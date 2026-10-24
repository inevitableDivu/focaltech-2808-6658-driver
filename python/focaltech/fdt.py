"""Helpers for interpreting FocalTech FW9366 finger-detection values."""

FDT_TOUCH_THRESHOLD = 50
FDT_READY_STATUS = 0x50

# Observed as the uniform value across all eight channels in false-touch logs.
# Treat it as a per-value invalid marker, not an upper bound for valid deltas.
FDT_INVALID_SENTINEL = 0x03FF


def is_finger_touch(values, status, threshold=FDT_TOUCH_THRESHOLD):
    """Return whether a ready FDT sample contains a plausible touch delta.

    A known successful hardware sample reported status 0x50 and varied
    16-bit deltas around 3000. The later false-touch sample reported status
    0x04 with eight identical 1028 (0x0404) values. Require the empirically
    observed ready status plus at least two distinct, non-sentinel channels;
    this rejects flat/unready data without imposing a 10-bit ceiling.
    The status gate is based on observed behavior, not vendor-confirmed docs.
    """
    if int(status) != FDT_READY_STATUS:
        return False

    sample = [int(value) for value in values]
    valid_values = [
        value for value in sample if value != FDT_INVALID_SENTINEL
    ]
    if len(valid_values) < 2:
        return False

    return max(valid_values) > threshold and min(valid_values) < max(valid_values)
