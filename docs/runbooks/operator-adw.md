# Operator ADW Runbook

This runbook is for explicit operator-only Oracle ADW actions. These commands
are not agent tools and must not be exposed through normal natural-language
execution.

## Environment Preflight

Set credentials and wallet details through environment variables only:

- `SQLCL_PATH`: absolute path to the SQLcl executable.
- `DB_WALLET_PATH`: existing wallet directory.
- `DB_DSN`: wallet TNS alias, not an EZCONNECT string.
- `ADMIN_USER` and `ADMIN_USER_PASS`: only for provisioning.
- `DB_USER` and `DB_USER_PASS`: working read-only user.

Do not print `.env`, wallet files, passwords, DSNs, rendered connect lines, or
SQLcl stdin. Use command output and audit events only after redaction.

## Provision Working User

Run provisioning only when the working user needs to be created or repaired:

```bash
bin/agent operator adw-provision-working-user \
  --grant-profile prototype-any-table-read \
  --confirm-live-adw-admin-provision \
  --audit-log /tmp/afs-adw-operator-audit.jsonl
```

Expected `provisioning_classification` values:

- `created`: the working user was absent before apply and compliant after
  apply.
- `already_compliant`: the working user already had the expected account
  status, grants, and SH private synonyms; DDL was skipped.
- `granted_missing_privileges`: the user existed and only expected profile
  grants or SH synonyms were missing; apply repaired them.
- `rejected_drift`: the user has privileges or synonym targets outside the
  selected profile. Stop and inspect manually; do not rerun blindly.

The current `prototype-any-table-read` profile grants `CREATE SESSION`,
`DWROLE`, and `SELECT ANY TABLE`, plus private synonyms for SH core tables. This
is prototype-only and must be reduced to object-level SH grants before
production use.

## Production-Grade Provisioning

Use the `production-sh-read` profile to replace the broad prototype grants with
object-level SELECT grants on the five core SH tables:

```bash
bin/agent operator adw-provision-working-user \
  --grant-profile production-sh-read \
  --confirm-live-adw-admin-provision \
  --audit-log /tmp/afs-adw-operator-audit.jsonl
```

The `production-sh-read` profile grants:
- `CREATE SESSION` (system privilege)
- `SELECT ON SH.CHANNELS`, `SELECT ON SH.CUSTOMERS`, `SELECT ON SH.PRODUCTS`,
  `SELECT ON SH.SALES`, `SELECT ON SH.TIMES` (object-level grants via `dba_tab_privs`)
- Private synonyms for the five SH tables (same as prototype)

**Drift detection**: if the working user already has `SELECT ANY TABLE` or
`DWROLE`, the command returns `rejected_drift` and stops without applying any
changes. Revoke those grants manually before running the production profile:

```sql
REVOKE SELECT ANY TABLE FROM AIAGENT;
REVOKE DWROLE FROM AIAGENT;
```

Verify object grants after provisioning:

```sql
SELECT privilege, owner, table_name
FROM dba_tab_privs
WHERE grantee = 'AIAGENT'
ORDER BY owner, table_name;
```

**Oracle ADW constraint**: the `ADMIN` account in Oracle Autonomous Database
does not hold `GRANT ANY OBJECT PRIVILEGE`, so `GRANT SELECT ON SH.* TO AIAGENT`
fails with `ORA-01031`. To apply `production-sh-read` in ADW you must either:

1. Connect as the `SH` schema owner and grant directly:
   ```sql
   GRANT SELECT ON SH.CHANNELS TO AIAGENT;
   GRANT SELECT ON SH.CUSTOMERS TO AIAGENT;
   GRANT SELECT ON SH.PRODUCTS  TO AIAGENT;
   GRANT SELECT ON SH.SALES     TO AIAGENT;
   GRANT SELECT ON SH.TIMES     TO AIAGENT;
   ```
2. Create ADMIN-owned views that select from SH tables and grant SELECT on
   those views — keeping AIAGENT away from the SH schema directly.

Until one of the above is applied, AIAGENT continues to use the broader
`prototype-any-table-read` grants (`SELECT ANY TABLE` + `DWROLE`).

## Smoke Check

After provisioning, run the fixed smoke query:

```bash
bin/agent operator adw-smoke \
  --confirm-live-adw-smoke \
  --audit-log /tmp/afs-adw-operator-audit.jsonl
```

The command runs only `select 1 as smoke_check from dual` as the working user.

## Reviewed Query

Put reviewed read-only SQL in a file and execute it explicitly:

```bash
bin/agent operator adw-query \
  --sql-file query.sql \
  --confirm-live-adw-query \
  --audit-log /tmp/afs-adw-operator-audit.jsonl
```

Durable audit records omit arbitrary result rows and raw SQL text. Prefer
`--sql-file` over inline SQL so the reviewed query is inspectable before
execution.

## Common Failures

- `ORA-01017`: wrong admin or working-user credentials, locked user, or stale
  password.
- Missing wallet: `DB_WALLET_PATH` does not point to the wallet directory.
- TNS alias failure: `DB_DSN` is not a wallet alias or `TNS_ADMIN` is wrong.
- Java or SQLcl failure: `SQLCL_PATH`, `PATH`, or `JAVA_HOME` is incomplete.
- Timeout or stream limit: increase only after reviewing the query and expected
  result size.
- `rejected_drift`: stop. Inspect roles, system privileges, synonyms, and
  account state manually before deciding whether to revoke or recreate.

## Rollback And Revoke

Rollback is an explicit admin decision, not an automatic agent action. Typical
manual actions are:

- revoke prototype broad grants such as `SELECT ANY TABLE` and `DWROLE`;
- drop private SH synonyms owned by the working user;
- lock the working user if access should pause;
- drop the working user only after confirming no operator workflow depends on
  it.

Record any manual rollback in the operator audit trail or project change log.
