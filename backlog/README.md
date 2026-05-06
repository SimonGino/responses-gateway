# Backlog System

This directory hosts the project's adaptation backlog **before** the GitHub repo exists. Each file in `issues/` is a self-contained, GitHub-ready issue body.

## File convention

- `issues/NNNN-slug.md` — one issue per file
- **First line:** `# Title` — used as the GitHub issue title on migration
- **Metadata block:** `**Type:** ...` / `**Priority:** ...` / `**Status:** ...` / `**Labels:** ...`
- **Body sections:** Context / Trigger / Acceptance / References

## Migrating to GitHub

Once you've created the GitHub repo and authenticated `gh`:

```bash
# From repo root
./backlog/migrate-to-github.sh
```

The script reads each `issues/NNNN-*.md`, extracts the title (first line) and labels (from the `**Labels:**` line, which uses backtick-quoted label names), and runs `gh issue create`.

You'll likely want to **create the labels first** (one-time):

```bash
# Sample label set — adjust to taste
gh label create "type/gap"          --color "d73a4a"
gh label create "type/verification" --color "0075ca"
gh label create "type/feature"      --color "0e8a16"
gh label create "type/bug"          --color "ee0701"
gh label create "type/decision"     --color "5319e7"
gh label create "priority/P0"       --color "b60205"
gh label create "priority/P1"       --color "d93f0b"
gh label create "priority/P2"       --color "fbca04"
gh label create "priority/P3"       --color "c2e0c6"
gh label create "area/tools"        --color "1d76db"
gh label create "area/protocol"     --color "1d76db"
gh label create "area/state"        --color "1d76db"
gh label create "area/streaming"    --color "1d76db"
gh label create "area/output"       --color "1d76db"
gh label create "area/multimodal"   --color "1d76db"
gh label create "area/billing"      --color "1d76db"
gh label create "area/reasoning"    --color "1d76db"
gh label create "area/mcp"          --color "1d76db"
gh label create "area/providers"    --color "1d76db"
gh label create "scope/emulation"   --color "5319e7"
gh label create "scope/passthrough" --color "5319e7"
gh label create "scope/rejection"   --color "5319e7"
gh label create "scope/runtime"     --color "5319e7"
gh label create "scope/architecture" --color "5319e7"
gh label create "scope/research"    --color "5319e7"
gh label create "scope/blocked"     --color "ededed"
```

## Adding new issues

1. Pick the next `NNNN` (highest existing + 1)
2. Copy from a similar file as template
3. Update `BACKLOG.md` table at repo root
4. (Post-migration) `gh issue create -F backlog/issues/NNNN-foo.md --title "..."`
