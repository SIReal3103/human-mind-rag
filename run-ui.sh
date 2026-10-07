#!/bin/sh
# One repository: UI -> crawl/parse -> human approval -> index -> evidence API.
# ./run-ui.sh; open http://127.0.0.1:8765 and configure provider keys in Settings.
# Optional OCR setup: ./setup-parser.sh; DOCUMENT_PARSER=docling ./run-ui.sh
set -eu
BOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$BOT_DIR/bootstrap.sh"
if ! "$BOT_PYTHON" - "$BOT_DIR" <<'PY'
import hashlib
import importlib.metadata
from pathlib import Path
import sys
root = Path(sys.argv[1])
expected = hashlib.sha256((root / 'requirements-ui.lock.txt').read_bytes()).hexdigest()
try:
    assert (root / '.venv/ui-requirements.sha256').read_text() == expected
    for name, version in [('fastapi', '0.142.2'), ('uvicorn', '0.54.0'), ('python-multipart', '0.0.32'), ('certifi', '2026.7.22')]:
        assert importlib.metadata.version(name) == version
except (AssertionError, FileNotFoundError, importlib.metadata.PackageNotFoundError):
    raise SystemExit(1)
PY
then
    "$BOT_PYTHON" -m pip install -r "$BOT_DIR/requirements-ui.lock.txt"
    "$BOT_PYTHON" - "$BOT_DIR" <<'PY'
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
(root / '.venv/ui-requirements.sha256').write_text(hashlib.sha256((root / 'requirements-ui.lock.txt').read_bytes()).hexdigest())
PY
fi
# Prefer installed Docling; native mode keeps unreadable scans pending for OCR.
if [ -z "${DOCUMENT_PARSER:-}" ]; then
    DOCUMENT_PARSER=$("$BOT_PYTHON" - "$BOT_DIR" <<'PYCODE'
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from document_parser import runtime
print('docling' if runtime().is_file() else 'native')
PYCODE
)
    export DOCUMENT_PARSER
fi
cd "$BOT_DIR"
exec "$BOT_PYTHON" -m uvicorn app:app --app-dir "$BOT_DIR/review_ui" --host 127.0.0.1 --port "${RAG_REVIEW_PORT:-8765}" --no-access-log
