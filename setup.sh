#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd "$(dirname "$0")" && pwd)"
upstream_commit=cb37446a00c6283cbb596df524885cfcb08a9fe7
upstream_dir="${SCOPE_BOT_PATH:-$app_dir/.runtime/scope-data-bot}"
venv_dir="${RAG_REVIEW_VENV:-$app_dir/.venv}"
python_bin="${PYTHON_BIN:-python3.12}"

if [ ! -d "$upstream_dir" ]; then
  mkdir -p "$(dirname "$upstream_dir")"
  git clone https://github.com/Qyroven/scope-data-bot.git "$upstream_dir"
  git -C "$upstream_dir" checkout --detach "$upstream_commit"
fi
if [ "$(git -C "$upstream_dir" rev-parse HEAD)" != "$upstream_commit" ]; then
  echo 'Upstream khác commit đã kiểm. Dùng clone riêng đúng commit hoặc đổi SCOPE_BOT_PATH.' >&2
  exit 1
fi
if [ ! -x "$venv_dir/bin/python" ]; then
  "$python_bin" -m venv "$venv_dir"
fi
"$venv_dir/bin/python" -m pip install -r "$app_dir/requirements.lock.txt"
# Tokenizer may download its public vocabulary once; document content is never sent.
"$venv_dir/bin/python" -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
echo 'Đã cài runtime. Chạy ./run.sh để mở API và giao diện trên 127.0.0.1:8765.'
