#!/usr/bin/env bash
# Verify a restored target against the local source: same migration revision, same row counts, migrations are a
# no-op, and the offer tracker sync is idempotent there. Writes only to the target (sync records nothing new when
# idempotent). Prints no connection string.
#   TARGET_DATABASE_URL='postgresql+psycopg://…?sslmode=require' deploy/neon/verify-target.sh
# ALLOW_GROWTH=1 after runs on the target: counts may have grown, never shrunk.
set -euo pipefail
set +x
cd "$(dirname "$0")/../.."
: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL}"
url="$TARGET_DATABASE_URL"; case "$url" in postgresql+psycopg://*) ;; postgresql://*) url="postgresql+psycopg://${url#postgresql://}" ;; esac
src="$(uv run --frozen bankrec db check-target)"
tgt="$(DATABASE_URL="$url" uv run --frozen bankrec db check-target)"
echo "target:"; echo "$tgt"
python3 - "$src" "$tgt" <<'PY'
import json, sys
s, t = json.loads(sys.argv[1]), json.loads(sys.argv[2])
bad = [f"revision {s['alembic_revision']} != {t['alembic_revision']}"] if s["alembic_revision"] != t["alembic_revision"] else []
import os
grow = os.environ.get("ALLOW_GROWTH") == "1"  # after runs on the target: rows may only have been added
ok = (lambda a, b: b is not None and b >= a) if grow else (lambda a, b: a == b)
bad += [f"{k}: source {v}, target {t['rows'].get(k)}" for k, v in s["rows"].items() if not ok(v, t["rows"].get(k))]
bad += ["target is the pooled endpoint"] if t["endpoint"].startswith("pooled") else []
print(("row counts match" + (" or grew" if grow else "") + " and revision matches") if not bad else "MISMATCH:\n  " + "\n  ".join(bad))
sys.exit(1 if bad else 0)
PY
DATABASE_URL="$url" uv run --frozen bankrec db upgrade                      # must be a no-op ("migrated", same revision)
# the first sync may record date-driven status changes (e.g. a deadline passed since the backup); a second sync
# right after must change nothing
DATABASE_URL="$url" uv run --frozen bankrec offers sync >/dev/null
DATABASE_URL="$url" uv run --frozen bankrec offers sync | python3 -c 'import json,sys; d=json.load(sys.stdin); n=len(d["new_campaigns"])+len(d["new_versions"])+len(d["status_changes"]); print(f"repeated sync: {n} change(s)"); sys.exit(1 if n else 0)'
echo "target verified"
