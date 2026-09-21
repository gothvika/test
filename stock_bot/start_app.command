#!/bin/bash
# Double-click this (or a Desktop alias to it) to start the Stock Bot web
# interface and open it in your browser automatically.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env file found in $(pwd) — the app needs your API keys there before it can start."
  echo "Press Enter to close this window."
  read -r _
  exit 1
fi

# Give the server a moment to start listening before opening the browser.
( sleep 2 && open "http://127.0.0.1:5000" ) &

echo "Starting Stock Bot at http://127.0.0.1:5000 — press Ctrl+C in this window to stop it."
python3 app.py
