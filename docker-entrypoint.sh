#!/bin/sh
# Container starts as root so we can fix the named-volume ownership (Docker
# creates volumes root-owned even when the image pre-chowned the mountpoint),
# then drops to uid 10001 / gid 10001 via setpriv before running the app.
set -e

chown appuser:appgroup /app/data 2>/dev/null || true

exec setpriv --reuid=10001 --regid=10001 --init-groups -- "$@"
