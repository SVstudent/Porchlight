#!/bin/bash
# Post-merge verification: run every deterministic test and build the frontend.
set -u
REPO="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# Python to run the suite with: the repo venv if present, else whatever `python3` is.
VENV="${VENV:-$REPO/backend/.venv/bin/python}"
[ -x "$VENV" ] || VENV="$(command -v python3)"
fail=0
echo "=== conflict marker check ==="
if grep -rn "^<<<<<<< \|^>>>>>>> " --include="*.py" --include="*.js" --include="*.jsx" --include="*.css" \
        --include="*.md" --include="*.json" --include=".env.example" "$REPO/backend" "$REPO/frontend/src" "$REPO/docs" 2>/dev/null | grep -v node_modules; then
  echo "!! conflict markers committed"; fail=1
else
  echo "  none"
fi
cd "$REPO/backend" || exit 1
echo "=== python import check ==="
$VENV -c "import app.main, agentcore_app; print('imports ok')" || fail=1
for t in $(ls tests/test_*.py 2>/dev/null | sed 's#tests/##; s#\.py##'); do
  echo "=== tests.$t ==="
  out=$($VENV -m "tests.$t" 2>&1 | grep -v "\[console\]" | tail -3)
  echo "$out"
  echo "$out" | grep -qi "PASSED" || { echo "!! $t did not report PASSED"; fail=1; }
done
echo "=== frontend build ==="
cd "$REPO/frontend" || exit 1
[ -d node_modules ] || npm ci --silent || npm install --silent
npm run build 2>&1 | tail -4 | grep -E "built in|error" || fail=1
echo "=== RESULT: $([ $fail -eq 0 ] && echo ALL GREEN || echo FAILURES) ==="
exit $fail
