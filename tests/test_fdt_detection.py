import unittest

from focaltech.fdt import FDT_INVALID_SENTINEL, is_finger_touch


class FingerDetectionTests(unittest.TestCase):
    def test_known_working_hardware_sample_is_touch(self):
        values = [3098, 3061, 3048, 2952, 2972, 3188, 3158, 877]
        self.assertTrue(is_finger_touch(values))

    def test_zero_sample_is_idle(self):
        self.assertFalse(is_finger_touch([0] * 8))

    def test_uniform_sentinel_sample_is_idle(self):
        self.assertFalse(is_finger_touch([FDT_INVALID_SENTINEL] * 8))

    def test_high_values_are_not_rejected_by_10_bit_ceiling(self):
        self.assertTrue(is_finger_touch([0, 0, 0, 0, 0, 0, 0, 3098]))

    def test_sentinel_channels_do_not_trigger_touch(self):
        self.assertFalse(is_finger_touch([FDT_INVALID_SENTINEL] * 7 + [20]))

    def test_valid_delta_survives_mixed_sentinel_values(self):
        self.assertTrue(is_finger_touch([FDT_INVALID_SENTINEL] * 7 + [877]))

    def test_threshold_is_strict(self):
        self.assertFalse(is_finger_touch([50] * 8))
        self.assertTrue(is_finger_touch([51] + [0] * 7))

    def test_empty_sample_is_idle(self):
        self.assertFalse(is_finger_touch([]))


if __name__ == "__main__":
    unittest.main()
