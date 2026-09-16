"""WebSub signature verification and feed parsing.

Signature verification is the app's only real security boundary, so it gets the
most attention here.
"""

from __future__ import annotations

import hashlib
import hmac

from kleos.websub import parse_feed, topic_for, verify_signature

SECRET = "test-secret"

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>yt:video:VIDEO_ONE</id>
    <yt:videoId>VIDEO_ONE</yt:videoId>
    <yt:channelId>UC_one</yt:channelId>
    <title>Team A 3-1 Team B | Highlights</title>
    <published>2026-09-12T18:30:00+00:00</published>
  </entry>
</feed>"""

DELETION = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:at="http://purl.org/atompub/tombstones/1.0"
      xmlns="http://www.w3.org/2005/Atom">
  <at:deleted-entry ref="yt:video:VIDEO_ONE" when="2026-09-12T19:00:00+00:00"/>
</feed>"""


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()


def test_accepts_a_correctly_signed_body():
    assert verify_signature(SECRET, FEED, _sign(FEED)) is True


def test_rejects_a_body_signed_with_the_wrong_secret():
    assert verify_signature(SECRET, FEED, _sign(FEED, "attacker-secret")) is False


def test_rejects_a_tampered_body():
    signature = _sign(FEED)
    assert verify_signature(SECRET, FEED + b"<!-- changed -->", signature) is False


def test_rejects_a_missing_signature_header():
    assert verify_signature(SECRET, FEED, None) is False


def test_rejects_a_malformed_signature_header():
    assert verify_signature(SECRET, FEED, "not-a-signature") is False


def test_rejects_an_unknown_digest_algorithm():
    assert verify_signature(SECRET, FEED, "rot13=abcdef") is False


def test_supports_sha256_signatures():
    signature = "sha256=" + hmac.new(SECRET.encode(), FEED, hashlib.sha256).hexdigest()
    assert verify_signature(SECRET, FEED, signature) is True


def test_parses_a_video_entry():
    refs = parse_feed(FEED)
    assert len(refs) == 1
    assert refs[0].video_id == "VIDEO_ONE"
    assert refs[0].channel_id == "UC_one"
    assert refs[0].title == "Team A 3-1 Team B | Highlights"
    assert refs[0].watch_url == "https://www.youtube.com/watch?v=VIDEO_ONE"


def test_returns_empty_for_a_deletion_notice():
    assert parse_feed(DELETION) == ()


def test_returns_empty_for_unparseable_xml():
    assert parse_feed(b"this is not xml") == ()


def test_topic_url_includes_the_channel_id():
    assert topic_for("UC_one").endswith("channel_id=UC_one")
