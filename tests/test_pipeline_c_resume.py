import tempfile
import unittest
from pathlib import Path

from preprocess.pipeline_c.main import completed_source_urls


class PipelineCResumeTests(unittest.TestCase):
    def test_reads_valid_rows_and_ignores_partial_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.jsonl"
            manifest.write_text(
                '{"source_url":"https://a.test","status":"pass"}\n'
                '{"source_url":"https://b.test","status":"rejected"}\n'
                '{"source_url":"https://retry.test","status":"preflight_network_error","quality_status":"retryable"}\n'
                '{"source_url":', encoding="utf-8")
            self.assertEqual({"https://a.test", "https://b.test"}, completed_source_urls(manifest))


if __name__ == "__main__":
    unittest.main()
