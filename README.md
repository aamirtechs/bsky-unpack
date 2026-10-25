# bsky-unpack

Turn a Bluesky account export (`.car` file) into a readable local archive.
Bluesky exports are opaque CAR blobs; this gives you your own posts back
as plain markdown and JSON, with no account, network, or upload involved.

## Install

There is nothing to install. It is one file, `bsky_unpack.py`, with zero
dependencies, and it runs on Python 3.9 and later:

```sh
python3 bsky_unpack.py export.car --out-dir archive/
```

Copy that single file anywhere and run it. The input file is only read,
never modified, and nothing is written into the input file's directory
unless `--out-dir` points there.

## Quick example

The repo includes a script that builds a tiny synthetic export so you can try it without your
real data. Generate it, then unpack it. This output was captured from a
real run:

```sh
python3 examples/build_example.py
python3 bsky_unpack.py examples/sample.car --out-dir archive/
```

```
Wrote examples/sample.car (589 bytes)
Wrote 3 post(s), 1 profile(s), 5 record(s) to archive (index.md, posts.json)
```

`archive/index.md` from that run:

```md
# Bluesky archive

## Profile

- Display name: Alex Sample
- Description: Sample profile for testing bsky-unpack.

## Posts

### 2026-10-20T09:00:00Z

First post of the day, stored second in the file.

### 2026-10-20T18:30:00Z

Second post, written later in the day.

### 2026-10-20T20:00:00Z

Replying to the first post.

- Reply to: bafyrebalbmfqw
```

`archive/posts.json` from that run (first record shown in full; the file
holds all five records, including the like, in chronological order):

```json
[
  {
    "type": "app.bsky.feed.post",
    "cid": "bafyrebalbmfqw",
    "createdAt": "2026-10-20T09:00:00Z",
    "text": "First post of the day, stored second in the file."
  }
]
```

Counts only, and a validity check, from the same sample:

```sh
python3 bsky_unpack.py examples/sample.car --stats-only
python3 bsky_unpack.py examples/sample.car --check
```

```
Total blocks: 6
Records: 5
Other blocks: 0
app.bsky.actor.profile: 1
app.bsky.feed.like: 1
app.bsky.feed.post: 3
OK: valid CAR with 6 block(s), 5 record(s).
```

## Flags

| Flag | What it does |
| --- | --- |
| `export.car` (positional) | The Bluesky export file to read. |
| `--out-dir DIR` | Directory to write into. Default: `archive`. |
| `--format md\|json\|both` | Write only markdown, only JSON, or both. Default: `both`. |
| `--type TYPE` | Only include this record type, for example `app.bsky.feed.post`. Repeatable. |
| `--since YYYY-MM-DD` | Keep records on or after this UTC date. |
| `--until YYYY-MM-DD` | Keep records before this UTC date. |
| `--stats-only` | Print counts per record type and write nothing. |
| `--check` | Validate that the CAR parses cleanly. Exit 0 on success, nonzero with a plain error message on corrupt input. |

Date filters apply to records with a parseable `createdAt` timestamp. Records
without a valid `createdAt` remain in the output. The `--since` boundary is
inclusive and the `--until` boundary is exclusive; both dates are interpreted
as midnight UTC.

Output files, when written:

- `index.md`: profile section if a profile record is present, then
  posts in chronological order with date, text, and reply or quote
  context where the record carries it. Unknown record types are counted
  in stats but skipped here.
- `posts.json`: machine readable list of extracted records, each with
  `type`, `cid`, `createdAt`, `text`, and `did` when the record carries
  one. Records are in chronological order, undated records last.

## CAR format notes

A CAR file is a sequence of length prefixed blocks. Each block starts
with an unsigned LEB128 varint giving the block byte length. The first
block is the header: a CBOR map with `roots` and `version`. Every later
block holds a CID (version, codec, multihash code, digest length,
digest, all varints except the digest itself) followed by one CBOR value.

The CBOR decoder in `bsky_unpack.py` is small and self contained. It
covers major types 0 to 7: unsigned and negative integers, byte and text
strings (including indefinite length chunks), arrays, maps, tags
(including tag 42, which becomes a CID link), simple values, and half,
single, and double precision floats.

## Limitations

- Local only: no network, no auth, no fetching of linked posts. A reply
  or quote is shown as the CID it points to, not as the linked post's
  text, because the export alone does not carry that text.
- Only records in the export are shown. Threads, follows, blocks, and
  other record types are counted in stats but not rendered as posts.
- Media is not downloaded or embedded. Image alt text is not yet shown
  in markdown (see `GOOD_FIRST_ISSUES.md`).
- CID strings are the base32 multibase form of the raw CID bytes.
  They are stable identifiers for the records in your export, not
  shortened links.
- Very large exports are read fully into memory. That keeps the code
  simple, and it is the main scaling limit to fix first.

## Tests

`pytest` is not required. The suite uses the standard library only:

```sh
python3 -m unittest discover -s tests
```

56 tests, all passing, covering CBOR decoding of each major type,
varint framing, header parsing, CID handling, post extraction and
chronological ordering, reply and quote context, `--type` filtering,
`--stats-only` counts and date filtering, `--check` pass and fail on corrupt
input, JSON output shape, and markdown output content. The CBOR encoder in the
test file exists only to build synthetic fixtures.

## License

MIT, Copyright 2026 Amir Hussain. See `LICENSE`.
