"""Standalone check: can this X account upload video on its current tier?

This is the cheapest de-risking step in the whole project. X's free tier has
moved video upload and write caps between tiers repeatedly, and if video upload
is not available to you, the X third of this product does not exist - better to
learn that in two minutes than after building around it.

Uploads a short clip and, unless --post is passed, stops before tweeting.

    python scripts/check_x_video.py path/to/short.mp4
    python scripts/check_x_video.py path/to/short.mp4 --post
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from requests_oauthlib import OAuth1Session  # noqa: E402

from kleos.config import get_settings  # noqa: E402

UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_URL = "https://api.x.com/2/tweets"
CHUNK_BYTES = 4 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="short .mp4 to test with")
    parser.add_argument("--post", action="store_true", help="actually tweet it")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"No such file: {args.video}")
        return 2

    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("X_API_KEY", settings.x_api_key),
            ("X_API_SECRET", settings.x_api_secret),
            ("X_ACCESS_TOKEN", settings.x_access_token),
            ("X_ACCESS_TOKEN_SECRET", settings.x_access_token_secret),
        )
        if not value
    ]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
        return 2

    session = OAuth1Session(
        settings.x_api_key,
        client_secret=settings.x_api_secret,
        resource_owner_key=settings.x_access_token,
        resource_owner_secret=settings.x_access_token_secret,
    )

    total = args.video.stat().st_size
    print(f"File: {args.video.name} ({total / 1e6:.1f} MB)")

    print("INIT   ... ", end="", flush=True)
    init = session.post(
        UPLOAD_URL,
        data={
            "command": "INIT",
            "total_bytes": str(total),
            "media_type": "video/mp4",
            "media_category": "tweet_video",
        },
        timeout=60,
    )
    if init.status_code not in (200, 201, 202):
        print(f"FAILED {init.status_code}\n{init.text[:500]}")
        print("\n>>> Video upload is not available on this tier. Plan without X.")
        return 1
    media_id = init.json()["media_id_string"]
    print(f"ok (media_id {media_id})")

    with args.video.open("rb") as handle:
        index = 0
        while chunk := handle.read(CHUNK_BYTES):
            print(f"APPEND {index} ... ", end="", flush=True)
            append = session.post(
                UPLOAD_URL,
                data={"command": "APPEND", "media_id": media_id, "segment_index": str(index)},
                files={"media": chunk},
                timeout=180,
            )
            if append.status_code not in (200, 201, 204):
                print(f"FAILED {append.status_code}\n{append.text[:500]}")
                return 1
            print("ok")
            index += 1

    print("FINALIZE ... ", end="", flush=True)
    finalize = session.post(
        UPLOAD_URL, data={"command": "FINALIZE", "media_id": media_id}, timeout=60
    )
    if finalize.status_code not in (200, 201):
        print(f"FAILED {finalize.status_code}\n{finalize.text[:500]}")
        return 1
    print("ok")

    info = finalize.json().get("processing_info")
    while info and info.get("state") in ("pending", "in_progress"):
        delay = int(info.get("check_after_secs", 5))
        print(f"processing ({info['state']}), waiting {delay}s ...")
        time.sleep(delay)
        status = session.get(
            UPLOAD_URL, params={"command": "STATUS", "media_id": media_id}, timeout=60
        )
        info = status.json().get("processing_info")

    if info and info.get("state") == "failed":
        print(f"Processing FAILED: {info.get('error')}")
        return 1

    print("\n>>> Video upload WORKS on this tier.")

    if not args.post:
        print("Stopped before tweeting. Re-run with --post to publish.")
        return 0

    tweet = session.post(
        TWEET_URL,
        json={"text": "test", "media": {"media_ids": [media_id]}},
        timeout=60,
    )
    print(f"Tweet: {tweet.status_code} {tweet.text[:300]}")
    return 0 if tweet.status_code in (200, 201) else 1


if __name__ == "__main__":
    raise SystemExit(main())
