#!/usr/bin/env bash
set -euo pipefail

ENROLL=0
VERIFY=0
TARGET_USER="${USER:-}"

usage() {
  cat <<'EOF'
Usage: scripts/test-fprintd.sh [--user USER] [--enroll | --verify]

Default behavior is read-only: report relevant commands and list enrolled
fingerprints through fprintd. Enrollment/verification are never started unless
explicitly requested.

Options:
  --user USER   User account to query (default: current user)
  --enroll      Start interactive fingerprint enrollment
  --verify      Start interactive verification (requires an existing enrollment)
  -h, --help    Show this help
EOF
}

while (($#)); do
  case "$1" in
    --user)
      (($# >= 2)) || { printf 'Error: --user requires a username.\n' >&2; exit 2; }
      TARGET_USER="$2"
      shift
      ;;
    --enroll) ENROLL=1 ;;
    --verify) VERIFY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if (( ENROLL && VERIFY )); then
  printf 'Error: choose either --enroll or --verify, not both.\n' >&2
  exit 2
fi
if [[ -z "$TARGET_USER" ]]; then
  printf 'Error: could not determine the target user; pass --user USER.\n' >&2
  exit 2
fi
if ! command -v fprintd-list >/dev/null 2>&1; then
  printf 'Error: fprintd-list is not installed. Run scripts/setup-linux.sh first.\n' >&2
  exit 1
fi

printf 'User: %s\n' "$TARGET_USER"
if command -v lsusb >/dev/null 2>&1; then
  printf "\nUSB devices matching the driver's registered ID (2808:6658):\n"
  lsusb -d 2808:6658 || true
else
  printf '\nInstall usbutils (lsusb) to inspect attached USB hardware.\n'
fi

printf '\nEnrolled fingerprints reported by fprintd:\n'
if fprintd-list "$TARGET_USER"; then
  :
else
  list_status=$?
  printf 'Warning: fprintd-list failed (status %s); inspect daemon/device access before interpreting the test.\n' \
    "$list_status" >&2
  if (( ! ENROLL && ! VERIFY )); then
    exit "$list_status"
  fi
fi

if (( ENROLL )); then
  command -v fprintd-enroll >/dev/null 2>&1 || {
    printf 'Error: fprintd-enroll is not installed.\n' >&2
    exit 1
  }
  printf '\nStarting interactive enrollment. The daemon stores biometric data locally.\n'
  fprintd-enroll "$TARGET_USER"
elif (( VERIFY )); then
  command -v fprintd-verify >/dev/null 2>&1 || {
    printf 'Error: fprintd-verify is not installed.\n' >&2
    exit 1
  }
  printf '\nStarting interactive verification. Touch the sensor only when prompted.\n'
  fprintd-verify "$TARGET_USER"
else
  printf '\nRead-only check complete. To test enrollment, explicitly run with --enroll.\n'
fi
