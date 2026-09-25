import unittest

from neptune_win11.vm import format_elapsed


class VmProgressTest(unittest.TestCase):
    def test_formats_elapsed_time(self) -> None:
        self.assertEqual(format_elapsed(0), "00:00:00")
        self.assertEqual(format_elapsed(65.9), "00:01:05")
        self.assertEqual(format_elapsed(7384), "02:03:04")

    def test_clamps_negative_elapsed_time(self) -> None:
        self.assertEqual(format_elapsed(-1), "00:00:00")


if __name__ == "__main__":
    unittest.main()
