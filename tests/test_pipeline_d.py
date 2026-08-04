import json
import tempfile
import unittest
from pathlib import Path

from preprocess.pipeline_d.main import completed_pass_count, completed_source_urls, project_id


class PipelineDTests(unittest.TestCase):
    def test_project_id_is_stable(self) -> None:
        self.assertEqual(project_id("https://example.test"), project_id("https://example.test"))

    def test_resume_retries_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.jsonl"
            rows = [
                {"source_url": "https://ok.test", "status": "pass", "quality_status": "unfiltered", "code_tokens": 123},
                {"source_url": "https://retry.test", "status": "crawl_failed", "quality_status": "retryable"},
            ]
            manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual({"https://ok.test"}, completed_source_urls(manifest))
            self.assertEqual(1, completed_pass_count(manifest))


if __name__ == "__main__":
    unittest.main()
