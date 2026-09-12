#!/bin/bash
# Restart the backend and wait until the NEW process is the one answering.
#
# Without the wait, /api/health answers from the process being shut down — it holds the port until its
# event stream drains — so a config change looks like it did not take effect when it did. That has been
# mistaken for a bug more than once.
set -u
PORT="${PORT:-8787}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PORCHLIGHT_PYTHON:-python3}"
LOG="${PORCHLIGHT_LOG:-/tmp/porchlight-backend.log}"

echo "stopping anything on :$PORT"
pkill -f "uvicorn app.main" 2>/dev/null
for i in $(seq 1 30); do
  pgrep -f "uvicorn app.main" >/dev/null || break
  [ "$i" -eq 15 ] && pkill -9 -f "uvicorn app.main" 2>/dev/null
  sleep 0.5
done
pgrep -f "uvicorn app.main" >/dev/null && { echo "!! could not stop the old process"; exit 1; }

cd "$HERE" || exit 1
nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
NEW=$!
echo "started pid $NEW; waiting for it to answer"

for i in $(seq 1 60); do
  got=$(curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null) || { sleep 1; continue; }
  # Only trust the answer once the old process is gone and ours is alive.
  # Only the new process counts. /api/health reports the pid that answered, so compare it against the
  # one just started rather than guessing from process counts.
  answered=$(echo "$got" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("pid",""))' 2>/dev/null)
  if [ -n "$answered" ] && [ "$answered" = "$NEW" ]; then
    echo "$got" | "$PY" -c 'import json,sys; h=json.load(sys.stdin); print("  models:", h["models"]); print("  send_mode:", h["send_mode"]); print("  public base:", h["public_base_url"])'
    exit 0
  fi
  sleep 1
done
echo "!! backend did not come up cleanly; see $LOG"
exit 1
