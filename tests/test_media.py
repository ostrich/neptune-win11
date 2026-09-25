from pathlib import Path
import unittest
from unittest import mock

from neptune_win11 import media


class MediaTest(unittest.TestCase):
    def test_selects_windows_11_pro(self) -> None:
        listing = """Index: 1
Name: Windows 11 Home
Index: 6
Name: Windows 11 Pro
"""
        with mock.patch.object(media, "checked", return_value=listing):
            self.assertEqual(media.image_index(Path("install.wim")), 6)

    def test_reports_available_editions(self) -> None:
        listing = """Index: 1
Name: Windows 11 Home
"""
        with mock.patch.object(media, "checked", return_value=listing):
            with self.assertRaisesRegex(ValueError, "Windows 11 Home"):
                media.image_index(Path("install.wim"))

    def test_renders_well_formed_unattend_file(self) -> None:
        template = Path(__file__).parents[1] / "unattended"
        with mock.patch.object(media, "TEMPLATE_ROOT", template):
            rendered = media.render_unattend(6, media.DEFAULT_PASSWORD)
        self.assertNotIn("@@", rendered)
        self.assertIn("<Value>6</Value>", rendered)
        self.assertIn("<Value>password</Value>", rendered)


if __name__ == "__main__":
    unittest.main()
