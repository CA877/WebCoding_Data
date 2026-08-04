import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from preprocess.pipeline_c.main import ResourceLocalizer


class AbsoluteSourceResourceTests(unittest.TestCase):
    def test_relative_source_resources_become_absolute_without_fetching(self) -> None:
        html = """
        <html><head>
          <link rel="stylesheet" href="../css/site.css">
          <script src="js/app.js"></script>
        </head><body>
          <img src="images/hero.jpg" srcset="images/small.jpg 1x, /images/large.jpg 2x">
          <div style="background-image: url('../images/bg.png')"></div>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            localizer = ResourceLocalizer(None, "https://example.test/pages/home/", Path(tmp))
            with patch.object(localizer, "_fetch") as fetch:
                rewritten = localizer.rewrite_html(html)

        fetch.assert_not_called()
        self.assertIn('href="https://example.test/pages/css/site.css"', rewritten)
        self.assertIn('src="https://example.test/pages/home/js/app.js"', rewritten)
        self.assertIn('src="https://example.test/pages/home/images/hero.jpg"', rewritten)
        self.assertIn("https://example.test/pages/home/images/small.jpg 1x", rewritten)
        self.assertIn("https://example.test/images/large.jpg 2x", rewritten)
        self.assertIn("https://example.test/pages/images/bg.png", rewritten)

    def test_existing_absolute_and_non_network_urls_are_unchanged(self) -> None:
        html = """
        <link rel="stylesheet" href="https://cdn.test/site.css">
        <script src="//cdn.test/app.js"></script>
        <img src="data:image/png;base64,AAAA">
        <div style="background:url(#paint)"></div>
        """
        with tempfile.TemporaryDirectory() as tmp:
            localizer = ResourceLocalizer(None, "https://example.test/page", Path(tmp))
            rewritten = localizer.rewrite_html(html)

        self.assertIn('href="https://cdn.test/site.css"', rewritten)
        self.assertIn('src="https://cdn.test/app.js"', rewritten)
        self.assertIn('src="data:image/png;base64,AAAA"', rewritten)
        self.assertIn("url(#paint)", rewritten)


if __name__ == "__main__":
    unittest.main()
