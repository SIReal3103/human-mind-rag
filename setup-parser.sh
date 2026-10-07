#!/bin/sh
# One-time local setup. Downloads public model weights, never uploads documents.
# uv provides Python 3.12, required by this pinned parser environment.
set -eu
BOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
    echo 'Install uv (https://docs.astral.sh/uv/getting-started/installation/), then rerun.' >&2
    exit 2
fi
if [ ! -x "$BOT_DIR/.venv-docling/bin/python" ]; then
    uv venv --python 3.12 "$BOT_DIR/.venv-docling"
fi
uv pip install --torch-backend cpu --python "$BOT_DIR/.venv-docling/bin/python" -r "$BOT_DIR/requirements-parser.lock.txt"
exec "$BOT_DIR/.venv-docling/bin/python" "$BOT_DIR/docling_worker.py" --download-models
