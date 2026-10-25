#!/usr/bin/env python3
"""Build examples/sample.car, a tiny synthetic Bluesky export.

This file duplicates a small CBOR encoder on purpose, so the example can
be regenerated without the test suite. The sample is synthetic: its CIDs
are made up, and its posts are placeholder text, not a real account export.

Run from the project root:

    python3 examples/build_example.py
    python3 bsky_unpack.py examples/sample.car --out-dir examples/archive
"""

import sys
from pathlib import Path


def enc_uint(major, value):
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")


def enc_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def enc(value):
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, int):
        return enc_uint(0, value) if value >= 0 else enc_uint(1, -1 - value)
    if isinstance(value, (bytes, bytearray)):
        return enc_uint(2, len(value)) + bytes(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return enc_uint(3, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        return enc_uint(4, len(value)) + b"".join(enc(v) for v in value)
    if isinstance(value, dict):
        out = enc_uint(5, len(value))
        for key, item in value.items():
            out += enc(key) + enc(item)
        return out
    raise TypeError("cannot encode %r" % (value,))


class Link:
    """A tag 42 CID link, built from made up CID bytes."""

    def __init__(self, seed):
        self.cid_bytes = bytes([1, 0x71, 0x12, 4]) + bytes([seed]) * 4

    def enc(self):
        return b"\xd8\x2a" + enc(b"\x00" + self.cid_bytes)


def link(value):
    if isinstance(value, Link):
        return value.enc()
    return enc(value)


def enc_record(record):
    """Encode a record, encoding Link values as tag 42 links."""
    out = enc_uint(5, len(record))
    for key, item in record.items():
        out += enc(key)
        out += link(item) if isinstance(item, Link) else enc_nested(item)
    return out


def enc_nested(value):
    if isinstance(value, dict):
        out = enc_uint(5, len(value))
        for key, item in value.items():
            out += enc(key)
            out += link(item) if isinstance(item, Link) else enc_nested(item)
        return out
    if isinstance(value, (list, tuple)):
        return enc_uint(4, len(value)) + b"".join(enc_nested(v) for v in value)
    return enc(value)


def block(cid_bytes, record):
    payload = cid_bytes + enc_record(record)
    return enc_varint(len(payload)) + payload


def main():
    here = Path(__file__).resolve().parent
    profile = Link(10)
    post_a = Link(11)
    post_b = Link(12)
    post_c = Link(13)
    header = {"roots": [profile], "version": 1}
    header_bytes = enc_uint(5, 2) + enc("roots") + enc_uint(4, 1) + profile.enc()
    header_bytes += enc("version") + enc(1)
    out = enc_varint(len(header_bytes)) + header_bytes
    out += block(profile.cid_bytes, {
        "$type": "app.bsky.actor.profile",
        "displayName": "Alex Sample",
        "description": "Sample profile for testing bsky-unpack.",
    })
    out += block(post_b.cid_bytes, {
        "$type": "app.bsky.feed.post",
        "text": "Second post, written later in the day.",
        "createdAt": "2026-10-20T18:30:00Z",
    })
    out += block(post_a.cid_bytes, {
        "$type": "app.bsky.feed.post",
        "text": "First post of the day, stored second in the file.",
        "createdAt": "2026-10-20T09:00:00Z",
    })
    out += block(post_c.cid_bytes, {
        "$type": "app.bsky.feed.post",
        "text": "Replying to the first post.",
        "createdAt": "2026-10-20T20:00:00Z",
        "reply": {"root": post_a, "parent": post_a},
    })
    out += block(Link(14).cid_bytes, {
        "$type": "app.bsky.feed.like",
        "createdAt": "2026-10-20T12:00:00Z",
    })
    target = here / "sample.car"
    target.write_bytes(out)
    try:
        shown = target.relative_to(Path.cwd())
    except ValueError:
        shown = target
    print("Wrote %s (%d bytes)" % (shown, len(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
