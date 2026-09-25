from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from .state import InstallState
from .media import prepare_media
from .vm import install_windows, shutdown_vm, start_vm


STATE_ROOT = Path(os.environ.get("NEPTUNE_STATE_ROOT", "/var/lib/neptune"))
STATE_FILE = STATE_ROOT / "state.json"
PREFIX = Path("/opt/neptune")


def run_checked(command: list[str], *, quiet: bool = False) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        if result.stdout and not quiet:
            print(result.stdout, file=sys.stderr, end="")
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout


def doctor() -> int:
    failures: list[str] = []
    checks = (
        ("KVM", Path("/dev/kvm").exists() and os.access("/dev/kvm", os.R_OK | os.W_OK)),
        ("QEMU", (PREFIX / "bin/qemu-system-x86_64").is_file()),
        ("DXVK D3D11", (PREFIX / "lib/libdxvk_d3d11.so").is_file()),
        ("DXVK DXGI", (PREFIX / "lib/libdxvk_dxgi.so").is_file()),
        ("virglrenderer", (PREFIX / "lib/libvirglrenderer.so").is_file()),
    )
    for name, passed in checks:
        print(f"{name}: {'ok' if passed else 'FAILED'}")
        if not passed:
            failures.append(name)

    try:
        summary = run_checked(["vulkaninfo", "--summary"], quiet=True)
        device = next(
            (line.split("=", 1)[1].strip() for line in summary.splitlines()
             if "deviceName" in line and "=" in line),
            "unknown device",
        )
        print(f"Vulkan: ok ({device})")
    except (OSError, RuntimeError) as error:
        print(f"Vulkan: FAILED ({error})")
        failures.append("Vulkan")

    if not failures:
        qemu = run_checked([str(PREFIX / "bin/qemu-system-x86_64"), "--version"])
        print(qemu.splitlines()[0])
        print("Container readiness: PASS")
        return 0

    print("Container readiness: FAIL: " + ", ".join(failures), file=sys.stderr)
    return 1


def status() -> int:
    state = InstallState.load(STATE_FILE)
    print(f"phase: {state.phase}")
    if state.detail:
        print(f"detail: {state.detail}")
    print(f"state: {STATE_FILE}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="neptune-win11")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="validate devices and the built stack")
    commands.add_parser("status", help="show persistent installer state")
    prepare = commands.add_parser("prepare", help="create unattended installation media")
    prepare.add_argument("--iso", type=Path, required=True)
    install = commands.add_parser("install", help="install Windows unattended")
    install.add_argument("--iso", type=Path, required=True)
    commands.add_parser("start", help="start the accelerated VM")
    commands.add_parser("shutdown", help="request a clean ACPI guest shutdown")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "doctor":
            return doctor()
        if arguments.command == "status":
            return status()
        if arguments.command == "prepare":
            return prepare_media(arguments.iso, STATE_ROOT, STATE_FILE)
        if arguments.command == "install":
            return install_windows(arguments.iso, STATE_ROOT, STATE_FILE)
        if arguments.command == "start":
            return start_vm(STATE_ROOT, STATE_FILE)
        if arguments.command == "shutdown":
            return shutdown_vm(STATE_ROOT)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"neptune-win11: {error}", file=sys.stderr)
        return 1
    raise AssertionError(arguments.command)
