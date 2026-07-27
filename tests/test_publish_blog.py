import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_blog
from f1_get_result import RaceInfo, publish_manifest_entry


class PublishBlogTest(unittest.TestCase):
    def test_signed_request_covers_timestamp_and_exact_body(self) -> None:
        payload = {"year": 2026, "race_slug": "belgium", "markdown": "成绩"}
        request = publish_blog.signed_request(
            "http://blog.example/f1-publish.php",
            "a" * 32,
            payload,
            timestamp=1785168000,
        )

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(b"a" * 32, b"1785168000\n" + body, hashlib.sha256).hexdigest()

        self.assertEqual(request.data, body)
        self.assertEqual(request.get_header("X-f1-timestamp"), "1785168000")
        self.assertEqual(request.get_header("X-f1-signature"), f"sha256={expected}")

    def test_article_payload_uses_silverstone_override_and_keeps_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "translations.json").write_text(
                json.dumps({"races_zh": {"great-britain": "英国大奖赛"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "result.md").write_text("## 排位赛\n\n| 名次 |\n| ---: |\n| 1 |\n", encoding="utf-8")

            with patch.object(publish_blog, "BASE_DIR", root):
                payload = publish_blog.article_payload(
                    {
                        "year": 2026,
                        "race_slug": "great-britain",
                        "session_key": "qualifying",
                        "markdown_path": "result.md",
                    },
                    {"article_slug_overrides": {"2026:great-britain": "f1-2026-silver-stone"}},
                )

        self.assertEqual(payload["article_slug"], "f1-2026-silver-stone")
        self.assertEqual(payload["title"], "2026年英国大奖赛比赛结果")
        self.assertIn("## 排位赛", payload["markdown"])

    def test_manifest_entry_uses_repository_relative_output(self) -> None:
        race = RaceInfo(year=2026, race_id="1290", slug="belgium", name="Belgium", title="Belgium")
        output = Path(__file__).resolve().parents[1] / "generated" / "2026" / "Belgium" / "belgium-race.md"

        entry = publish_manifest_entry(race, "race", output)

        self.assertEqual(
            entry,
            {
                "year": 2026,
                "race_slug": "belgium",
                "session_key": "race",
                "markdown_path": "generated/2026/Belgium/belgium-race.md",
            },
        )


if __name__ == "__main__":
    unittest.main()

