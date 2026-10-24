# Linux setup and fprintd integration

This repository contains an experimental native libfprint driver for the FocalTech
sensor identified as USB **2808:6658**. The C backend also used to register
`2808:9366`, `2808:6652`, and `2808:9201`; those IDs are not backed by device
testing in this repository and are deliberately not registered now. Other IDs
are not claimed as supported.

Successful compilation is not evidence that enrollment or matching works. This
research prototype is not suitable for security-critical or daily authentication.
See the project README and `docs/PROTOCOL.md` for the sensor limitations.

## Supported setup environments

The setup script automates package installation for Debian/Ubuntu-family systems
using apt, Fedora/RHEL-family systems using dnf, Arch-family systems using
pacman, and openSUSE/SUSE-family systems using zypper. It uses `ID` and
`ID_LIKE` from `/etc/os-release` to recognize derivatives. Other distributions
are not auto-detected; install the equivalent compiler,
Meson/Ninja, GLib/GUsb/GUdev, USB, image, Python, and fprintd development/runtime
packages manually before building. Arch installs `glib2-devel` separately from
`glib2`, which provides the `glib-mkenums` build tool required by Meson. The
script checks that GLib's pkg-config metadata points to an executable tool before
starting the build and prints a distro-specific repair hint if it does not.
Package names can vary by release.

Run from the repository:

```sh
scripts/setup-linux.sh --dry-run
scripts/setup-linux.sh
```

The script installs OS packages through the detected package manager, creates a
project-local `.venv` for the Python diagnostic toolkit, and builds upstream
libfprint **v1.94.100** with the repository's driver patch. The patched source
and build are kept under `build/`. It does **not** install the custom library
system-wide. It does not add permissive USB rules, modify fprintd configuration,
or enroll a fingerprint.

To run the Python sensor diagnostic yourself:

```sh
.venv/bin/python python/cli.py --test
.venv/bin/python python/cli.py --capture private-frame.png
```

The Python tool opens the USB device and issues sensor commands; the capture
contains biometric data. Do not share or commit capture files.

## Integrate the custom libfprint build with fprintd

`fprintd` loads libfprint dynamically. A private Meson build is not automatically
visible to the system daemon. The explicit installer stages the build first:

```sh
scripts/link-fprintd.sh
scripts/link-fprintd.sh --install-system
```

The installer puts files under the isolated prefix
`/opt/focaltech-6658-libfprint` and refuses to overwrite existing files by
default. To update an existing project install, run
`scripts/link-fprintd.sh --install-system --update-existing`. This checks that
the existing prefix has exactly the staged package layout, that non-library
files and symlinks match, and that any existing integration files match this
project before replacing the library. The installer installs a narrowly
scoped udev `uaccess` rule for 2808:6658 (without setting world-writable
permissions), reloads and retriggers that device, and adds a systemd drop-in that makes only fprintd preload the custom
`/opt/focaltech-6658-libfprint/lib/libfprint-2.so.2`. It restarts fprintd only
if its service is active. The system-wide option is intentionally opt-in; the
library is outside general linker directories and the drop-in targets fprintd
only. Review the staged contents and your distribution's libfprint/fprintd
packaging before installing. Do not use this prototype on a machine where
fingerprint login is a required security control.

The install command does not remove files on uninstall. It prints the path to
the staged copy, which is retained for review. To undo it, use that staged file
list under `opt/focaltech-6658-libfprint` to remove only the files installed by
this project, remove
`/etc/udev/rules.d/70-focaltech-6658.rules` and
`/etc/systemd/system/fprintd.service.d/90-focaltech-libfprint.conf`, then run
`sudo systemctl daemon-reload`, `sudo udevadm control --reload-rules`, and
restart fprintd. Do not delete paths that existed before this project was
installed.

## Test through fprintd

First run the read-only check:

```sh
scripts/test-fprintd.sh
```

It reports an attached 2808:6658 device when `lsusb` is available and asks
fprintd to list the current user's enrolled prints. It does not enroll or
verify by default. To exercise sensor access and enrollment, explicitly run:

```sh
scripts/test-fprintd.sh --enroll
scripts/test-fprintd.sh --verify
```

Enrollment stores biometric data locally in fprintd. `fprintd-delete "$USER"`
removes all enrolled prints for that account, so use it only if that is
intended. If enrollment cannot access the device, check
the USB ID, daemon logs (`journalctl -u fprintd -b --no-pager`), and whether
fprintd is loading the isolated `/opt/focaltech-6658-libfprint` build. A
matching USB ID alone does not prove the sensor revision is compatible.
