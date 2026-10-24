import unittest

from focaltech.fdt import (
    FDT_INVALID_SENTINEL,
    FDT_INVALID_ALL_ONES,
    FDT_READY_STATUS,
    is_finger_touch,
)


class FingerDetectionTests(unittest.TestCase):
    def test_known_working_hardware_sample_is_touch(self):
        values = [3098, 3061, 3048, 2952, 2972, 3188, 3158, 877]
        self.assertTrue(is_finger_touch(values, status=FDT_READY_STATUS))

    def test_uniform_0404_sample_with_unexpected_status_is_idle(self):
        self.assertFalse(is_finger_touch([1028] * 8, status=0x04))

    def test_uniform_high_sample_is_not_a_touch(self):
        self.assertFalse(is_finger_touch([1028] * 8, status=FDT_READY_STATUS))

    def test_all_ones_sample_is_idle(self):
        self.assertFalse(
            is_finger_touch([FDT_INVALID_ALL_ONES] * 8,
                            status=FDT_READY_STATUS)
        )

    def test_all_ones_values_do_not_dominate_a_mixed_sample(self):
        values = [1023, 1023, 1023, 1023,
                  FDT_INVALID_ALL_ONES, FDT_INVALID_ALL_ONES,
                  FDT_INVALID_ALL_ONES, FDT_INVALID_ALL_ONES]
        self.assertFalse(is_finger_touch(values, status=FDT_READY_STATUS))

    def test_unready_status_rejects_large_deltas(self):
        values = [3098, 3061, 3048, 2952, 2972, 3188, 3158, 877]
        self.assertFalse(is_finger_touch(values, status=0x04))

    def test_zero_sample_is_idle(self):
        self.assertFalse(is_finger_touch([0] * 8, status=FDT_READY_STATUS))

    def test_uniform_sentinel_sample_is_idle(self):
        self.assertFalse(
            is_finger_touch(
                [FDT_INVALID_SENTINEL] * 8, status=FDT_READY_STATUS
            )
        )

    def test_high_values_are_not_rejected_by_10_bit_ceiling(self):
        values = [3098, 3061, 3048, 2952, 2972, 3188, 3158, 877]
        self.assertTrue(is_finger_touch(values, status=FDT_READY_STATUS))

    def test_single_high_outlier_is_not_a_touch(self):
        self.assertFalse(
            is_finger_touch([3098] + [0] * 7, status=FDT_READY_STATUS)
        )

    def test_equal_above_threshold_values_are_not_a_touch(self):
        self.assertFalse(
            is_finger_touch([1028, 1028] + [0] * 6,
                            status=FDT_READY_STATUS)
        )

    def test_sentinel_channels_do_not_trigger_touch(self):
        self.assertFalse(
            is_finger_touch([FDT_INVALID_SENTINEL] * 7 + [20],
                            status=FDT_READY_STATUS)
        )

    def test_one_remaining_channel_is_not_enough(self):
        self.assertFalse(
            is_finger_touch([FDT_INVALID_SENTINEL] * 7 + [877],
                            status=FDT_READY_STATUS)
        )

    def test_mixed_sentinel_and_varied_high_values_are_allowed(self):
        values = [FDT_INVALID_SENTINEL, 3061, 3048, 2952,
                  2972, 3188, 3158, 877]
        self.assertTrue(is_finger_touch(values, status=FDT_READY_STATUS))

    def test_threshold_is_strict(self):
        self.assertFalse(
            is_finger_touch([50, 51] + [0] * 6, status=FDT_READY_STATUS)
        )
        self.assertTrue(
            is_finger_touch([50, 51, 52] + [0] * 5, status=FDT_READY_STATUS)
        )

    def test_empty_sample_is_idle(self):
        self.assertFalse(is_finger_touch([], status=FDT_READY_STATUS))


if __name__ == "__main__":
    unittest.main()
