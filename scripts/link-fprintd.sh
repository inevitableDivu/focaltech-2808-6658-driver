#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly BUILD_DIR="$PROJECT_ROOT/build/libfprint-build"
readonly INSTALL_ROOT="/opt/focaltech-6658-libfprint"
readonly UDEV_RULE_SOURCE="$PROJECT_ROOT/udev/70-focaltech-6658.rules"
readonly UDEV_RULE_DEST="/etc/udev/rules.d/70-focaltech-6658.rules"
readonly SYSTEMD_DROPIN_SOURCE="$PROJECT_ROOT/systemd/fprintd.service.d/90-focaltech-libfprint.conf"
readonly SYSTEMD_DROPIN_DEST="/etc/systemd/system/fprintd.service.d/90-focaltech-libfprint.conf"
STAGE_DIR=""

INSTALL_SYSTEM=0
UPDATE_EXISTING=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/link-fprintd.sh [--install-system] [--update-existing] [--dry-run]

Stage the project's libfprint build and, only when explicitly requested, install
its files under /opt/focaltech-6658-libfprint so the system fprintd daemon can
load the custom driver. Existing files are not overwritten unless
--update-existing is explicitly requested and the current installation matches
the expected project layout.

Options:
  --install-system  Perform the system-wide install and configure fprintd
  --update-existing Update a matching existing project install (requires --install-system)
  --dry-run         Print what would be done
  -h, --help        Show this help

This intentionally does not replace distribution files or place a library in a
general-purpose linker directory. A systemd drop-in preloads this library only
for fprintd; see docs/LINUX-SETUP.md first.
EOF
}

while (($#)); do
  case "$1" in
    --install-system) INSTALL_SYSTEM=1 ;;
    --update-existing) UPDATE_EXISTING=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if (( UPDATE_EXISTING && ! INSTALL_SYSTEM )); then
  printf 'Error: --update-existing requires --install-system.\n' >&2
  exit 2
fi

if (( DRY_RUN )); then
  if [[ -f "$BUILD_DIR/build.ninja" ]]; then
    printf 'Would stage Meson install files in a temporary directory and print its path.\n'
  else
    printf 'No build found at %s; run scripts/setup-linux.sh before staging.\n' "$BUILD_DIR"
  fi
  if (( INSTALL_SYSTEM )); then
    if (( UPDATE_EXISTING )); then
      printf 'Would verify and update the existing project install under %s, then refresh fprintd integration and restart fprintd if active.\n' \
        "$INSTALL_ROOT"
    else
      printf 'Would install non-conflicting files under %s, configure fprintd to preload the custom library, add a per-device uaccess rule, refresh systemd/udev state, and restart fprintd if active.\n' \
        "$INSTALL_ROOT"
    fi
  else
    printf 'No system changes requested. Re-run with --install-system to install.\n'
  fi
  exit 0
fi

if [[ ! -f "$BUILD_DIR/build.ninja" ]]; then
  printf 'Error: no libfprint build found at %s. Run scripts/setup-linux.sh first.\n' \
    "$BUILD_DIR" >&2
  exit 1
fi

if (( INSTALL_SYSTEM )); then
  if (( EUID == 0 )); then
    printf 'Error: do not run this script as root; run it as your user so Meson does not execute with elevated privileges.\n' >&2
    exit 1
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    printf 'Error: --install-system requires sudo for the final copy and system configuration.\n' >&2
    exit 1
  fi
  if ! command -v systemctl >/dev/null 2>&1 || ! systemctl cat fprintd.service >/dev/null 2>&1; then
    printf 'Error: a systemd fprintd.service unit is required for direct library integration.\n' >&2
    exit 1
  fi
  if ! command -v udevadm >/dev/null 2>&1; then
    printf 'Error: udevadm is required to apply the device access rule.\n' >&2
    exit 1
  fi
fi

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/focaltech-fprintd-stage.XXXXXX")"
DESTDIR="$STAGE_DIR" meson install -C "$BUILD_DIR"

if (( ! INSTALL_SYSTEM )); then
  printf 'Staged libfprint install at %s (no system changes made).\n' "$STAGE_DIR"
  printf 'Review it; to install, rerun this script with --install-system (it will create a fresh stage).\n'
  exit 0
fi

if [[ ! -d "$STAGE_DIR$INSTALL_ROOT" ]]; then
  printf 'Error: expected staged files under %s%s.\n' "$STAGE_DIR" "$INSTALL_ROOT" >&2
  exit 1
fi

if (( UPDATE_EXISTING )); then
  if [[ ! -d "$INSTALL_ROOT" ]]; then
    printf 'Error: --update-existing requested, but no existing install directory was found at %s.\n' \
      "$INSTALL_ROOT" >&2
    exit 1
  fi

  if ! diff -u \
      <(cd "$STAGE_DIR$INSTALL_ROOT" && find . -mindepth 1 -printf '%y %P\n' | LC_ALL=C sort) \
      <(cd "$INSTALL_ROOT" && find . -mindepth 1 -printf '%y %P\n' | LC_ALL=C sort); then
    printf 'Error: existing install layout does not match the staged project package; refusing update.\n' >&2
    exit 1
  fi

  while IFS= read -r -d '' staged_path; do
    relative_path="${staged_path#"$STAGE_DIR$INSTALL_ROOT/"}"
    destination="$INSTALL_ROOT/$relative_path"

    if [[ -L "$staged_path" ]]; then
      if [[ ! -L "$destination" ]] || [[ "$(readlink -- "$staged_path")" != "$(readlink -- "$destination")" ]]; then
        printf 'Error: existing symlink differs from the staged project install: %s\n' \
          "$destination" >&2
        exit 1
      fi
    elif [[ "$relative_path" != lib/libfprint-2.so && \
            "$relative_path" != lib/libfprint-2.so.2.0.0 && \
            "$relative_path" != lib/libfprint-2.so.2 ]]; then
      if [[ ! -f "$destination" ]] || ! cmp -s -- "$staged_path" "$destination"; then
        printf 'Error: existing file differs from the staged project install: %s\n' \
          "$destination" >&2
        exit 1
      fi
    fi
  done < <(find "$STAGE_DIR$INSTALL_ROOT" \( -type f -o -type l \) -print0)
else
  while IFS= read -r -d '' staged_path; do
    relative_path="${staged_path#"$STAGE_DIR$INSTALL_ROOT/"}"
    destination="$INSTALL_ROOT/$relative_path"
    if [[ -e "$destination" || -L "$destination" ]]; then
      printf 'Error: refusing to overwrite existing path: %s\n' "$destination" >&2
      printf 'If this is the existing project install, review it and rerun with --update-existing.\n' >&2
      exit 1
    fi
  done < <(find "$STAGE_DIR$INSTALL_ROOT" \( -type f -o -type l \) -print0)
fi

for config_pair in \
  "$UDEV_RULE_SOURCE:$UDEV_RULE_DEST" \
  "$SYSTEMD_DROPIN_SOURCE:$SYSTEMD_DROPIN_DEST"; do
  config_source="${config_pair%%:*}"
  config_destination="${config_pair#*:}"
  if [[ -e "$config_destination" || -L "$config_destination" ]]; then
    if (( ! UPDATE_EXISTING )); then
      printf 'Error: refusing to overwrite existing integration file: %s\n' \
        "$config_destination" >&2
      printf 'If this is the existing project integration, rerun with --update-existing.\n' >&2
      exit 1
    fi
    if [[ ! -f "$config_destination" ]] || ! cmp -s -- "$config_source" "$config_destination"; then
      printf 'Error: existing integration file differs from the project version: %s\n' \
        "$config_destination" >&2
      exit 1
    fi
  fi
done

if [[ ! -e "$STAGE_DIR$INSTALL_ROOT/lib/libfprint-2.so.2" ]]; then
  printf 'Error: staged library not found at %s%s/lib/libfprint-2.so.2.\n' \
    "$STAGE_DIR" "$INSTALL_ROOT" >&2
  printf 'Rebuild with scripts/setup-linux.sh; it configures Meson with --libdir=lib.\n' >&2
  exit 1
fi

if (( UPDATE_EXISTING )); then
  sudo cp -a "$STAGE_DIR$INSTALL_ROOT/." "$INSTALL_ROOT/"
else
  sudo cp -a -n "$STAGE_DIR$INSTALL_ROOT/." "$INSTALL_ROOT/"
fi
sudo install -D -m 0644 "$UDEV_RULE_SOURCE" "$UDEV_RULE_DEST"
sudo install -D -m 0644 "$SYSTEMD_DROPIN_SOURCE" "$SYSTEMD_DROPIN_DEST"

sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb \
  --attr-match=idVendor=2808 --attr-match=idProduct=6658
if systemctl is-active --quiet fprintd.service; then
  sudo systemctl restart fprintd.service
fi

printf 'Installed custom libfprint under %s. Run scripts/test-fprintd.sh to check detection.\n' \
  "$INSTALL_ROOT"
printf 'Staged manifest/source files remain at %s for review and later removal.\n' "$STAGE_DIR"
