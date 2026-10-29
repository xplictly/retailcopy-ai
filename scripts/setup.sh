#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
printf 'Checking macOS toolchain...\n'
command -v git >/dev/null || { echo 'Git is required.'; exit 1; }
node --version
npm --version
python3 --version
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
cd "$ROOT"
if [[ ! -f .env ]]; then cp .env.example .env; fi
mkdir -p backend/data
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then npm install --legacy-peer-deps; fi
cd "$ROOT/backend"
.venv/bin/python -m pytest -q
printf '\nSetup complete. Launch with:\n  scripts/start-backend.sh\n  scripts/start-frontend.sh\n'
