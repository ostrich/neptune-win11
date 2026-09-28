import fcntl
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import termios
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "neptune-win11"
FAKE_PODMAN = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
  'container exists') test -e "$FAKE_CONTAINER" ;;
  'container inspect') cat "$FAKE_RUNNING" ;;
  'image exists') test -e "$FAKE_IMAGE" ;;
  'image rm') rm "$FAKE_IMAGE" ;;
  *)
    case "$1" in
      exec) test -e "$FAKE_KEEP_RUNNING" || rm -f "$FAKE_CONTAINER" ;;
      stop) test ! -e "$FAKE_STOP_FAIL" || exit 125; rm -f "$FAKE_CONTAINER" ;;
      rm) rm -f "$FAKE_CONTAINER" ;;
      *) exit 125 ;;
    esac ;;
esac
"""


class CleanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        binary = self.root / "bin"
        binary.mkdir()
        podman = binary / "podman"
        podman.write_text(FAKE_PODMAN)
        podman.chmod(0o755)
        sleep = binary / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        sleep.chmod(0o755)
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "windows.qcow2").write_text("keep")
        self.container = self.root / "container"
        self.image = self.root / "image"
        self.log = self.root / "podman.log"
        self.env = os.environ.copy()
        self.env.update(
            PATH=f"{binary}:{os.environ['PATH']}",
            HOME=str(self.root),
            NEPTUNE_STATE_DIR=str(self.state),
            NEPTUNE_CONTAINER_NAME="test-container",
            NEPTUNE_IMAGE="localhost/test-image:dev",
            FAKE_CONTAINER=str(self.container),
            FAKE_IMAGE=str(self.image),
            FAKE_RUNNING=str(self.root / "running"),
            FAKE_KEEP_RUNNING=str(self.root / "keep-running"),
            FAKE_STOP_FAIL=str(self.root / "stop-fail"),
            FAKE_LOG=str(self.log),
        )

    def run_clean(self, answer: str | None = "clean", *args: str) -> subprocess.CompletedProcess[str]:
        if answer is None:
            return subprocess.run(
                [str(LAUNCHER), "clean", *args], env=self.env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                start_new_session=True, check=False,
            )
        master, slave = pty.openpty()

        def controlling_terminal() -> None:
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        try:
            process = subprocess.Popen(
                [str(LAUNCHER), "clean", *args], env=self.env,
                stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=controlling_terminal,
            )
            os.close(slave)
            slave = -1
            os.write(master, (answer + "\n").encode())
            output = bytearray()
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            return subprocess.CompletedProcess(
                process.args, process.wait(), output.decode(errors="replace"), ""
            )
        finally:
            os.close(master)
            if slave >= 0:
                os.close(slave)

    def test_full_reset_uses_configured_names(self) -> None:
        self.container.touch()
        self.image.touch()
        (self.root / "running").write_text("false")
        result = self.run_clean()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.container.exists())
        self.assertFalse(self.image.exists())
        log = self.log.read_text()
        self.assertIn("rm test-container", log)
        self.assertIn("image rm localhost/test-image:dev", log)

    def test_cancel_and_missing_terminal_leave_resources(self) -> None:
        self.image.touch()
        for answer in ("no", None):
            result = self.run_clean(answer)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.state.exists())
            self.assertTrue(self.image.exists())
        self.assertFalse(self.log.exists())

    def test_missing_resources_are_harmless(self) -> None:
        (self.state / "windows.qcow2").unlink()
        self.state.rmdir()
        result = self.run_clean()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_stop_failure_preserves_image_and_data(self) -> None:
        self.container.touch()
        self.image.touch()
        (self.root / "running").write_text("true")
        (self.root / "keep-running").touch()
        (self.root / "stop-fail").touch()
        result = self.run_clean()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state.exists())
        self.assertTrue(self.image.exists())
        self.assertTrue(self.container.exists())

    def test_rejects_unsafe_state_paths(self) -> None:
        self.image.touch()
        for path in (self.root, LAUNCHER.parent, LAUNCHER.parent.parent, Path("/"), Path("/tmp")):
            self.env["NEPTUNE_STATE_DIR"] = str(path)
            result = self.run_clean()
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.image.exists())
        link = self.root / "state-link"
        link.symlink_to(self.state, target_is_directory=True)
        self.env["NEPTUNE_STATE_DIR"] = str(link)
        result = self.run_clean()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state.exists())


if __name__ == "__main__":
    unittest.main()
