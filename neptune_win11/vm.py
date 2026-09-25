from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

from .state import InstallState


PREFIX = Path("/opt/neptune")
QEMU = PREFIX / "bin/qemu-system-x86_64"
QEMU_IMG = PREFIX / "bin/qemu-img"
OVMF_CODE = Path("/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd")
OVMF_VARS_TEMPLATE = Path("/usr/share/edk2/x64/OVMF_VARS.4m.fd")


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_for_socket(path: Path, process: subprocess.Popen[bytes], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise RuntimeError(f"process exited before creating {path}")
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {path}")


def qmp(path: Path, command: dict[str, object]) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(path))
        stream = connection.makefile("rwb", buffering=0)
        json.loads(stream.readline())
        stream.write(b'{"execute":"qmp_capabilities"}\n')
        json.loads(stream.readline())
        stream.write(json.dumps(command).encode() + b"\n")
        while True:
            response = json.loads(stream.readline())
            if "return" in response or "error" in response:
                return response


def prepare_vm_files(state_root: Path) -> dict[str, Path]:
    vm = state_root / "vm"
    logs = state_root / "logs"
    vm.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    paths = {
        "vm": vm,
        "logs": logs,
        "disk": vm / "windows.qcow2",
        "vars": vm / "OVMF_VARS.4m.fd",
        "tpm": vm / "tpm",
        "tpm_socket": vm / "swtpm.sock",
        "qmp": vm / "qmp.sock",
        "spice": vm / "spice.sock",
        "qemu_log": logs / "qemu.log",
        "swtpm_log": logs / "swtpm.log",
        "screenshot": logs / "install-progress.ppm",
    }
    paths["tpm"].mkdir(exist_ok=True)
    if not paths["disk"].exists():
        subprocess.run(
            [str(QEMU_IMG), "create", "-f", "qcow2", str(paths["disk"]), "128G"],
            check=True,
        )
    if not paths["vars"].exists():
        shutil.copy2(OVMF_VARS_TEMPLATE, paths["vars"])
    return paths


def start_tpm(paths: dict[str, Path]) -> tuple[subprocess.Popen[bytes], object]:
    paths["tpm_socket"].unlink(missing_ok=True)
    log = paths["swtpm_log"].open("wb")
    process = subprocess.Popen([
        "swtpm", "socket", "--tpm2",
        "--tpmstate", f"dir={paths['tpm']}",
        "--ctrl", f"type=unixio,path={paths['tpm_socket']},terminate",
        "--flags", "not-need-init,startup-clear",
    ], stdout=log, stderr=subprocess.STDOUT)
    wait_for_socket(paths["tpm_socket"], process)
    return process, log


def common_qemu(paths: dict[str, Path]) -> list[str]:
    return [
        str(QEMU), "-name", "neptune-win11",
        "-machine", "q35,accel=kvm", "-enable-kvm", "-cpu", "host",
        "-smp", os.environ.get("NEPTUNE_CPUS", "8"),
        "-m", os.environ.get("NEPTUNE_RAM", "8G"),
        "-drive", f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}",
        "-drive", f"if=pflash,format=raw,file={paths['vars']}",
        "-chardev", f"socket,id=chrtpm,path={paths['tpm_socket']}",
        "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
        "-device", "tpm-tis,tpmdev=tpm0",
        "-drive", f"if=none,id=osdisk,format=qcow2,file={paths['disk']},discard=unmap",
        "-device", "nvme,drive=osdisk,serial=NEPTUNEWIN11",
        "-device", "qemu-xhci,id=xhci", "-device", "usb-kbd,bus=xhci.0",
        "-device", "usb-tablet,bus=xhci.0",
        "-device", "e1000e,netdev=net0", "-netdev", "user,id=net0",
        "-monitor", "none", "-qmp", f"unix:{paths['qmp']},server=on,wait=off",
    ]


def run_qemu(arguments: list[str], paths: dict[str, Path]) -> tuple[subprocess.Popen[bytes], object]:
    for key in ("qmp", "spice"):
        paths[key].unlink(missing_ok=True)
    log = paths["qemu_log"].open("wb")
    process = subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT)
    wait_for_socket(paths["qmp"], process)
    return process, log


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def install_windows(iso: Path, state_root: Path, state_file: Path) -> int:
    state = InstallState.load(state_file)
    if state.phase not in {"media-ready", "install-failed"}:
        raise ValueError(f"installation requires media-ready state, found {state.phase}")
    iso = iso.resolve()
    media = state_root / "media"
    seed = media / "unattend.img"
    guest_tools = media / "utm-guest-tools-0.1.273.iso"
    for required in (iso, seed, guest_tools):
        if not required.is_file():
            raise ValueError(f"required installation media is missing: {required}")

    paths = prepare_vm_files(state_root)
    state.phase = "installing"
    state.detail = "Windows Setup is running"
    state.save(state_file)
    tpm_process: subprocess.Popen[bytes] | None = None
    qemu_process: subprocess.Popen[bytes] | None = None
    tpm_log = qemu_log = None
    try:
        tpm_process, tpm_log = start_tpm(paths)
        arguments = common_qemu(paths) + [
            "-drive", f"if=none,id=windows-media,format=raw,readonly=on,file={iso}",
            "-device", "ide-cd,bus=ide.0,drive=windows-media,bootindex=1",
            "-drive", f"if=none,id=guest-tools,format=raw,readonly=on,file={guest_tools}",
            "-device", "ide-cd,bus=ide.1,drive=guest-tools",
            "-drive", f"if=floppy,format=raw,file={seed}",
            "-device", "virtio-vga",
            "-spice", f"unix=on,addr={paths['spice']},gl=off,disable-ticketing=on",
            "-display", "none",
        ]
        qemu_process, qemu_log = run_qemu(arguments, paths)
        started = time.monotonic()
        print(f"Windows installation started; QEMU log: {paths['qemu_log']}", flush=True)
        print(
            f"Progress snapshots will be reported every "
            f"{os.environ.get('NEPTUNE_PROGRESS_INTERVAL', '30')} seconds.",
            flush=True,
        )
        time.sleep(2)
        for _ in range(5):
            qmp(paths["qmp"], {
                "execute": "send-key",
                "arguments": {"keys": [{"type": "qcode", "data": "spc"}]},
            })
            time.sleep(1)

        timeout = int(os.environ.get("NEPTUNE_INSTALL_TIMEOUT", "10800"))
        progress_interval = int(os.environ.get("NEPTUNE_PROGRESS_INTERVAL", "30"))
        if progress_interval < 5:
            raise ValueError("NEPTUNE_PROGRESS_INTERVAL must be at least 5 seconds")
        deadline = time.monotonic() + timeout
        next_capture = 0.0
        previous_digest: str | None = None
        unchanged_captures = 0
        while qemu_process.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"Windows installation exceeded {timeout} seconds")
            if now >= next_capture:
                try:
                    capture = qmp(paths["qmp"], {
                        "execute": "screendump",
                        "arguments": {"filename": str(paths["screenshot"])},
                    })
                    if "error" in capture:
                        raise RuntimeError(str(capture["error"]))
                    digest = file_digest(paths["screenshot"])
                    if previous_digest is None:
                        display = "display captured"
                    elif digest != previous_digest:
                        display = "display changed"
                        unchanged_captures = 0
                    else:
                        unchanged_captures += 1
                        display = f"display unchanged for {unchanged_captures} capture(s)"
                    previous_digest = digest
                    status = qmp(paths["qmp"], {"execute": "query-status"})
                    vm_status = str(status.get("return", {}).get("status", "unknown"))
                    elapsed = format_elapsed(now - started)
                    message = f"[{elapsed}] VM {vm_status}; {display}"
                    if unchanged_captures >= 10:
                        message += "; check the saved framebuffer if this is unexpected"
                    print(f"{message}; {paths['screenshot']}", flush=True)
                    InstallState(phase="installing", detail=message).save(state_file)
                except (OSError, RuntimeError, TimeoutError, ValueError) as error:
                    elapsed = format_elapsed(now - started)
                    print(f"[{elapsed}] Progress capture failed: {error}", flush=True)
                next_capture = now + progress_interval
            time.sleep(1)
        if qemu_process.returncode != 0:
            raise RuntimeError(f"QEMU exited with status {qemu_process.returncode}")

        marker = subprocess.run(
            ["mtype", "-i", str(seed), "::/complete.txt"],
            check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if marker.returncode:
            raise RuntimeError("Windows powered off without the guest completion marker")
        InstallState(phase="installed", detail=marker.stdout.strip()).save(state_file)
        print("Windows installation completed and the guest marker was verified.", flush=True)
        return 0
    except Exception:
        InstallState(phase="install-failed", detail=f"See {paths['qemu_log']}").save(state_file)
        raise
    finally:
        stop_process(qemu_process)
        stop_process(tpm_process)
        if qemu_log:
            qemu_log.close()
        if tpm_log:
            tpm_log.close()


def render_node() -> str:
    nodes = sorted(Path("/dev/dri").glob("renderD*"))
    if not nodes:
        raise RuntimeError("no DRM render node is available")
    return str(nodes[0])


def start_vm(state_root: Path, state_file: Path) -> int:
    state = InstallState.load(state_file)
    # A SIGKILL or host crash can leave the persisted phase at "running" even
    # though the named Podman container is gone. The host launcher guarantees
    # that only one named VM container can exist, so that stale phase is safe
    # to recover here.
    if state.phase not in {"installed", "stopped", "running"}:
        raise ValueError(f"accelerated start requires installed state, found {state.phase}")
    paths = prepare_vm_files(state_root)
    tpm_process: subprocess.Popen[bytes] | None = None
    qemu_process: subprocess.Popen[bytes] | None = None
    viewer_process: subprocess.Popen[bytes] | None = None
    tpm_log = qemu_log = None

    def terminate(_signum: int, _frame: object) -> None:
        stop_process(qemu_process)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        tpm_process, tpm_log = start_tpm(paths)
        arguments = common_qemu(paths) + [
            "-device", "virtio-vga-gl,blob=true,venus=on,neptune=true,hostmem=4G,event_idx=on",
            "-display", f"egl-headless,rendernode={render_node()}",
            "-spice", f"unix=on,addr={paths['spice']},gl=off,disable-ticketing=on",
        ]
        qemu_process, qemu_log = run_qemu(arguments, paths)
        wait_for_socket(paths["spice"], qemu_process)
        viewer = paths["vm"] / "viewer.vv"
        viewer.write_text(f"[virt-viewer]\ntype=spice\nunix-path={paths['spice']}\n", encoding="utf-8")
        try:
            viewer_process = subprocess.Popen(["remote-viewer", str(viewer)])
        except OSError as error:
            print(f"Viewer could not start: {error}")
        InstallState(phase="running", detail="Neptune acceleration active").save(state_file)
        result = qemu_process.wait()
        if result:
            raise RuntimeError(f"QEMU exited with status {result}")
        InstallState(phase="stopped", detail="VM powered off").save(state_file)
        return 0
    finally:
        stop_process(viewer_process)
        stop_process(qemu_process)
        stop_process(tpm_process)
        if qemu_log:
            qemu_log.close()
        if tpm_log:
            tpm_log.close()


def shutdown_vm(state_root: Path) -> int:
    qmp_socket = state_root / "vm/qmp.sock"
    if not qmp_socket.exists():
        raise RuntimeError("QMP socket is missing; the VM is not running")
    response = qmp(qmp_socket, {"execute": "system_powerdown"})
    if "error" in response:
        raise RuntimeError(f"guest shutdown request failed: {response['error']}")
    print("Guest shutdown requested.")
    return 0
