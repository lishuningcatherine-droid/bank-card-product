#!/usr/bin/env bash
# Back up the local docker database (the current source of truth) to backups/ — custom format, with a checksum.
# Read-only on the source. Never touches docker volumes. Prints no connection string.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p backups
out="backups/bankrec-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U bankrec -d bankrec --format=custom --no-owner --no-privileges > "$out"
shasum -a 256 "$out" > "$out.sha256"
echo "backup written: $out ($(du -h "$out" | cut -f1)); checksum in $out.sha256"
echo "row counts at backup time:"
uv run --frozen bankrec db check-target | sed -n '/"rows"/,/}/p'
