#!/usr/bin/env bash
# One-command local demo bootstrap.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f content/source/dialogue_demo.mp4 ]]; then
  python scripts/generate_dialogue_demo.py
fi
if [[ ! -f content/hls/dialogue_demo/master.m3u8 ]]; then
  python scripts/package_hls.py --input content/source/dialogue_demo.mp4 --name dialogue_demo --max-height 720
fi
python -m captions.build --video dialogue_demo
python -m captions.eval_accuracy --video dialogue_demo

echo
echo "Demo ready."
echo "  Player:  http://127.0.0.1:8080"
echo "  Study:   http://127.0.0.1:8080/study"
echo
exec uvicorn server.main:app --host 127.0.0.1 --port 8080
