# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

This is a single-file Python CLI tool (`ipa_string_extractor.py`) that extracts readable strings from iOS `.ipa` files. It has zero pip dependencies — only Python 3.6+ standard library modules are used.

### Running the tool

```bash
python3 ipa_string_extractor.py <path_to_ipa> [-o output.txt] [-n min_length] [--extract-dir dir] [--no-cleanup]
```

See `README.md` for full usage examples.

### Linux environment caveats

- **`plutil` is macOS-only**: The plist conversion feature (`convert_plist_to_readable`) relies on `plutil`, which is not available on Linux. Plist string extraction will silently return empty results on Linux. The rest of the tool (binary string extraction via `strings`, localizable `.strings` file parsing, and text file reading) works normally.
- **`strings` command**: Available on Linux via `binutils` (pre-installed in most environments). Behavior is functionally equivalent to macOS `strings`.

### Linting

```bash
python3 -m py_compile ipa_string_extractor.py
flake8 ipa_string_extractor.py --max-line-length=120
```

Note: There is one pre-existing `E501` warning on line 123 (134 chars).

### Testing

No automated test suite exists. To test manually, create a mock `.ipa` file (a zip containing a `Payload/<AppName>.app/` directory with plist, `.strings`, binary, and text files) and run the extractor against it.
