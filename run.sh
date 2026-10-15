#!/usr/bin/env bash
# Start Anzen-bot. Override any of these before running, e.g.
#   ROUTER_URL=http://127.0.0.1:11434/v1 DEFAULT_MODEL=llama3.1 ./run.sh
set -e
export ROUTER_URL="${ROUTER_URL:-http://127.0.0.1:11434/v1}"
export ROUTER_KEY="${ROUTER_KEY:-}"
export DEFAULT_MODEL="${DEFAULT_MODEL:-llama3.1}"
export PORT="${PORT:-8093}"
exec python3 "$(dirname "$0")/server.py"
