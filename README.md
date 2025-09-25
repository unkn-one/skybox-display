# skybox-display

A lightweight Raspberry Pi UI for **dump1090**, designed to run **directly on the framebuffer** (no desktop environment).
It ships as a `.deb` that bundles its own Python virtual environment, so you don’t need to install Python packages system-wide.

* **Executable:** `skybox-display`
* **Service:** `skybox-display.service`
* **Install path (venv):** `/opt/skybox-display/.venv`
* **Wrapper:** `/usr/bin/skybox-display`
* **Target OS/Arch:** Debian/PI OS **Bookworm** on **arm64** (aarch64)

---

## Requirements

* Raspberry Pi running Debian / Raspberry Pi OS **Bookworm (arm64)**
* `dump1090` (or `dump1090-fa`) running on the device or reachable over the network
* System packages (pulled by the `.deb`):

  * `python3 (>= 3.11)`, `systemd`

> The app runs on the **framebuffer** and does not require X11/Wayland.

---

## Install

### Option A: Install a released `.deb`

1. Download `skybox-display_<VERSION>_arm64.deb` (e.g., from your GitHub Releases).
2. Install:

   ```bash
   sudo apt-get install ./skybox-display_<VERSION>_arm64.deb
   ```

   (Use `sudo dpkg -i <deb> && sudo apt-get -f install` if you prefer.)

The package’s post-install script will automatically:

* reload systemd units
* enable & start `skybox-display.service`

### Check status / logs

```bash
systemctl status skybox-display
journalctl -u skybox-display -e -n 200 -f
```

---

## Build from source

This project provides a **self-contained build** that uses **`python3 -m venv` + `pip`** and packages the result with `dpkg-deb`. No system-wide Python deps are installed.

### Build on the host (Pi or arm64 Debian)

Prereqs:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git dpkg-dev build-essential make
pip3 install -U setuptools-scm tomli
```

Build:

```bash
make deb
# artifact appears at: build/skybox-display_<VERSION>_arm64.deb
```

Install the locally built package:

```bash
sudo apt-get install ./build/skybox-display_*_arm64.deb
```

### Build in Docker (keeps your host clean)

Prereqs: Docker (with QEMU/binfmt if building arm64 on x86_64).

Build the image and the package:

```bash
make docker-deb
# or force arm64 platform build:
make docker-deb-arm64
```

The resulting `.deb` will be in `build/`.

---

## Running & service management

The installer enables and starts the service automatically. Manual controls:

```bash
sudo systemctl start skybox-display
sudo systemctl restart skybox-display
sudo systemctl stop skybox-display
systemctl status skybox-display
journalctl -u skybox-display -e -n 200 -f
```

---

## Uninstall

```bash
sudo systemctl disable --now skybox-display
sudo apt-get remove -y skybox-display
```

This removes the systemd unit and the installed package. (Data/config paths, if any, are not removed by default.)

---

## Notes & tips

* The `.deb` is built for **arm64** by default (`ARCH=arm64`). Building for other arches requires building on that arch (or compatible cross/QEMU setup) so the bundled venv matches the target Python ABI.
* The service launches `/usr/bin/skybox-display` which wraps `/opt/skybox-display/.venv/bin/skybox-display`.
* If you need environment tweaks (e.g., device nodes, permissions), add them to the systemd unit section in `scripts/build_deb.sh`.

