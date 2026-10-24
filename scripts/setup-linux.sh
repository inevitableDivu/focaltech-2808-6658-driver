#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly LIBFPRINT_VERSION="1.94.100"
readonly SOURCE_DIR="$PROJECT_ROOT/build/libfprint-source"
readonly BUILD_DIR="$PROJECT_ROOT/build/libfprint-build"

DRY_RUN=0
SKIP_PACKAGES=0
SKIP_PYTHON=0
SKIP_LIBFPRINT=0

usage() {
  cat <<'EOF'
Usage: scripts/setup-linux.sh [options]

Install build/runtime packages, create a project-local Python virtualenv, and
build the patched upstream libfprint locally (without installing it system-wide).

Supported package-manager families: Debian/Ubuntu (apt), Fedora/RHEL (dnf),
Arch Linux (pacman), and openSUSE/SUSE (zypper). Detection uses ID and
ID_LIKE from /etc/os-release.

Options:
  --dry-run          Print package/build actions without changing the system or project
  --skip-packages    Do not install operating-system packages
  --skip-python      Do not create the Python virtualenv or install Python requirements
  --skip-libfprint   Do not clone, patch, or build libfprint
  -h, --help         Show this help
EOF
}

say() {
  printf '\n==> %s\n' "$*"
}

run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if (( ! DRY_RUN )); then
    "$@"
  fi
}

as_root() {
  if (( DRY_RUN && EUID != 0 )); then
    run sudo "$@"
  elif (( EUID == 0 )); then
    run "$@"
  elif command -v sudo >/dev/null 2>&1; then
    run sudo "$@"
  else
    printf 'Error: installing system packages requires root or sudo.\n' >&2
    exit 1
  fi
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-packages) SKIP_PACKAGES=1 ;;
    --skip-python) SKIP_PYTHON=1 ;;
    --skip-libfprint) SKIP_LIBFPRINT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

install_packages() {
  local distro_id distro_like
  distro_id="$(
    . /etc/os-release
    printf '%s' "${ID:-unknown}"
  )"
  distro_like="$(
    . /etc/os-release
    printf '%s' "${ID_LIKE:-}"
  )"

  case "$distro_id:$distro_like" in
    debian:*|ubuntu:*|linuxmint:*|pop:*|*:*debian*|*:*ubuntu*)
      as_root apt-get update
      as_root apt-get install -y \
        build-essential git meson ninja-build pkg-config \
        libglib2.0-dev libgudev-1.0-dev libgusb-dev libusb-1.0-0-dev \
        libpixman-1-dev libssl-dev libcairo2-dev gobject-introspection \
        python3 python3-venv python3-pip python3-usb python3-numpy python3-pil \
        fprintd usbutils
      ;;
    fedora:*|rhel:*|centos:*|rocky:*|almalinux:*|ol:*|*:*fedora*|*:*rhel*)
      as_root dnf install -y \
        gcc gcc-c++ make git meson ninja-build pkgconf-pkg-config \
        glib2-devel libgudev-devel libgusb-devel libusb1-devel \
        pixman-devel openssl-devel cairo-devel gobject-introspection-devel \
        python3 python3-pip python3-pyusb python3-numpy python3-pillow fprintd usbutils
      ;;
    arch:*|manjaro:*|endeavouros:*|*:*arch*)
      as_root pacman -S --needed --noconfirm \
        base-devel git meson ninja pkgconf glib2 glib2-devel libgudev libgusb libusb \
        pixman openssl cairo gobject-introspection \
        python python-pip python-virtualenv python-pyusb python-numpy python-pillow \
        fprintd usbutils
      ;;
    opensuse*:*|sles:*|sled:*|*:*suse*)
      as_root zypper --non-interactive install \
        gcc gcc-c++ make git meson ninja pkg-config \
        glib2-devel libgudev-1_0-devel libgusb-devel libusb-1_0-devel \
        libpixman-1-0-devel libopenssl-devel cairo-devel gobject-introspection-devel \
        python3 python3-pip python3-pyusb python3-numpy python3-Pillow fprintd usbutils
      ;;
    *)
      printf 'Unsupported Linux distribution ID "%s". Supported: Debian/Ubuntu, Fedora, Arch, openSUSE.\n' \
        "$distro_id${distro_like:+ (ID_LIKE=$distro_like)}" >&2
      exit 1
      ;;
  esac
}

check_glib_mkenums() {
  local mkenums distro_id hint

  if ! pkg-config --exists glib-2.0; then
    printf 'Error: GLib development metadata (glib-2.0.pc) was not found. Install the GLib development package and retry.\n' >&2
    exit 1
  fi

  mkenums="$(pkg-config --variable=glib_mkenums glib-2.0)"
  if [[ -n "$mkenums" && -x "$mkenums" ]]; then
    return
  fi

  distro_id="$(
    . /etc/os-release
    printf '%s' "${ID:-unknown}"
  )"
  case "$distro_id" in
    arch|manjaro|endeavouros) hint="Install it with: sudo pacman -S glib2-devel" ;;
    fedora|rhel|centos|rocky|almalinux) hint="Install it with: sudo dnf install glib2-devel" ;;
    opensuse*|sles|sled) hint="Install it with: sudo zypper install glib2-devel" ;;
    *) hint="Install or repair your distribution's GLib development package (for Debian/Ubuntu: sudo apt-get install --reinstall libglib2.0-dev)." ;;
  esac

  printf "Error: GLib's pkg-config metadata points to '%s' for glib-mkenums, but that executable is missing or not executable.\n%s\n" \
    "${mkenums:-<empty>}" "$hint" >&2
  exit 1
}

if (( ! SKIP_PACKAGES )); then
  say "Installing operating-system dependencies"
  install_packages
fi

if (( ! SKIP_LIBFPRINT && ! DRY_RUN )); then
  check_glib_mkenums
fi

if (( ! SKIP_PYTHON )); then
  say "Setting up the project-local Python environment"
  if (( DRY_RUN )); then
    printf '+ python3 -m venv %q\n' "$PROJECT_ROOT/.venv"
    printf '+ %q -m pip install -r %q\n' "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/requirements.txt"
  else
    python3 -m venv "$PROJECT_ROOT/.venv"
    "$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
    "$PROJECT_ROOT/.venv/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"
  fi
fi

if (( ! SKIP_LIBFPRINT )); then
  say "Building upstream libfprint v$LIBFPRINT_VERSION with the experimental driver"
  if (( DRY_RUN )); then
    printf 'Would clone v%s into %s, apply libfprint-driver/meson.patch, and build in %s.\n' \
      "$LIBFPRINT_VERSION" "$SOURCE_DIR" "$BUILD_DIR"
  else
    mkdir -p "$PROJECT_ROOT/build"
    if [[ ! -d "$SOURCE_DIR/.git" ]]; then
      if [[ -e "$SOURCE_DIR" ]]; then
        printf 'Error: %s exists but is not a Git checkout; move it aside before retrying.\n' \
          "$SOURCE_DIR" >&2
        exit 1
      fi
      git clone --depth 1 --branch "v$LIBFPRINT_VERSION" \
        https://gitlab.freedesktop.org/libfprint/libfprint.git "$SOURCE_DIR"
    else
      git -C "$SOURCE_DIR" fetch --depth 1 origin "refs/tags/v$LIBFPRINT_VERSION:refs/tags/v$LIBFPRINT_VERSION"
      git -C "$SOURCE_DIR" checkout --detach "v$LIBFPRINT_VERSION"
    fi

    cp "$PROJECT_ROOT/libfprint-driver/focaltech_6658.c" "$SOURCE_DIR/libfprint/drivers/"
    if git -C "$SOURCE_DIR" apply --reverse --check "$PROJECT_ROOT/libfprint-driver/meson.patch" \
      >/dev/null 2>&1; then
      printf 'libfprint Meson patch is already applied.\n'
    else
      git -C "$SOURCE_DIR" apply --check "$PROJECT_ROOT/libfprint-driver/meson.patch"
      git -C "$SOURCE_DIR" apply "$PROJECT_ROOT/libfprint-driver/meson.patch"
    fi
    if [[ -f "$BUILD_DIR/build.ninja" ]]; then
      meson setup --wipe "$BUILD_DIR" "$SOURCE_DIR" \
        --prefix=/opt/focaltech-6658-libfprint \
        --libdir=lib \
        -Ddoc=false \
        -Dinstalled-tests=false \
        -Ddrivers=all
    else
      meson setup "$BUILD_DIR" "$SOURCE_DIR" \
        --prefix=/opt/focaltech-6658-libfprint \
        --libdir=lib \
        -Ddoc=false \
        -Dinstalled-tests=false \
        -Ddrivers=all
    fi
    meson compile -C "$BUILD_DIR"
  fi
fi

cat <<EOF

Setup stage complete.
- Python toolkit environment: $PROJECT_ROOT/.venv
- libfprint build directory: $BUILD_DIR

The build is not installed system-wide. To connect it to fprintd, review and
explicitly run scripts/link-fprintd.sh --install-system. Then use
scripts/test-fprintd.sh to inspect the daemon or explicitly request enrollment.
Only USB ID 2808:6658 is registered by this experimental driver.
EOF
