from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ElementTree

from .state import InstallState


GUEST_TOOLS_URL = (
    "https://github.com/utmapp/qemu/releases/download/v10.0.12-utm/"
    "utm-guest-tools-0.1.273.iso"
)
GUEST_TOOLS_SHA256 = "7d2c0343e92358ad5e65078b08ec1dad873eb91b3c154aef60531bf6c2f04601"
PRODUCT_KEY = "W269N-WFGWX-YVC9B-4J6C9-T83GX"
TEMPLATE_ROOT = Path("/opt/neptune/app/unattended")


def checked(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_guest_tools(destination: Path) -> None:
    if destination.exists() and sha256(destination) == GUEST_TOOLS_SHA256:
        print(f"Guest tools: verified cached {destination}")
        return

    temporary = destination.with_suffix(".download")
    temporary.unlink(missing_ok=True)
    print(f"Downloading guest tools from {GUEST_TOOLS_URL}")
    with urllib.request.urlopen(GUEST_TOOLS_URL, timeout=60) as response:
        with temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
    actual = sha256(temporary)
    if actual != GUEST_TOOLS_SHA256:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            "guest-tools checksum mismatch; expected "
            f"{GUEST_TOOLS_SHA256}, received {actual}"
        )
    temporary.replace(destination)
    print(f"Guest tools: verified {destination}")


def find_install_archive(iso: Path) -> str:
    listing = checked(["7z", "l", "-ba", str(iso)], capture=True)
    for line in listing.splitlines():
        candidate = line.split()[-1] if line.split() else ""
        if re.fullmatch(r"sources/install\.(?:wim|esd)", candidate, re.IGNORECASE):
            return candidate
    raise ValueError("Windows ISO has no sources/install.wim or install.esd")


def image_index(image: Path, edition: str = "Windows 11 Pro") -> int:
    information = checked(["wimlib-imagex", "info", str(image)], capture=True)
    current: int | None = None
    available: list[str] = []
    for line in information.splitlines():
        if line.startswith("Index:"):
            current = int(line.split(":", 1)[1].strip())
        elif line.startswith("Name:") and current is not None:
            name = line.split(":", 1)[1].strip()
            available.append(name)
            if name == edition:
                return current
    raise ValueError(f"edition {edition!r} not found; available: {', '.join(available)}")


def render_unattend(index: int, password: str) -> str:
    replacements = {
        "@@IMAGE_INDEX@@": str(index),
        "@@USERNAME@@": "neptune",
        "@@COMPUTER_NAME@@": "NEPTUNE-W11",
        "@@LOCALE@@": "en-US",
        "@@PRODUCT_KEY@@": PRODUCT_KEY,
        "@@PASSWORD@@": password,
    }
    rendered = (TEMPLATE_ROOT / "Autounattend.xml.in").read_text(encoding="utf-8")
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    ElementTree.fromstring(rendered)
    return rendered


def create_seed(destination: Path, xml: str) -> None:
    with tempfile.TemporaryDirectory(prefix="neptune-seed-") as directory:
        staging = Path(directory)
        (staging / "Autounattend.xml").write_text(xml, encoding="utf-8")
        shutil.copy2(TEMPLATE_ROOT / "setup.ps1", staging / "setup.ps1")
        with destination.open("wb") as stream:
            stream.truncate(1440 * 1024)
        checked(["mkfs.fat", "-F", "12", "-n", "NEPTUNE_CFG", str(destination)])
        checked([
            "mcopy", "-i", str(destination),
            str(staging / "Autounattend.xml"), str(staging / "setup.ps1"), "::/",
        ])


def prepare_media(iso: Path, state_root: Path, state_file: Path) -> int:
    iso = iso.resolve()
    if not iso.is_file():
        raise ValueError(f"Windows ISO is not readable: {iso}")

    media = state_root / "media"
    media.mkdir(parents=True, exist_ok=True)
    archive = find_install_archive(iso)
    print(f"Windows archive: {archive}")
    with tempfile.TemporaryDirectory(prefix="neptune-wim-") as directory:
        extraction = Path(directory)
        checked(["7z", "x", "-bd", "-y", f"-o{extraction}", str(iso), archive])
        index = image_index(extraction / archive)
    print(f"Windows edition: Windows 11 Pro (index {index})")

    credentials = state_root / "windows-credentials.txt"
    if credentials.exists():
        password = credentials.read_text(encoding="utf-8").split("password=", 1)[1].splitlines()[0]
    else:
        password = f"Npt-{secrets.token_hex(12)}A1!"
        credentials.write_text(f"username=neptune\npassword={password}\n", encoding="utf-8")
        os.chmod(credentials, 0o600)

    seed = media / "unattend.img"
    create_seed(seed, render_unattend(index, password))
    download_guest_tools(media / "utm-guest-tools-0.1.273.iso")
    InstallState(phase="media-ready", detail=f"Windows 11 Pro index {index}").save(state_file)
    print(f"Unattended media: {seed}")
    print(f"Credentials: {credentials}")
    return 0
