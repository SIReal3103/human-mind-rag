#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd "$(dirname "$0")" && pwd)"
python_bin="${RAG_REVIEW_PYTHON:-${RAG_REVIEW_VENV:-$app_dir/.venv}/bin/python}"
if [ -z "${SCOPE_BOT_PATH:-}" ] && [ -d "$app_dir/.runtime/scope-data-bot" ]; then
  export SCOPE_BOT_PATH="$app_dir/.runtime/scope-data-bot"
fi
if [ ! -x "$python_bin" ]; then
  echo 'Chưa có Python runtime. Chạy ./setup.sh hoặc đặt RAG_REVIEW_PYTHON.' >&2
  exit 1
fi
cd "$app_dir"
exec "$python_bin" -m uvicorn app:app --host 127.0.0.1 --port "${RAG_REVIEW_PORT:-8765}" --no-access-log
