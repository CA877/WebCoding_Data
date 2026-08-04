import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from preprocess.pipeline_c.main import ResourceLocalizer


class RemoteFontFallbackTests(unittest.TestCase):
    def test_remote_css_keeps_link_and_adds_system_font_override_without_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            localizer = ResourceLocalizer(None, "https://site.test/page", Path(tmp))
            html = localizer.rewrite_html('<link rel="stylesheet" href="https://site.test/assets/site.css">')
            self.assertIn("https://site.test/assets/site.css", html)
            self.assertIn('data-remote-font-fallback="system-default"', html)
            self.assertIn("Arial,Helvetica,sans-serif", html)
            self.assertEqual(0, localizer.log.first_party_fonts_downloaded)

    def test_relative_css_font_is_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            localizer = ResourceLocalizer(None, "https://site.test/page", Path(tmp))
            css = b'@font-face{font-family:Icons;src:url("font/icons.woff2")} .x{color:red}'
            with patch.object(localizer, "_fetch", return_value=(css, "text/css")), \
                 patch.object(localizer, "_write_binary") as write_binary:
                localizer.localize_css("https://site.test/assets/site.css")
            write_binary.assert_not_called()
            self.assertEqual(1, localizer.log.font_files_skipped)


if __name__ == "__main__":
    unittest.main()
