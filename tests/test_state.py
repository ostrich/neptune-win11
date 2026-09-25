import tempfile
from pathlib import Path
import unittest

from neptune_win11.state import InstallState


class InstallStateTest(unittest.TestCase):
    def test_missing_file_is_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = InstallState.load(Path(directory) / "state.json")
        self.assertEqual(state.phase, "not-started")

    def test_atomic_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            InstallState(phase="host-ready", detail="probe passed").save(path)
            state = InstallState.load(path)
        self.assertEqual(state.phase, "host-ready")
        self.assertEqual(state.detail, "probe passed")


if __name__ == "__main__":
    unittest.main()
