#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def article_slug(year: int, race_slug: str, config: dict[str, Any]) -> str:
    race_key = f"{year}:{race_slug}"
    overrides = config.get("article_slug_overrides", {})
    return overrides.get(race_key, f"f1-{year}-{race_slug}")


def article_payload(session: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    year = int(session["year"])
    race_slug = str(session["race_slug"])
    markdown_path = BASE_DIR / str(session["markdown_path"])
    markdown = markdown_path.read_text(encoding="utf-8").strip()
    translations = read_json(BASE_DIR / "config" / "translations.json", {})
    race_name = translations.get("races_zh", {}).get(race_slug, race_slug.replace("-", " ").title() + "大奖赛")

    return {
        "year": year,
        "race_slug": race_slug,
        "article_slug": article_slug(year, race_slug, config),
        "session_key": str(session["session_key"]),
        "title": f"{year}年{race_name}比赛结果",
        "excerpt": f"持续更新{year}年{race_name}各场次官方成绩。",
        "tags": f"F1, 一级方程式, {race_name}",
        "markdown": markdown,
    }


def signed_request(url: str, secret: str, payload: dict[str, Any], timestamp: int | None = None) -> Request:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp_text = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(secret.encode("utf-8"), timestamp_text.encode("ascii") + b"\n" + body, hashlib.sha256).hexdigest()
    return Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "F1-get-result-blog-publisher/1.0",
            "X-F1-Timestamp": timestamp_text,
            "X-F1-Signature": f"sha256={signature}",
        },
    )


def publish(url: str, secret: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    request = signed_request(url, secret, payload)
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Blog returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach blog publisher: {exc}") from exc

    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"Blog rejected publish request: {result}")
    return result


def run(args: argparse.Namespace) -> int:
    manifest = read_json(Path(args.manifest), {"sessions": []})
    sessions = manifest.get("sessions", [])
    if not sessions:
        print("publish: no eligible sessions")
        return 0

    url = (args.url or os.environ.get("BLOG_PUBLISH_URL", "")).strip()
    secret = (args.secret or os.environ.get("BLOG_PUBLISH_SECRET", "")).strip()
    if not url or not secret:
        if args.skip_unconfigured:
            print("publish: BLOG_PUBLISH_URL or BLOG_PUBLISH_SECRET is not configured; skipping")
            return 0
        raise SystemExit("BLOG_PUBLISH_URL and BLOG_PUBLISH_SECRET are required.")
    if len(secret) < 32:
        raise SystemExit("BLOG_PUBLISH_SECRET must contain at least 32 characters.")

    config = read_json(BASE_DIR / "config" / "blog_publish.json", {})
    for session in sessions:
        payload = article_payload(session, config)
        result = publish(url, secret, payload, timeout=args.timeout)
        print(
            "publish: "
            f"{payload['year']}:{payload['race_slug']}:{payload['session_key']} "
            f"-> {result['status']} {result.get('post_url', '')}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish generated F1 Markdown to the blog.")
    parser.add_argument("--manifest", default=str(BASE_DIR / ".f1-publish-manifest.json"))
    parser.add_argument("--url", help="Blog publisher endpoint. Defaults to BLOG_PUBLISH_URL.")
    parser.add_argument("--secret", help="Signing secret. Defaults to BLOG_PUBLISH_SECRET.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-unconfigured", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

