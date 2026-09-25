# neptune-win11

`neptune-win11` creates a GPU-accelerated Windows 11 virtual machine on Linux
without PCI GPU passthrough.

Supply a Windows 11 ISO and it creates a VM, installs Windows 11 Pro
unattended, installs the guest graphics driver, and verifies that setup
finished. No interaction with Windows Setup is required. When the installer
shuts down, you have a persistent Windows VM ready to boot with the
experimental Neptune graphics stack.

QEMU, DXVK, virglrenderer, firmware, guest tools, and the viewer stay inside a
rootless Podman container. The Windows ISO is the only installation media you
provide.

This is experimental software. It has reached the Windows desktop on AMD and
NVIDIA hosts under Wayland, but expect rough edges.

Credit to the contributors behind [UTM QEMU](https://github.com/utmapp/qemu),
[UTM virglrenderer](https://github.com/utmapp/virglrenderer), and
[osy/dxvk](https://github.com/osy/dxvk), and to [neuromaniacMD's Linux KVM
report](https://github.com/utmapp/UTM/issues/7812) for documenting the AMD/RADV
setup and Linux SPICE/GBM fix.

## Requirements

- Linux x86-64 with KVM available to your user
- Podman 5 or newer with a rootless OCI runtime such as `crun`
- A Vulkan-capable GPU and accessible DRM render node
- NVIDIA Container Toolkit on NVIDIA hosts
- A Windows 11 x86-64 ISO

Need an ISO? The
[Massgrave Windows 11 download page](https://massgrave.dev/windows_11_links)
lists official Microsoft download links. An x64 consumer ISO is the simplest
choice; the installer selects Windows 11 Pro from it.

Install the host packages for your distribution. A working GPU driver must
already be installed.

### Arch Linux

```sh
# AMD
sudo pacman -S --needed podman crun mesa vulkan-radeon

# NVIDIA
sudo pacman -S --needed podman crun nvidia-container-toolkit
```

### Debian and Ubuntu

```sh
sudo apt update
sudo apt install podman crun

# AMD
sudo apt install mesa-vulkan-drivers

# NVIDIA
sudo apt install nvidia-container-toolkit
```

Use a distribution release or package source that provides Podman 5 or newer.
The NVIDIA package requires
[NVIDIA's apt repository](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#with-apt-ubuntu-debian).

### Fedora

```sh
sudo dnf install podman crun

# AMD
sudo dnf install mesa-vulkan-drivers

# NVIDIA
sudo dnf install nvidia-container-toolkit
```

The NVIDIA package requires
[NVIDIA's RPM repository](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#with-dnf-rhel-centos-fedora-amazon-linux).

The project does not invoke your host package manager or modify `/etc`.

## Install and run

Build the container and check that KVM and Vulkan work inside it:

```sh
./neptune-win11 build
./neptune-win11 container-doctor
```

Prepare the unattended media and install Windows 11 Pro:

```sh
./neptune-win11 prepare /path/to/windows-11.iso
./neptune-win11 install /path/to/windows-11.iso
```

Installation progress is reported every 30 seconds. The process normally
reboots Windows several times and finishes by shutting down the VM.

Start the accelerated VM:

```sh
./neptune-win11 start
```

Use another terminal to check its state or request a clean shutdown:

```sh
./neptune-win11 status
./neptune-win11 stop
```

## Data and configuration

VM data is stored in `$XDG_DATA_HOME/neptune-win11`, or
`~/.local/share/neptune-win11` when `XDG_DATA_HOME` is unset. Set
`NEPTUNE_STATE_DIR` to use another location.

The default Windows login is:

- Username: `neptune`
- Password: `password`

Change the password after the first boot if the VM is accessible to untrusted
users. The installer also records the login in `windows-credentials.txt` under
the state directory and creates a dynamically allocated 128 GB qcow2 disk
alongside the other VM state.

Useful overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEPTUNE_CPUS` | `8` | VM virtual CPU count |
| `NEPTUNE_RAM` | `8G` | VM memory |
| `NEPTUNE_PROGRESS_INTERVAL` | `30` | Install heartbeat interval in seconds |
| `NEPTUNE_IMAGE` | `localhost/neptune-win11:dev` | Container image name |

The latest installation framebuffer is written to
`logs/install-progress.ppm` under the state directory. Automatic viewer
reconnection is not currently implemented.

## Source revisions

| Component | Revision |
| --- | --- |
| DXVK | `404240fdacf47470b02c76d6e684639a95dc7387` |
| virglrenderer | `111a6d89a466f35dad9ed5fd05623aa9edc1db6d` |
| QEMU | `b795d6de88fc52cb6ff061e0e034be51d8e9c474` |

Viewer startup and recovery notes are in
[`docs/ui-navigation.md`](docs/ui-navigation.md).
