# Moving the database to Neon (prepared, not switched)

Status (2026-11-11): **prepared and rehearsed locally; nothing is switched.** The local docker database (volume
`pgdata`) stays the source of truth and is never modified by these steps. The daily schedule stays off
(`BANKREC_SCHEDULER` unset) until the cloud database has passed every check below.

## What was verified locally

| Check | Result |
|---|---|
| Server version | local 16.15; create the Neon project with **PostgreSQL 16** |
| Extensions | only `plpgsql` (built in) — nothing Neon must provide |
| Roles / grants | the backup is taken with `--no-owner --no-privileges`, so Neon's own role owns everything; the read-only API role is created separately (step 7) |
| Backup → restore → verify | rehearsed on a scratch local database: same migration revision (0017), same row counts in all main tables, `db upgrade` a no-op, a repeated `offers sync` made 0 changes |
| Locks | scheduled runs take an advisory lock per tier. On a **direct** connection it is a session lock; on a **pooled** one (PgBouncer in transaction mode, Neon's `-pooler` host, or `BANKREC_DB_POOLED=1`) it is a transaction-level lock in a transaction held open for the run (tested). The workflow and the restore script refuse a `-pooler` address anyway: use the direct one. |
| Secrets | scripts read addresses only from environment variables and never print them; `bankrec db check-target` reports endpoint kind, revision and row counts without the address (tested); the workflow masks the URL |

Scripts: `deploy/neon/backup-local.sh`, `deploy/neon/restore-to-target.sh`, `deploy/neon/verify-target.sh`.
Backups go to `backups/` (git-ignored; they contain real data — keep them off shared drives).

## Steps that need you

Do them in order; stop at the first failure (rollback below).

1. **Create the Neon project** (console.neon.tech): PostgreSQL **16**, a US East region (close to GitHub's runners).
   Neon creates a default branch with a database and an owner role.
2. **Create a test branch** from the default branch, e.g. `migration-test`. In *Connect*, turn **off** connection
   pooling and copy the **direct** connection string (its host has no `-pooler`). Keep `sslmode=require` in it.
3. **Back up, restore into the test branch, verify** — in your own terminal, so the address never reaches a log:
   ```sh
   deploy/neon/backup-local.sh
   read -rs TARGET_DATABASE_URL && export TARGET_DATABASE_URL     # paste the test branch's direct string; not echoed
   deploy/neon/restore-to-target.sh backups/<the new file>.dump
   deploy/neon/verify-target.sh                                    # must end with "target verified"
   unset TARGET_DATABASE_URL
   ```
4. **Test GitHub against the test branch** (the schedule stays off):
   ```sh
   gh secret set DATABASE_URL_TEST            # paste the test branch's direct string, written as postgresql+psycopg://…
   gh secret set BANKREC_CONTACT_EMAIL        # an address you choose for bank sites to contact the crawler operator
   gh workflow run scheduled-ingest.yml -f database=test
   gh run watch                               # must succeed; the log shows "database target: test" and row counts
   ```
   Then re-run `ALLOW_GROWTH=1 deploy/neon/verify-target.sh` against the test branch: counts may only have grown
   (new checks/versions), and the repeated sync must still report 0 changes.
5. **Production branch:** repeat step 3 with the **default** branch's direct string (from a fresh backup), then
   `gh secret set DATABASE_URL` with that string, and run `gh workflow run scheduled-ingest.yml -f database=production`
   once while watching it.
6. **Point the site at Neon** (only when you decide): set `DATABASE_URL` (and `API_DATABASE_URL`, step 7) in the
   environment the API runs in, then redeploy. Until then the site keeps reading the local database.
7. **Read-only API role (recommended):** in the Neon console create role `bankrec_api`, then as the owner run
   `deploy/db/roles.sql` with `psql -v api_password=… -f deploy/db/roles.sql` (password from your password manager);
   use it for `API_DATABASE_URL`.
8. **Switch the schedule on — last:** `gh variable set BANKREC_SCHEDULER --body github`. The daily run (06:15 UTC)
   then writes to the `DATABASE_URL` database.

Never paste a connection string into an issue, PR, commit, chat or report. The repository is **public**: workflow
logs and artifacts are visible to others (secrets are masked; the scripts print no address).

## Rollback

| Situation | What to do |
|---|---|
| Restore or verify fails on the test branch | Delete or reset the test branch in the Neon console (it is a disposable copy) and try again. Nothing else changed. |
| A GitHub test run misbehaves | Nothing to undo locally; reset the test branch to its parent in the console, or delete it. |
| Problems after step 5/6 | Point `DATABASE_URL` back to the local database and redeploy; the local volume was never touched. Neon can also restore the branch to an earlier point in time (see Neon's documentation for your plan's history window), or restore the last `backups/*.dump` into a new branch. |
| The schedule must stop | `gh variable delete BANKREC_SCHEDULER` — scheduled runs are skipped from the next trigger on. |
| A secret leaked | Reset the role's password in the Neon console (the old string stops working), then update the GitHub secret. |
