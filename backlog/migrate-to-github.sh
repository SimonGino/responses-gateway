#!/usr/bin/env bash
# Migrate backlog/issues/*.md to GitHub issues.
# Requires: gh CLI authenticated to the target repo.
# Run from repo root: ./backlog/migrate-to-github.sh
set -euo pipefail

cd "$(dirname "$0")/issues"

for f in *.md; do
  # Title: first line, strip leading "# "
  title=$(head -1 "$f" | sed 's/^# //')

  # Labels: pull backtick-quoted words from the **Labels:** line
  labels=$(grep '^\*\*Labels:\*\*' "$f" | head -1 \
           | grep -oE '`[^`]+`' \
           | tr -d '`' \
           | tr '\n' ',' \
           | sed 's/,$//')

  # Body: everything except the first line (title)
  body=$(tail -n +2 "$f")

  echo "Creating issue: $title"
  if [ -n "$labels" ]; then
    gh issue create --title "$title" --body "$body" --label "$labels"
  else
    gh issue create --title "$title" --body "$body"
  fi
done

echo "Done. Verify with: gh issue list"
