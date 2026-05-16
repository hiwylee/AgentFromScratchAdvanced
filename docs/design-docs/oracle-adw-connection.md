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
