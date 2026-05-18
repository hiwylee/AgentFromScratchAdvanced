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

## Admin Provisioning Direction

`ADMIN_USER` is allowed to create and provision the normal working account, but
admin provisioning is a separate setup boundary from read-only query execution.
The read-only connector must never fall back to admin credentials.

The first implementation exposes both a dry-run admin-executable provisioning
plan and an operator-only SQLcl apply command. Admin apply is separate from
read-only query execution and requires explicit confirmation:

```bash
bin/agent operator adw-provision-working-user \
  --grant-profile prototype-any-table-read \
  --confirm-live-adw-admin-provision
```

Provisioning rules:

- validate `DB_USER` as a simple unquoted Oracle identifier;
- reject administrative, system, and sample-schema names for `DB_USER`;
- require `ADMIN_USER` and `ADMIN_USER_PASS` to be configured before generating
  an admin setup plan;
- require `DB_USER_PASS` but keep it out of generated/loggable statements;
- use a symbolic password placeholder in dry-run output;
- grant only `CREATE SESSION` and object-level `SELECT` on the selected sample
  schema tables;
- create private working-user synonyms for selected sample tables so natural
  language queries can avoid schema-qualified dotted references;
- do not create public synonyms or grant `DBA`, `RESOURCE`, `ANY` privileges,
  package execution, DDL, or write access.

The `prototype-any-table-read` grant profile is an explicit exception requested
for live prototype verification. It grants `CREATE SESSION`, `DWROLE`, and
`SELECT ANY TABLE`, and creates private synonyms for the SH core tables so
operator SQL can keep using unqualified table names while the parser-less SQL
policy continues to reject schema-qualified dotted references. This profile is
broader than the object-level plan above, must remain operator-only, and should
be reduced before production use.

Actual apply must be explicit, auditable, redacted, and idempotent. Re-running
setup reports one of `created`, `already_compliant`,
`granted_missing_privileges`, or `rejected_drift` rather than silently
broadening privileges.

Admin provisioning apply remains separate from the read-only SQLcl execution
boundary. It does not reuse the read-only execution helper because setup
requires different idempotency checks, compensation behavior, privilege
diffing, and approval records. The prototype command inspects admin metadata
before DDL. If the existing user already matches the selected profile, apply is
skipped. If the existing user has unexpected powerful roles, unexpected system
privileges, or SH private synonyms pointing to unexpected targets, the command
returns `rejected_drift` before unlocking or granting anything. Otherwise it
creates the missing user or repairs only the expected profile grants and
synonyms, then runs a postcheck through the same bounded SQLcl subprocess
stream-capture boundary as live read-only execution. Passwords that cannot be
safely rendered in the current admin setup block are rejected before SQLcl is
invoked.

Operator procedure details are in `docs/runbooks/operator-adw.md`.

## Sample Dataset Choice

Use `SH` first and `SSB` second.

`SH` is preferred for the first natural-language database analysis milestone
because its sales history schema has more business-friendly entities: sales,
products, customers, channels, and time. These map directly to prompts such as
product sales trends and metric/dimension ambiguity.

`SSB` remains useful later as a star-schema benchmark and stress dataset for
row limits, timeouts, and cost controls. The first SSB profile uses
`LINEORDER`, `CUSTOMER`, `SUPPLIER`, `PART`, and `DWDATE`.

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

## SQLcl Read-Only Execution Boundary

The first executable boundary is designed as a plan, not as a live database
call. `build_read_only_sqlcl_execution_plan(...)` validates the SQL policy and
constructs the exact future SQLcl subprocess shape, while
`OracleAdwReadOnlyConnector.execute_read_only_query(...)` still raises
`NotImplementedError`.

Planned invocation:

```text
sql -S -L -nolog
```

Credentials must not appear in command-line arguments. The working-user
connect command is sent through private stdin after SQLcl starts with
`-nolog`. The plan object's normal redacted representation replaces stdin with
`[REDACTED]`, and audit records store only metadata such as the SQL hash,
working username, timeout, row limit, and SQLcl argv.

The read-only plan uses only the working account:

- require `SQLCL_PATH`, `DB_USER`, `DB_USER_PASS`, and `DB_DSN`;
- validate `DB_USER` as a non-protected simple Oracle identifier;
- never fall back to `ADMIN_USER`;
- optionally set `TNS_ADMIN` from `DB_WALLET_PATH`;
- never place password, DSN, admin password, or wallet password in argv,
  result dictionaries, error dictionaries, or audit records.

Execution controls:

- timeout: default 30 seconds, configurable from 1 to 300 seconds;
- row limit: default 1000 rows, configurable from 1 to 10000 rows;
- stdout capture limit: default 1 MiB;
- stderr capture limit: default 64 KiB;
- SQL is wrapped as `SELECT * FROM (<validated query>) WHERE ROWNUM <= n` so
  the first backend-side limit exists before result parsing.

Output behavior:

- SQLcl is configured for JSON output;
- supported parser shapes are SQLcl-style `results[0].columns/items`, direct
  `items`, direct `rows`, or a list of row objects;
- parser failures return a structured `json_parse_failed` or
  `json_shape_not_supported` error;
- results over the configured row limit return `row_limit_exceeded`;
- any configured credential value observed in stdout-derived rows is redacted
  before the result dictionary is exposed.

Error behavior:

- non-zero SQLcl status returns `sqlcl_error` with a bounded, redacted stderr
  tail;
- timeout returns `timeout` and records the configured timeout value;
- oversized stdout or stderr returns `output_too_large` or
  `error_output_too_large`;
- all error dictionaries are redacted before audit or caller exposure.

Audit behavior:

- record SQL hash, SQLcl argv, working user, timeout, row limit, output limits,
  mode, backend, and structured outcome;
- do not record stdin, rendered connect strings, DSN, passwords, wallet
  passwords, wallet contents, or raw SQLcl stderr containing configured secret
  values.

Real read-only execution may be enabled only after tests cover the full
subprocess runner: environment merging, stdin handling, timeout kill behavior,
bounded output capture, JSON parsing, row limit behavior, redacted audit writes,
and failure classification.

## SQL Execution Adapter Boundary

Agent-facing tools should not expose SQLcl as their abstraction. Tools should
depend on a generic read-only SQL execution adapter that accepts a structured
SQL execution request and returns a structured response with generic backend
metadata: backend name, read-only mode, closed/rejected/succeeded status,
limits, row count, result rows, and redacted audit metadata.

`agent_runtime/sql_execution.py` is the first adapter boundary:

- `SqlExecutionAdapter` defines the read-only execution protocol.
- `SqlExecutionRequest` and `SqlExecutionResponse` define the backend-neutral
  request and response shape.
- `SqlclReadOnlyAdapter` is the SQLcl-backed implementation, but it still uses
  `build_read_only_sqlcl_execution_plan(...)` only to validate policy and
  construct redacted dry-run/audit metadata. Real execution is closed by
  default and remains closed even though a future runner hook exists.
- `FakeSqlExecutionAdapter` provides deterministic test behavior without
  credentials or a database.

This keeps the future agent tool boundary stable. A schema-inspection or
query-execution tool can later call the adapter without knowing SQLcl argv,
stdin, connection syntax, wallet paths, or subprocess details. SQLcl-specific
metadata may appear in redacted audit records, but tool callers should use only
the generic response fields.

MCP or server-based integration remains optional. The runtime can later expose
the same adapter through an MCP server, local service, or direct in-process
tool call. That choice should be driven by deployment, isolation, and
multi-client needs, not by the SQL execution API itself. The safety boundary is
the read-only adapter plus database least privilege, policy validation, row and
timeout limits, and redacted audit records; an MCP layer would package that
boundary rather than replace it.

## SQLcl Subprocess Runner Boundary

SQLcl subprocess execution is an internal runner behind
`SqlclReadOnlyAdapter`. It does not change the agent-facing adapter contract
and does not enable live SQL execution by default. `SqlclReadOnlyAdapter` calls
the runner only when `allow_real_execution=True`; normal planning, schema
context, and fake-result explanation flows keep that flag disabled.

Runner command contract:

- invoke SQLcl with an argv list, not a shell string;
- use the planned read-only shape `sql -S -L -nolog`;
- require an absolute SQLcl executable resolved from `SQLCL_PATH`;
- never place passwords, DSNs, wallet passwords, rendered connect strings, or
  SQL text in argv;
- return the redacted argv in audit metadata so reviewers can verify the
  subprocess shape without seeing secrets.

Runner environment contract:

- start from a minimal base environment needed for SQLcl execution rather than
  inheriting the whole process environment by default;
- merge plan-specific environment values after the base environment;
- allow plan values to override only approved SQLcl keys such as `TNS_ADMIN`;
- reject or ignore unexpected plan environment keys until a reviewed use case
  requires them;
- never propagate configured credential variables into the child process unless
  SQLcl requires them through an explicitly documented secure mechanism.

Private stdin contract:

- build the SQLcl connect command and session configuration as private stdin
  owned by the execution plan;
- send stdin through the subprocess pipe only;
- exclude stdin from reprs, result dictionaries, test failure messages, audit
  records, and trace records;
- redact stdin-derived values if SQLcl echoes them in stdout or stderr.

Timeout and process cleanup contract:

- use the plan timeout as a hard execution deadline;
- kill the SQLcl process on timeout and wait for process cleanup before
  returning;
- classify timeout as a structured `timeout` outcome with the configured
  timeout value and without raw secret-bearing output;
- keep partial stdout/stderr subject to the same bounded capture and redaction
  rules as non-timeout failures.

Output capture contract:

- capture stdout and stderr separately with explicit byte limits;
- stop reading or classify the outcome as `output_too_large` or
  `error_output_too_large` when a stream exceeds its configured limit;
- store only bounded, redacted stderr tails in error metadata;
- never write raw SQLcl output to logs before redaction.

Result parsing and classification contract:

- keep JSON parsing, row-limit checks, credential redaction, and outcome
  classification in the existing `oracle_adw` helper layer;
- keep the runner responsible only for process execution, bounded stream
  capture, timeout handling, return code collection, and raw captured bytes;
- classify SQLcl return-code failures through the helper layer as
  `sqlcl_error` rather than leaking backend-specific process details to tools;
- keep parser failures as structured `json_parse_failed` or
  `json_shape_not_supported` outcomes.

Audit metadata contract:

- record backend, mode, SQL hash, redacted argv, working user, timeout, row
  limit, output limits, return-code class, and structured outcome;
- do not record stdin, rendered connect strings, DSN, passwords, wallet
  passwords, wallet contents, raw SQL text, or unredacted stdout/stderr;
- mark adapter metadata with the explicit execution gate state and never imply
  live execution from planning or fake-result paths.

Required tests before any live ADW smoke test:

- argv construction proves no secrets, DSNs, rendered connect strings, or SQL
  text appear in process arguments;
- base environment and plan environment merging allow only approved keys and
  do not leak credential variables;
- private stdin is passed to the process but absent from reprs, responses,
  audit records, traces, and failure messages;
- timeout tests prove the process is killed, waited for, and classified as
  `timeout`;
- stdout and stderr limit tests prove oversized streams are bounded and
  classified without raw leakage;
- JSON success and parser-failure tests exercise the `oracle_adw` helpers, not
  duplicated runner parsing logic;
- non-zero SQLcl status maps to redacted `sqlcl_error` metadata;
- audit tests prove only redacted runner metadata is persisted;
- integration tests prove the default adapter remains closed and
  `allow_real_execution` cannot be reached by normal fake-result or planning
  flows.

SQLcl MCP or server integration remains optional and is not part of this
runner step. The runner is a local subprocess boundary behind the existing
adapter; any future MCP/server layer would package the same closed-by-default
safety rules rather than enabling execution on its own.

## Operator-Only Live Smoke Path

The first live ADW path is an operator-only CLI command, not an agent tool:

```bash
bin/agent operator adw-smoke --confirm-live-adw-smoke
```

The command uses one fixed SQL shape:

```sql
select 1 as smoke_check from dual
```

It loads `OracleAdwConfig.from_env()`, requires working-user credentials, and
never falls back to `ADMIN_USER`. The command also requires:

- explicit `--confirm-live-adw-smoke`;
- absolute `SQLCL_PATH`;
- `DB_DSN` as a wallet TNS alias only, not an easy-connect string or full
  descriptor;
- existing `DB_WALLET_PATH` directory for `TNS_ADMIN`;
- successful `verify_sqlcl(...)` before constructing the live adapter.

Only after those checks pass may the CLI instantiate
`SqlclReadOnlyAdapter(..., allow_real_execution=True)`. Normal `agent ask`,
schema context, query planning, fake result explanation, and default tool
registry paths must not construct the adapter with live execution enabled.
The SQLcl version check runs with a minimal allowlisted environment so
credential variables are not inherited by the version subprocess.

The smoke command writes redacted JSON to stdout and appends an
`operator.adw_smoke` audit event for confirmation-required, rejected, and
executed outcomes. The audit/output may include SQL hash, row count, generic
backend metadata, redacted SQLcl status, and redacted adapter audit metadata.
It records `live_execution_requested`, `live_execution_attempted`, and
`live_execution_succeeded` separately so rejected preflight checks do not imply
database execution. It must not include raw SQL text beyond the fixed
documented smoke shape, stdin, rendered connect strings, DSNs, passwords,
wallet passwords, wallet contents, or unredacted SQLcl stderr.

## Operator-Only Read-Only Query Path

The first general working-user query path is also operator-only:

```bash
bin/agent operator adw-query \
  --sql-file query.sql \
  --row-limit 100 \
  --timeout-seconds 30 \
  --confirm-live-adw-query
```

Supported SQL sources are mutually exclusive:

- `--sql-file PATH`, the preferred operational path;
- `--sql-stdin`, for pipe/heredoc workflows;
- `--sql TEXT`, a convenience path that should be avoided for sensitive
  literals because shell history and process listings can expose argv text.

The command validates SQL before any SQLcl verification or live adapter
construction. It rejects empty or oversized SQL, then applies the same
parser-less read-only policy used by the adapter. The adapter revalidates the
SQL before building the SQLcl plan, so CLI validation is a preflight gate rather
than the sole safety boundary.

The query command reuses the smoke preflight contract: explicit confirmation,
valid row/timeout/output/error limits, absolute `SQLCL_PATH`, working-user
credentials, wallet TNS alias `DB_DSN`, existing `DB_WALLET_PATH`, and
successful `verify_sqlcl(...)`. Only after those checks pass may it construct
`SqlclReadOnlyAdapter(..., allow_real_execution=True)` with purpose
`operator_live_adw_read_only_query`.

Stdout may include bounded, redacted result rows for the operator. Durable
`operator.adw_query` audit records omit arbitrary result rows and keep only
metadata such as SQL hash, SQL source kind, columns, row count, generic backend
metadata, redacted adapter audit metadata, and structured error details.
Audit records and normal runtime traces must not store raw operator SQL,
stdin, rendered connect strings, DSNs, passwords, wallet secrets, raw SQLcl
stderr, or wallet contents.

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
