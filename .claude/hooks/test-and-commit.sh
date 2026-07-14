#!/bin/bash
# Auto-test and commit hook: runs on PostToolUse Edit|Write for Python files.
# Exit 0 = success (or skipped). Exit 2 = test failure (rewakes model).

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=${CLAUDE_PROJECT_DIR:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}
cd "$REPO" || exit 0

# Only run for Python source files
FILE=$(jq -r '.tool_input.file_path // ""' 2>/dev/null)
echo "$FILE" | grep -qE '\.(py)$' || exit 0

echo "[hook] Python file changed: $FILE — running tests..."

# Run full test suite
if UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests -q 2>&1; then
  echo "[hook] Tests PASSED"
  git add -A
  if ! git diff --cached --quiet; then
    BRANCH=$(git branch --show-current)
    TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
    git commit -m "auto: tests passed ${TIMESTAMP}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    git push origin "$BRANCH"
    echo "[hook] Committed and pushed to $BRANCH"
  else
    echo "[hook] Tests passed — nothing new to commit"
  fi
  exit 0
else
  echo "[hook] Tests FAILED — changes not committed"
  exit 2
fi
