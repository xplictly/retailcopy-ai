#!/bin/zsh
set -e
cd "$(dirname "$0")/../backend"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
