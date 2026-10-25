# Examples

`sample.car` is a tiny synthetic Bluesky export, built by
`build_example.py`. It is not a real account export: its CIDs are made up
and its posts are placeholder text. It exists so you can try the tool
without handing it your real export first.

It contains one profile, three posts (one is a reply, and the posts are
stored out of order in the file so you can see chronological sorting),
and one like, which is counted in stats but skipped in the markdown.

Regenerate it and unpack it:

```sh
python3 examples/build_example.py
python3 bsky_unpack.py examples/sample.car --out-dir archive/
```

See the main README for the real captured output of those commands.
