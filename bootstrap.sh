#!/bin/sh
# Sourced by CLI wrappers: install a pinned lightweight runtime only when needed.
BOT_PYTHON="$BOT_DIR/.venv/bin/python"
if [ ! -x "$BOT_PYTHON" ]; then
    python3 -m venv "$BOT_DIR/.venv"
fi
if ! "$BOT_PYTHON" - "$BOT_DIR" <<'PY'
import hashlib
import importlib.metadata
from pathlib import Path
import sys
root = Path(sys.argv[1])
marker = root / '.venv/requirements.sha256'
expected = hashlib.sha256((root / 'requirements.lock.txt').read_bytes()).hexdigest()
try:
    assert marker.read_text() == expected
    for name, version in [('tiktoken','0.12.0'),('trafilatura','2.3.0'),('pypdf','6.19.0'),('lxml','6.1.3')]:
        assert importlib.metadata.version(name) == version
except (AssertionError, FileNotFoundError, importlib.metadata.PackageNotFoundError):
    raise SystemExit(1)
PY
then
    "$BOT_PYTHON" -m pip install -r "$BOT_DIR/requirements.lock.txt"
    "$BOT_PYTHON" - "$BOT_DIR" <<'PY'
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
(root / '.venv/requirements.sha256').write_text(hashlib.sha256((root / 'requirements.lock.txt').read_bytes()).hexdigest())
PY
fi
