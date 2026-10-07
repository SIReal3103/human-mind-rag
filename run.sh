#!/bin/sh
set -eu
BOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$BOT_DIR/bootstrap.sh"
exec "$BOT_PYTHON" "$BOT_DIR/bot.py" "$@"
