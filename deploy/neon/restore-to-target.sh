#!/usr/bin/env bash
# Restore a backup into a TARGET database, normally a Neon *test branch* (never the branch the site will use until
# that branch has passed verify-target.sh). The target comes only from the environment and is never printed:
#   TARGET_DATABASE_URL='postgresql://…/…?sslmode=require' deploy/neon/restore-to-target.sh backups/<file>.dump
# Use Neon's DIRECT (unpooled) connection string: its host has no "-pooler". Local rehearsal: set
# ALLOW_LOCAL_TARGET=1 and point TARGET_DATABASE_URL at a scratch database in the local container.
set -euo pipefail
set +x  # never trace: the URL holds a password
cd "$(dirname "$0")/../.."
dump="${1:?usage: restore-to-target.sh backups/<file>.dump}"
: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL in the environment (never on the command line of a shared shell)}"
shasum -a 256 -c "$dump.sha256" >/dev/null || { echo "checksum mismatch for $dump" >&2; exit 1; }
target="${TARGET_DATABASE_URL/+psycopg/}"
host="$(python3 -c 'import sys,urllib.parse as u; print(u.urlsplit(sys.argv[1]).hostname or "")' "$target")"
case "$host" in
  *-pooler.*) echo "refused: this is Neon's pooled endpoint; use the direct (unpooled) connection string" >&2; exit 1 ;;
  *.neon.tech) kind=neon ;;
  localhost|127.0.0.1|db) [ "${ALLOW_LOCAL_TARGET:-}" = 1 ] || { echo "refused: local target needs ALLOW_LOCAL_TARGET=1" >&2; exit 1; }; kind=local ;;
  *) echo "refused: unexpected target host kind (expected a Neon branch)" >&2; exit 1 ;;
esac
echo "restoring $(basename "$dump") into the $kind target (connection string not shown)…"
# pg_restore runs in a postgres:16 client container; the URL is passed as an environment variable, not an argument
if [ "$kind" = local ]; then
  docker compose exec -T -e TARGET="$target" db sh -c 'pg_restore --dbname="$TARGET" --no-owner --no-privileges --exit-on-error' < "$dump"
else
  docker run --rm -i -e TARGET="$target" postgres:16 sh -c 'pg_restore --dbname="$TARGET" --no-owner --no-privileges --exit-on-error' < "$dump"
fi
echo "restore finished; now run deploy/neon/verify-target.sh"
