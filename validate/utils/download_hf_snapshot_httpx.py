#!/usr/bin/env python3
"""Download a public Hugging Face dataset snapshot without relying on HEAD metadata."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from urllib.parse import quote

import httpx


def _token() -> str:
    explicit = os.environ.get("HF_TOKEN", "").strip()
    if explicit:
        return explicit
    cached = Path.home() / ".cache" / "huggingface" / "token"
    return cached.read_text(encoding="utf-8").strip() if cached.is_file() else ""


def _retry_request(call):
    for attempt in range(12):
        try:
            return call()
        except httpx.TransportError:
            if attempt == 11:
                raise
            time.sleep(min(2 ** attempt, 30))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id")
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"))
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    args.local_dir.mkdir(parents=True, exist_ok=True)
    verify = os.environ.get("SSL_NO_VERIFY") != "1"

    token = _token()
    auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or os.environ.get("ALL_PROXY")
    transport = httpx.HTTPTransport(retries=8, verify=verify, proxy=proxy)
    with httpx.Client(
        timeout=httpx.Timeout(60, read=300),
        follow_redirects=False,
        transport=transport,
    ) as client:
        response = _retry_request(
            lambda: client.get(
                f"{endpoint}/api/datasets/{args.repo_id}/tree/main",
                params={"recursive": "true", "expand": "true"},
                headers=auth_headers,
            )
        )
        while response.is_redirect:
            next_url = str(response.next_request.url)
            response = _retry_request(lambda: client.get(next_url, headers=auth_headers))
        response.raise_for_status()
        files = [
            item for item in response.json()
            if item.get("type") == "file" and item.get("path") != ".gitattributes"
        ]

        for index, item in enumerate(files, 1):
            relative = item["path"]
            expected = int(item.get("size") or 0)
            target = args.local_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            current = target.stat().st_size if target.exists() else 0
            if expected and current == expected:
                print(f"[{index}/{len(files)}] exists {relative}", flush=True)
                continue
            if current > expected > 0:
                target.unlink()
                current = 0

            headers = dict(auth_headers)
            if current:
                headers["Range"] = f"bytes={current}-"
            url = f"{endpoint}/datasets/{args.repo_id}/resolve/main/{quote(relative, safe='/')}"
            redirect = _retry_request(lambda: client.head(url, headers=headers))
            while redirect.is_redirect:
                url = str(redirect.next_request.url)
                redirect = _retry_request(lambda: client.head(url, headers=headers))
            if redirect.status_code >= 400:
                redirect.raise_for_status()
            with client.stream("GET", url, headers=headers) as download:
                download.raise_for_status()
                append = current > 0 and download.status_code == 206
                if current and not append:
                    current = 0
                mode = "ab" if append else "wb"
                print(f"[{index}/{len(files)}] download {relative} from {current}", flush=True)
                with target.open(mode) as handle:
                    for chunk in download.iter_bytes(1024 * 1024):
                        handle.write(chunk)

            actual = target.stat().st_size
            if expected and actual != expected:
                raise RuntimeError(f"size mismatch for {relative}: {actual} != {expected}")

    print(f"complete: {len(files)} files", flush=True)


if __name__ == "__main__":
    main()
