# UI navigation notes

## Reach the accelerated Windows desktop

- Last verified: Windows 11 25H2 at 1280x800 in a Wayland session with
  rootless Podman.
- Starting state: `./neptune-win11 status` reports `installed` or `stopped`,
  and no `neptune-win11-vm` container is running.
- Run `./neptune-win11 start`. Identify the `remote-viewer` window titled
  `neptune-win11`; the launcher starts it inside the container through the
  host Wayland socket.
- Readiness check: require visible Windows desktop content in the viewer. A
  connected black window is not ready. QMP `screendump` is not a valid check
  for this GL-backed path: it reports **Display output is not active** even
  while SPICE readback is rendering the desktop correctly.
- Recovery: if the viewer closes while the named container remains running,
  stop the VM with `./neptune-win11 stop` before restarting. Automatic viewer
  reconnection is not implemented yet.
- Shutdown: run `./neptune-win11 stop`. The launcher requests an ACPI shutdown
  and waits for the guest and container to exit.
- Verified scope: AMD and NVIDIA hosts under Wayland. X11, additional
  resolutions, and viewer reconnection remain untested.
