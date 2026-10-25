"""Tests for bsky_unpack. The encoder here is test only: it builds
synthetic CBOR and CAR fixtures so the real decoder can be exercised."""

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bsky_unpack import (  # noqa: E402
    CIDLink, CarError, Tagged, build_markdown, compute_stats, decode_cbor,
    encode_varint, extract_records, main, parse_car, parse_cid,
    read_varint, sort_records,
)

SRC = Path(__file__).resolve().parents[1] / "bsky_unpack.py"
POST = "app.bsky.feed.post"
PROFILE = "app.bsky.actor.profile"


# --- Minimal CBOR encoder, test fixtures only -----------------------------

def enc_uint(major, value):
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    if value < 4294967296:
        return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")
    return bytes([(major << 5) | 27]) + value.to_bytes(8, "big")


def enc(value):
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, CIDLink):
        return b"\xd8\x2a" + enc(b"\x00" + value.cid_bytes)
    if isinstance(value, Tagged):
        return enc_uint(6, value.tag) + enc(value.value)
    if isinstance(value, int):
        if value >= 0:
            return enc_uint(0, value)
        return enc_uint(1, -1 - value)
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
    if isinstance(value, float):
        return b"\xfb" + struct.pack(">d", value)
    raise TypeError("cannot encode %r" % (value,))


def make_cid(seed):
    body = bytes([1, 0x71, 0x12, 4]) + bytes([seed]) * 4
    return CIDLink(body)


def block_bytes(cid, value):
    payload = cid.cid_bytes + enc(value)
    return encode_varint(len(payload)) + payload


def make_car(records):
    """records: list of (cid, value). Header roots point at the first cid."""
    roots = [records[0][0]] if records else []
    header = {"roots": roots, "version": 1}
    out = encode_varint(len(enc(header))) + enc(header)
    for cid, value in records:
        out += block_bytes(cid, value)
    return out


def post_record(text, created, extra=None):
    record = {"$type": POST, "text": text, "createdAt": created}
    if extra:
        record.update(extra)
    return record


def run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SRC)] + args,
        capture_output=True, text=True, cwd=cwd,
    )


class CborDecodeTests(unittest.TestCase):
    def test_unsigned_ints(self):
        self.assertEqual(decode_cbor(enc(0)), 0)
        self.assertEqual(decode_cbor(enc(23)), 23)
        self.assertEqual(decode_cbor(enc(24)), 24)
        self.assertEqual(decode_cbor(enc(300)), 300)
        self.assertEqual(decode_cbor(enc(70000)), 70000)

    def test_negative_ints(self):
        self.assertEqual(decode_cbor(enc(-1)), -1)
        self.assertEqual(decode_cbor(enc(-100)), -100)
        self.assertEqual(decode_cbor(enc(-100000)), -100000)

    def test_bytes_and_text(self):
        self.assertEqual(decode_cbor(enc(b"\x01\x02")), b"\x01\x02")
        self.assertEqual(decode_cbor(enc("hello")), "hello")
        self.assertEqual(decode_cbor(enc("café")), "café")

    def test_arrays_and_maps(self):
        self.assertEqual(decode_cbor(enc([1, "two", None])), [1, "two", None])
        self.assertEqual(decode_cbor(enc({"a": 1, "b": [2, 3]})),
                         {"a": 1, "b": [2, 3]})

    def test_nested_map(self):
        value = {"outer": {"inner": [1, {"x": "y"}]}}
        self.assertEqual(decode_cbor(enc(value)), value)

    def test_booleans_and_null(self):
        self.assertIs(decode_cbor(enc(True)), True)
        self.assertIs(decode_cbor(enc(False)), False)
        self.assertIsNone(decode_cbor(enc(None)))

    def test_floats(self):
        self.assertAlmostEqual(decode_cbor(enc(3.25)), 3.25)
        self.assertAlmostEqual(decode_cbor(b"\xfb" + struct.pack(">d", 0.5)), 0.5)

    def test_half_and_single_floats(self):
        self.assertAlmostEqual(decode_cbor(b"\xf9\x3c\x00"), 1.0)
        self.assertAlmostEqual(decode_cbor(b"\xfa\x3f\x80\x00\x00"), 1.0)

    def test_tag_other_than_42(self):
        self.assertEqual(decode_cbor(enc(Tagged(1, 1234567890))),
                         Tagged(1, 1234567890))

    def test_tag_42_cid_link(self):
        cid = make_cid(7)
        self.assertEqual(decode_cbor(enc(cid)), cid)
        self.assertTrue(decode_cbor(enc(cid)).cid.startswith("b"))

    def test_indefinite_array(self):
        self.assertEqual(decode_cbor(b"\x9f\x01\x02\xff"), [1, 2])

    def test_indefinite_text(self):
        self.assertEqual(decode_cbor(b"\x7f\x62\x68\x69\xff"), "hi")

    def test_trailing_bytes_rejected(self):
        with self.assertRaises(CarError):
            decode_cbor(enc(1) + b"\x00")

    def test_truncated_cbor_rejected(self):
        with self.assertRaises(CarError):
            decode_cbor(b"\x62\x68")

    def test_invalid_utf8_rejected(self):
        with self.assertRaises(CarError):
            decode_cbor(b"\x61\xff")


class VarintAndCidTests(unittest.TestCase):
    def test_varint_round_trip(self):
        for value in (0, 1, 127, 128, 300, 16384, 100000):
            encoded = encode_varint(value)
            decoded, pos = read_varint(encoded, 0)
            self.assertEqual(decoded, value)
            self.assertEqual(pos, len(encoded))

    def test_varint_truncated(self):
        with self.assertRaises(CarError):
            read_varint(b"\x80", 0)

    def test_cid_parse(self):
        cid = make_cid(3)
        parsed, pos = parse_cid(cid.cid_bytes, 0)
        self.assertEqual(parsed, cid)
        self.assertEqual(pos, len(cid.cid_bytes))

    def test_cid_bad_version(self):
        with self.assertRaises(CarError):
            parse_cid(bytes([0, 0x71, 0x12, 1, 9]), 0)

    def test_cid_truncated_digest(self):
        with self.assertRaises(CarError):
            parse_cid(bytes([1, 0x71, 0x12, 9, 1]), 0)


class CarParsingTests(unittest.TestCase):
    def test_header_parsing(self):
        data = make_car([(make_cid(1), post_record("hi", "2026-01-01T00:00:00Z"))])
        header, blocks = parse_car(data)
        self.assertEqual(header["version"], 1)
        self.assertEqual(len(header["roots"]), 1)
        self.assertEqual(len(blocks), 1)

    def test_empty_file_rejected(self):
        with self.assertRaises(CarError):
            parse_car(b"")

    def test_block_length_overrun_rejected(self):
        data = encode_varint(99) + b"\x00" * 5
        with self.assertRaises(CarError):
            parse_car(data)

    def test_missing_header_rejected(self):
        payload = make_cid(1).cid_bytes + enc(post_record("x", "2026-01-01T00:00:00Z"))
        data = encode_varint(len(payload)) + payload
        with self.assertRaises(CarError):
            parse_car(data)

    def test_corrupt_cbor_in_block_rejected(self):
        header = {"roots": [], "version": 1}
        out = encode_varint(len(enc(header))) + enc(header)
        out += encode_varint(3) + make_cid(1).cid_bytes + b"\xff"
        with self.assertRaises(CarError):
            parse_car(out)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.cid1 = make_cid(1)
        self.cid2 = make_cid(2)
        self.cid3 = make_cid(3)
        records = [
            (self.cid1, post_record("second", "2026-01-02T00:00:00Z")),
            (self.cid2, post_record("first", "2026-01-01T00:00:00Z")),
            (self.cid3, {"$type": PROFILE, "displayName": "Chris",
                         "description": "Dispatcher"}),
        ]
        self.data = make_car(records)
        _, blocks = parse_car(self.data)
        self.records, self.other = extract_records(blocks)

    def test_records_extracted(self):
        self.assertEqual(len(self.records), 3)
        self.assertEqual(self.other, 0)

    def test_post_fields(self):
        post = self.records[0]
        self.assertEqual(post["type"], POST)
        self.assertEqual(post["text"], "second")
        self.assertEqual(post["createdAt"], "2026-01-02T00:00:00Z")
        self.assertTrue(post["cid"].startswith("b"))

    def test_chronological_ordering(self):
        ordered = sort_records([r for r in self.records if r["type"] == POST])
        self.assertEqual([r["text"] for r in ordered], ["first", "second"])

    def test_undated_last(self):
        records = [{"type": POST, "cid": "b1", "createdAt": None,
                    "text": "no date", "raw": {}},
                   {"type": POST, "cid": "b2",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "text": "dated", "raw": {}}]
        ordered = sort_records(records)
        self.assertEqual(ordered[0]["text"], "dated")

    def test_non_record_blocks_counted(self):
        _, blocks = parse_car(self.data)
        records, other = extract_records(blocks + [(make_cid(9), [1, 2])])
        self.assertEqual(other, 1)
        self.assertEqual(len(records), 3)

    def test_author_did_when_present(self):
        _, blocks = parse_car(make_car([
            (make_cid(5), post_record("hi", "2026-01-01T00:00:00Z",
                                       {"did": "did:plc:abc"}))]))
        records, _ = extract_records(blocks)
        self.assertEqual(records[0].get("did"), "did:plc:abc")

    def test_author_did_absent(self):
        self.assertNotIn("did", self.records[0])

    def test_reply_context_in_markdown(self):
        record = post_record("reply text", "2026-01-03T00:00:00Z",
                             {"reply": {"root": make_cid(8),
                                        "parent": make_cid(9)}})
        md = build_markdown([{"type": POST, "cid": "bx",
                              "createdAt": "2026-01-03T00:00:00Z",
                              "text": "reply text", "raw": record}])
        self.assertIn("Reply to:", md)
        self.assertIn("Thread root:", md)
        self.assertIn("reply text", md)

    def test_quote_context_in_markdown(self):
        record = post_record("quote text", "2026-01-03T00:00:00Z",
                             {"embed": {"$type": "app.bsky.embed.record",
                                        "record": make_cid(8)}})
        md = build_markdown([{"type": POST, "cid": "bx",
                              "createdAt": "2026-01-03T00:00:00Z",
                              "text": "quote text", "raw": record}])
        self.assertIn("Quote:", md)

    def test_profile_section_in_markdown(self):
        md = build_markdown(self.records)
        self.assertIn("## Profile", md)
        self.assertIn("Chris", md)
        self.assertIn("Dispatcher", md)

    def test_unknown_type_skipped_in_markdown(self):
        md = build_markdown(self.records + [{
            "type": "app.bsky.feed.like", "cid": "bx",
            "createdAt": "2026-01-01T00:00:00Z", "text": None,
            "raw": {"$type": "app.bsky.feed.like"}}])
        self.assertNotIn("app.bsky.feed.like", md)

    def test_markdown_posts_chronological(self):
        md = build_markdown(self.records)
        self.assertLess(md.index("first"), md.index("second"))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.car = self.dir / "export.car"
        self.car.write_bytes(make_car([
            (make_cid(1), post_record("second", "2026-01-02T00:00:00Z")),
            (make_cid(2), post_record("first", "2026-01-01T00:00:00Z")),
            (make_cid(3), {"$type": PROFILE, "displayName": "Chris",
                            "description": "Dispatcher"}),
            (make_cid(4), {"$type": "app.bsky.feed.like",
                           "createdAt": "2026-01-01T12:00:00Z"}),
        ]))
        self.out = self.dir / "archive"

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_run_writes_both(self):
        result = run_cli([str(self.car), "--out-dir", str(self.out)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "index.md").exists())
        self.assertTrue((self.out / "posts.json").exists())
        self.assertFalse((self.out / "archive.txt").exists())
        self.assertIn("Wrote 2 post(s)", result.stdout)

    def test_input_not_modified(self):
        before = self.car.read_bytes()
        run_cli([str(self.car), "--out-dir", str(self.out)])
        self.assertEqual(self.car.read_bytes(), before)

    def test_format_md_only(self):
        run_cli([str(self.car), "--out-dir", str(self.out), "--format", "md"])
        self.assertTrue((self.out / "index.md").exists())
        self.assertFalse((self.out / "posts.json").exists())

    def test_format_json_only(self):
        run_cli([str(self.car), "--out-dir", str(self.out), "--format", "json"])
        self.assertFalse((self.out / "index.md").exists())
        self.assertTrue((self.out / "posts.json").exists())

    def test_format_txt_only_and_chronological(self):
        reply = post_record(
            "reply text", "2026-01-03T00:00:00Z",
            {
                "reply": {"root": make_cid(1), "parent": make_cid(2)},
                "embed": {
                    "$type": "app.bsky.embed.record",
                    "record": make_cid(3),
                },
            },
        )
        self.car.write_bytes(make_car([
            (make_cid(4), post_record("second", "2026-01-02T00:00:00Z")),
            (make_cid(5), post_record("first", "2026-01-01T00:00:00Z")),
            (make_cid(6), reply),
        ]))

        result = run_cli([
            str(self.car), "--out-dir", str(self.out), "--format", "txt",
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "archive.txt").exists())
        self.assertFalse((self.out / "index.md").exists())
        self.assertFalse((self.out / "posts.json").exists())
        self.assertIn("archive.txt", result.stdout)
        self.assertEqual(
            (self.out / "archive.txt").read_text(),
            "2026-01-01T00:00:00Z\n\nfirst\n\n"
            "2026-01-02T00:00:00Z\n\nsecond\n\n"
            "2026-01-03T00:00:00Z\n\nreply text\n"
            "- Reply to: %s\n- Thread root: %s\n- Quote: %s\n"
            % (make_cid(2).cid, make_cid(1).cid, make_cid(3).cid),
        )

    def test_json_output_shape(self):
        run_cli([str(self.car), "--out-dir", str(self.out), "--format", "json"])
        payload = json.loads((self.out / "posts.json").read_text())
        self.assertEqual(len(payload), 4)
        first = payload[0]
        self.assertEqual(first["type"], POST)
        self.assertEqual(first["text"], "first")
        self.assertIn("cid", first)
        self.assertIn("createdAt", first)
        self.assertEqual([p["text"] for p in payload if p["type"] == POST],
                         ["first", "second"])

    def test_markdown_output_content(self):
        run_cli([str(self.car), "--out-dir", str(self.out), "--format", "md"])
        md = (self.out / "index.md").read_text()
        self.assertIn("# Bluesky archive", md)
        self.assertIn("Chris", md)
        self.assertIn("first", md)
        self.assertIn("2026-01-01T00:00:00Z", md)

    def test_type_filter(self):
        run_cli([str(self.car), "--out-dir", str(self.out),
                 "--type", POST, "--format", "json"])
        payload = json.loads((self.out / "posts.json").read_text())
        self.assertEqual(len(payload), 2)
        self.assertTrue(all(p["type"] == POST for p in payload))

    def test_type_filter_repeatable(self):
        run_cli([str(self.car), "--out-dir", str(self.out),
                 "--type", POST, "--type", PROFILE, "--format", "json"])
        payload = json.loads((self.out / "posts.json").read_text())
        self.assertEqual(len(payload), 3)

    def test_since_includes_boundary_and_keeps_undated_records(self):
        result = run_cli([str(self.car), "--out-dir", str(self.out),
                          "--since", "2026-01-02", "--format", "json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads((self.out / "posts.json").read_text())
        posts = [r["text"] for r in payload if r["type"] == POST]
        self.assertEqual(posts, ["second"])
        self.assertTrue(any(r["type"] == PROFILE for r in payload))

    def test_until_excludes_boundary_and_keeps_undated_records(self):
        result = run_cli([str(self.car), "--out-dir", str(self.out),
                          "--until", "2026-01-02", "--format", "json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads((self.out / "posts.json").read_text())
        posts = [r["text"] for r in payload if r["type"] == POST]
        self.assertEqual(posts, ["first"])
        self.assertTrue(any(r["type"] == PROFILE for r in payload))

    def test_stats_only_respects_both_date_filters(self):
        result = run_cli([str(self.car), "--stats-only", "--since",
                          "2026-01-02", "--until", "2026-01-03"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Records: 2", result.stdout)
        self.assertIn("app.bsky.feed.post: 1", result.stdout)
        self.assertIn("app.bsky.actor.profile: 1", result.stdout)
        self.assertNotIn("app.bsky.feed.like", result.stdout)

    def test_date_filter_requires_iso_date(self):
        result = run_cli([str(self.car), "--since", "2026-1-2"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("YYYY-MM-DD", result.stderr)

    def test_stats_only_writes_nothing(self):
        result = run_cli([str(self.car), "--stats-only"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.out.exists())
        self.assertIn("app.bsky.feed.post: 2", result.stdout)
        self.assertIn("app.bsky.actor.profile: 1", result.stdout)
        self.assertIn("app.bsky.feed.like: 1", result.stdout)

    def test_stats_only_with_filter(self):
        result = run_cli([str(self.car), "--stats-only", "--type", POST])
        self.assertIn("app.bsky.feed.post: 2", result.stdout)
        self.assertNotIn("app.bsky.feed.like", result.stdout)

    def test_check_pass(self):
        result = run_cli([str(self.car), "--check"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK: valid CAR", result.stdout)

    def test_check_fail_corrupt(self):
        bad = self.dir / "bad.car"
        bad.write_bytes(b"\x05\xff\xff\xff\xff\xff")
        result = run_cli([str(bad), "--check"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_check_fail_missing_file(self):
        result = run_cli([str(self.dir / "nope.car"), "--check"])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_corrupt_run_no_traceback(self):
        bad = self.dir / "bad.car"
        bad.write_bytes(make_car([(make_cid(1), post_record("x", "2026-01-01T00:00:00Z"))]) + b"\x80")
        result = run_cli([str(bad), "--out-dir", str(self.out)])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_stats_counts(self):
        _, blocks = parse_car(self.car.read_bytes())
        records, other = extract_records(blocks)
        stats = compute_stats({"roots": []}, blocks, records, other)
        self.assertEqual(stats["record_count"], 4)
        self.assertEqual(stats["by_type"][POST], 2)


if __name__ == "__main__":
    unittest.main()
