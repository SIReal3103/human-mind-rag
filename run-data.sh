#!/bin/sh
# Scope -> source discovery -> crawl -> parse/check/save -> chunks -> embeddings -> LLM evidence package.
# ./run-data.sh --scope 'Phạm vi dữ liệu cần thu thập'
# ./run-data.sh --from-run bot-runs/<id>  # Resume a saved crawl, no repeated search.
set -eu
BOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$BOT_DIR/bootstrap.sh"
exec "$BOT_PYTHON" "$BOT_DIR/data_bot.py" "$@"
