# Good first issues

Four small, self contained starting points. Each one states the file to
touch and what counts as done. No network or account access is needed
for any of them.

## 1. Add media alt text to the markdown output

File: `bsky_unpack.py`, function `_context_lines` and `build_markdown`.

Bluesky posts can carry image embeds (`app.bsky.embed.images`) with an
`alt` field per image. Today those embeds are ignored in `index.md`.

Acceptance criteria:

- A post with an images embed shows one line per image, in order, in
  the form `- Image: <alt text>` (or `- Image: (no alt text)` when alt
  is missing).
- Existing reply and quote lines are unchanged.
- At least one new test in `tests/test_bsky_unpack.py` covers an images
  embed with alt text and one without it.

## 2. Support `--since` and `--until` date filters

Files: `bsky_unpack.py` (argument parsing and record filtering),
`tests/test_bsky_unpack.py`, `README.md` (flags table).

Acceptance criteria:

- `--since 2026-01-01` keeps only records with `createdAt` on or after
  that date; `--until 2026-02-01` keeps only records before it.
- Records with no `createdAt` are kept by `--since` and `--until` unless
  a future issue says otherwise; document the choice in the README.
- `--stats-only` respects both filters.
- At least two new tests cover the boundary dates.

## 3. Print a readable record count table by month

Files: `bsky_unpack.py` (new function, used by `--stats-only`),
`tests/test_bsky_unpack.py`.

Acceptance criteria:

- `--stats-only` gains a `By month:` section listing post counts per
  `YYYY-MM` month, sorted chronologically, for example `2026-01: 12`.
- Undated records are listed once as `Undated: N` when any exist.
- The existing per type counts stay exactly as they are.
- At least one new test covers two months plus an undated record.

## 4. Add a `--format txt` plain text archive

Files: `bsky_unpack.py` (new `build_text` function and `--format`
choice), `tests/test_bsky_unpack.py`, `README.md` (flags table).

Acceptance criteria:

- `--format txt` writes `archive.txt` instead of `index.md`, with one
  post per block: date, a blank line, text, then reply or quote lines
  when present, in the same chronological order as the markdown.
- `--format both` still writes only `index.md` and `posts.json`; the
  txt format is opt in, not added to `both`.
- At least one new test checks the file name, the order, and the
  reply line in `archive.txt`.
