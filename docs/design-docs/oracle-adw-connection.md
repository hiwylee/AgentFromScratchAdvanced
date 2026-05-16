# Oracle ADW Connection Design

## Target

Oracle Autonomous Data Warehouse is the first supported database target.

The runtime should support two credential roles:

- `ADMIN_USER` / `ADMIN_USER_PASS`: privileged setup and metadata operations.
- `DB_USER` / `DB_USER_PASS`: normal read-only working account for agent tasks.

The working account should be preferred for natural-language query execution.
Admin credentials should be used only for explicit setup, grants, or metadata
tasks that the working account cannot perform.

## Environment Variables

Runtime configuration comes from `.env` in local development and process
environment variables in deployed usage:

- `SQLCL_PATH`: absolute path to the SQLcl executable.
- `ADMIN_USER`: Oracle ADW admin username.
- `ADMIN_USER_PASS`: Oracle ADW admin password.
- `DB_USER`: Oracle ADW working username.
- `DB_USER_PASS`: Oracle ADW working-user password.
- `DB_DSN`: ADW service name or connect descriptor.
- `DB_WALLET_PATH`: local wallet directory.
- `DB_WALLET_FILE`: local wallet archive or file path.
- `DB_WALLET_PASS`: wallet password if required.

Current local SQLcl path:

```text
/home/opc/.local/share/sqlcl/sqlcl/bin/sql
```

The convenience wrapper is also available at:

```text
/home/opc/.local/bin/sqlcl
```

## Secret Handling Rules

- Never print passwords, API keys, wallet passwords, or full secret-bearing
  connection strings.
- Do not commit `.env`, wallet files, or generated connection artifacts.
- Redact sensitive environment variables in logs and test failures.
- Pass passwords through environment variables or SQLcl-supported secure
  mechanisms; do not interpolate them into visible command strings.
- Store query text and non-sensitive metadata for auditability, but do not store
  credentials in agent state.

## First Connector Behavior

The first Oracle ADW connector should:

1. load configuration from environment variables;
2. verify SQLcl exists and can report a version;
3. verify wallet paths exist without printing wallet contents;
4. connect as the working user for read-only queries;
5. connect as admin only for explicit administrative workflows;
6. enforce read-only query policy for natural-language tasks.

## Milestone 4 Foundation Skeleton

`agent_runtime/oracle_adw.py` now defines the pre-connection foundation for
Oracle ADW support. It deliberately does not connect to a real database yet.
The skeleton provides:

- `OracleAdwConfig.from_env(...)` for environment-based configuration loading.
  Status helpers expose booleans and redacted dictionaries instead of printing
  passwords, wallet passwords, or full DSNs.
- `verify_sqlcl(...)` for SQLcl path resolution and version checks. The version
  runner is injectable so tests can use fixtures instead of a real SQLcl
  installation.
- `verify_wallet_paths(...)` for existence and file-type checks on wallet
  directories or files. The check uses path metadata only and never reads wallet
  contents.
- `validate_read_only_sql(...)` and `require_read_only_sql(...)` as the first
  application-level SQL policy layer.
- schema introspection query constants for tables, columns, and comments using
  Oracle data dictionary views available to the working user.

The real execution method on `OracleAdwReadOnlyConnector` remains closed with
`NotImplementedError`. This is intentional until SQLcl invocation, audit
recording, result limits, timeout behavior, and credential passing are designed
and tested.

## Read-Only SQL Policy

Natural-language database tasks must pass the read-only policy before any
future execution backend can run them. The current policy allows a single
`SELECT` or `WITH` statement and blocks:

- DML and DDL/admin keywords such as `INSERT`, `UPDATE`, `DELETE`, `MERGE`,
  `CREATE`, `ALTER`, `DROP`, `GRANT`, and `REVOKE`.
- `SELECT ... FOR UPDATE`.
- PL/SQL blocks and SQLcl slash block execution.
- database links using `@`.
- unsafe multi-statement input.
- resource-heavy optimizer hints such as `PARALLEL`, `FULL`, `USE_HASH`,
  `MATERIALIZE`, and `GATHER_PLAN_STATISTICS`.

This policy is a second layer behind database least privilege. The ADW working
user must still be read-only because string validation is not a complete SQL
sandbox.
