# Changelog

## v1.0.0

- First release: single file, zero dependency Bluesky CAR unpacker.
- Small self contained CBOR decoder in pure stdlib Python (major types
  0 to 7, maps, arrays, text, bytes, ints, tags including tag 42 CID
  links, simple values and floats).
- CAR framing: LEB128 varint block lengths, header with roots and
  version, CID plus CBOR value per later block.
- CLI: `bsky_unpack.py export.car --out-dir archive/` writes `index.md`
  (profile section, then posts in chronological order with reply and
  quote context) and `posts.json` (typed records with cid, createdAt,
  text, and did when present), plus a stats line on stdout.
- Flags: `--format md|json|both`, repeatable `--type` filtering,
  `--stats-only`, and `--check` for clean validation with a nonzero
  exit and a plain error message on corrupt input.
- Unknown record types are counted in stats but skipped in markdown.
- Malformed varints and CBOR fail with a clear error, not a traceback.
- 52 tests, all passing, covering CBOR types, varint framing, header
  parsing, CID handling, extraction, ordering, reply and quote context,
  filtering, stats, check pass and fail, and both output shapes.
- Synthetic example: `examples/build_example.py` generates
  `examples/sample.car`.
