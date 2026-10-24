"""Helpers for interpreting FocalTech FW9366 finger-detection values."""

FDT_TOUCH_THRESHOLD = 50

# Observed as the uniform value across all eight channels in false-touch logs.
# Treat it as a per-value invalid marker, not an upper bound for valid deltas.
FDT_INVALID_SENTINEL = 0x03FF


def is_finger_touch(values, threshold=FDT_TOUCH_THRESHOLD):
    """Return whether an FDT sample contains a usable touch delta.

    Valid 16-bit deltas may exceed 0x03FF; the first successful hardware
    sample contained values around 3000. Exclude only the exact sentinel
    observed during false-touch reports. Empty, all-zero, and all-sentinel
    samples do not indicate a touch.
    """
    valid_values = (
        int(value) for value in values if int(value) != FDT_INVALID_SENTINEL
    )
    return any(value > threshold for value in valid_values)
