# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This repo (`xcode_obf`) contains a Python CLI tool (`ipa_string_extractor.py`) that extracts readable strings from iOS `.ipa` files. It is a standalone script with **no pip dependencies** — only Python 3.6+ standard library is used.

### Running the tool

```bash
python3 ipa_string_extractor.py <path-to-ipa> [-o output.txt]
```

See `python3 ipa_string_extractor.py --help` for all options.

### Linux-specific caveats

- **`strings` command**: Available on Linux via `binutils` (pre-installed). Works identically to macOS version.
- **`plutil` command**: macOS-only. Not available on Linux. The script handles this gracefully — plist extraction will return empty results, but the script will not crash. Localizable `.strings` files fall back to text-based parsing when `plutil` is unavailable.
- Plist-related extraction (Info.plist values) will be empty on Linux. All other extraction categories (binary strings, localizable strings, text files) work normally.

### Linting and type checking

```bash
flake8 ipa_string_extractor.py
mypy ipa_string_extractor.py
```

Both are installed via `pip3 install --user flake8 mypy`. The `~/.local/bin` directory must be on `PATH`.

### Testing

No automated test suite exists. To manually test, create a minimal `.ipa` (a zip with `Payload/AppName.app/` structure containing test files) and run the extractor against it.
