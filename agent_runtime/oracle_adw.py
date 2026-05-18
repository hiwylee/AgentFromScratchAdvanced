"""Oracle ADW read-only connector foundation.

This module intentionally stops short of opening a database connection. The
Milestone 4 skeleton proves configuration loading, SQLcl and wallet checks, and
query safety validation before real execution is enabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Mapping

from agent_runtime.redaction import REDACTION, redact


SCHEMA_TABLES_QUERY = """
SELECT
    owner,
    table_name,
    num_rows,
    last_analyzed
FROM all_tables
WHERE owner = :owner
ORDER BY table_name
""".strip()

SCHEMA_COLUMNS_QUERY = """
SELECT
    owner,
    table_name,
    column_name,
    data_type,
    data_length,
    nullable,
    column_id
FROM all_tab_columns
WHERE owner = :owner
ORDER BY table_name, column_id
""".strip()

SCHEMA_COMMENTS_QUERY = """
SELECT
    c.owner,
    c.table_name,
    t.comments AS table_comment,
    c.column_name,
    c.comments AS column_comment
FROM all_col_comments c
LEFT JOIN all_tab_comments t
    ON t.owner = c.owner
    AND t.table_name = c.table_name
WHERE c.owner = :owner
ORDER BY c.table_name, c.column_name
""".strip()

SCHEMA_INTROSPECTION_QUERIES = {
    "tables": SCHEMA_TABLES_QUERY,
    "columns": SCHEMA_COLUMNS_QUERY,
    "comments": SCHEMA_COMMENTS_QUERY,
}

SAMPLE_SCHEMA_PROFILE_QUERY = """
SELECT
    owner,
    table_name,
    num_rows
FROM all_tables
WHERE owner IN ('SH', 'SSB')
ORDER BY owner, table_name
""".strip()

SH_REQUIRED_TABLES = frozenset(
    {
        "CHANNELS",
        "CUSTOMERS",
        "PRODUCTS",
        "SALES",
        "TIMES",
    }
)

SSB_REQUIRED_TABLES = frozenset(
    {
        "CUSTOMER",
        "DWDATE",
        "LINEORDER",
        "PART",
        "SUPPLIER",
    }
)

PROTECTED_WORKING_USER_NAMES = frozenset(
    {
        "ADMIN",
        "ANONYMOUS",
        "APEX_PUBLIC_USER",
        "CTXSYS",
        "DBSNMP",
        "GSMADMIN_INTERNAL",
        "MDSYS",
        "ORDDATA",
        "ORDSYS",
        "OUTLN",
        "SH",
        "SSB",
        "SYS",
        "SYSTEM",
        "WMSYS",
        "XDB",
    }
)

BLOCKED_WRITE_OR_ADMIN_TOKENS = frozenset(
    {
        "ALTER",
        "ANALYZE",
        "ASSOCIATE",
        "AUDIT",
        "CALL",
        "COMMENT",
        "COMMIT",
        "CREATE",
        "DELETE",
        "DISASSOCIATE",
        "DROP",
        "EXEC",
        "EXECUTE",
        "FLASHBACK",
        "GRANT",
        "INSERT",
        "LOCK",
        "MERGE",
        "NOAUDIT",
        "PURGE",
        "RENAME",
        "REVOKE",
        "ROLLBACK",
        "SAVEPOINT",
        "TRUNCATE",
        "UPDATE",
        "UPSERT",
    }
)

RESOURCE_HEAVY_HINTS = frozenset(
    {
        "APPEND",
        "BROADCAST",
        "FULL",
        "GATHER_PLAN_STATISTICS",
        "LEADING",
        "MATERIALIZE",
        "MONITOR",
        "NO_MERGE",
        "PARALLEL",
        "PARALLEL_INDEX",
        "PQ_DISTRIBUTE",
        "USE_HASH",
    }
)

SAFE_READ_ONLY_FUNCTIONS = frozenset(
    {
        "ABS",
        "AVG",
        "CAST",
        "CEIL",
        "COALESCE",
        "COUNT",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "EXTRACT",
        "FLOOR",
        "LOWER",
        "MAX",
        "MIN",
        "MOD",
        "NULLIF",
        "NVL",
        "ROUND",
        "STDDEV",
        "SUBSTR",
        "SUM",
        "TO_CHAR",
        "TO_DATE",
        "TRIM",
        "TRUNC",
        "UPPER",
        "VARIANCE",
    }
)

SQL_CONSTRUCTS_WITH_PARENS = frozenset(
    {
        "AS",
        "EXISTS",
        "FROM",
        "IN",
        "JOIN",
        "ON",
        "OVER",
        "SELECT",
        "TABLE",
        "WITH",
    }
)

SQLCL_COMMAND_TOKENS = frozenset(
    {
        "CONNECT",
        "CONN",
        "DISCONNECT",
        "HOST",
        "HO",
        "PROMPT",
        "RUN",
        "SPOOL",
        "START",
        "STORE",
        "@",
        "@@",
        "!",
        ".",
    }
)


@dataclass(frozen=True)
class OracleAdwConfig:
    sqlcl_path: str | None = None
    admin_user: str | None = None
    admin_user_pass: str | None = None
    db_user: str | None = None
    db_user_pass: str | None = None
    db_dsn: str | None = None
    db_wallet_path: str | None = None
    db_wallet_file: str | None = None
    db_wallet_pass: str | None = None

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "OracleAdwConfig":
        source = os.environ if env is None else env
        return cls(
            sqlcl_path=_empty_to_none(source.get("SQLCL_PATH")),
            admin_user=_empty_to_none(source.get("ADMIN_USER")),
            admin_user_pass=_empty_to_none(source.get("ADMIN_USER_PASS")),
            db_user=_empty_to_none(source.get("DB_USER")),
            db_user_pass=_empty_to_none(source.get("DB_USER_PASS")),
            db_dsn=_empty_to_none(source.get("DB_DSN")),
            db_wallet_path=_empty_to_none(source.get("DB_WALLET_PATH")),
            db_wallet_file=_empty_to_none(source.get("DB_WALLET_FILE")),
            db_wallet_pass=_empty_to_none(source.get("DB_WALLET_PASS")),
        )

    def redacted_status(self) -> dict[str, object]:
        return {
            "sqlcl_path": self.sqlcl_path,
            "admin_user_configured": self.admin_user is not None,
            "admin_user_pass_configured": self.admin_user_pass is not None,
            "db_user_configured": self.db_user is not None,
            "db_user_pass_configured": self.db_user_pass is not None,
            "db_dsn_configured": self.db_dsn is not None,
            "db_wallet_path": self.db_wallet_path,
            "db_wallet_file": self.db_wallet_file,
            "db_wallet_pass_configured": self.db_wallet_pass is not None,
        }

    def to_redacted_dict(self) -> dict[str, object]:
        redacted = redact(asdict(self))
        redacted["db_dsn"] = REDACTION if self.db_dsn else None
        return redacted


@dataclass(frozen=True)
class SqlclRunResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class SqlclReadOnlyExecutionSettings:
    timeout_seconds: int = 30
    row_limit: int = 1000
    max_output_bytes: int = 1_048_576
    max_error_bytes: int = 65_536


@dataclass(frozen=True)
class SqlclReadOnlyExecutionPlan:
    command: tuple[str, ...]
    env: Mapping[str, str]
    stdin: str = field(repr=False)
    timeout_seconds: int
    row_limit: int
    max_output_bytes: int
    max_error_bytes: int
    sql_sha256: str
    working_user: str
    _sensitive_values: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "env": redact(dict(self.env)),
            "stdin": REDACTION,
            "stdin_contains_credentials": True,
            "timeout_seconds": self.timeout_seconds,
            "row_limit": self.row_limit,
            "max_output_bytes": self.max_output_bytes,
            "max_error_bytes": self.max_error_bytes,
            "sql_sha256": self.sql_sha256,
            "working_user": self.working_user,
        }

    def redact_text(self, text: str) -> str:
        redacted = redact(text)
        for value in self._sensitive_values:
            if value and len(value) >= 4:
                redacted = redacted.replace(value, REDACTION)
        redacted = re.sub(
            rf"(?i)\bconnect\s+{re.escape(self.working_user)}\b[^\r\n]*",
            f"connect {REDACTION}",
            redacted,
        )
        return redacted


@dataclass(frozen=True)
class SqlclQueryResult:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlclExecutionError:
    code: str
    message: str
    returncode: int | None = None
    stderr: str | None = None

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlclExecutionOutcome:
    ok: bool
    result: SqlclQueryResult | None = None
    error: SqlclExecutionError | None = None

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlclStatus:
    configured_path: str | None
    resolved_path: str | None
    exists: bool
    executable: bool
    version_checked: bool
    ok: bool
    version: str | None = None
    error: str | None = None

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class WalletPathStatus:
    wallet_path: str | None
    wallet_path_exists: bool
    wallet_path_is_dir: bool
    wallet_file: str | None
    wallet_file_exists: bool
    wallet_file_is_file: bool
    ok: bool

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlPolicyResult:
    allowed: bool
    code: str
    reason: str


@dataclass(frozen=True)
class AdminProvisioningPlan:
    admin_user: str
    working_user: str
    password_placeholder: str
    sample_schema: str
    statements: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SampleDatasetRecommendation:
    selected: str
    reason: str
    available: dict[str, bool]
    table_counts: dict[str, int]
    missing_required_tables: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


SqlclRunner = Callable[[list[str]], SqlclRunResult]


def resolve_sqlcl_path(
    configured_path: str | None,
    *,
    path_lookup: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    if configured_path:
        expanded = Path(configured_path).expanduser()
        if expanded.is_absolute() or len(expanded.parts) > 1:
            return expanded
        resolved = path_lookup(configured_path)
        return Path(resolved) if resolved else expanded

    resolved_default = path_lookup("sql")
    if resolved_default:
        return Path(resolved_default)
    resolved_wrapper = path_lookup("sqlcl")
    return Path(resolved_wrapper) if resolved_wrapper else None


def verify_sqlcl(
    config: OracleAdwConfig,
    *,
    runner: SqlclRunner | None = None,
    path_lookup: Callable[[str], str | None] = shutil.which,
) -> SqlclStatus:
    resolved = resolve_sqlcl_path(config.sqlcl_path, path_lookup=path_lookup)
    if resolved is None:
        return SqlclStatus(
            configured_path=config.sqlcl_path,
            resolved_path=None,
            exists=False,
            executable=False,
            version_checked=False,
            ok=False,
            error="sqlcl_not_configured_or_found",
        )

    exists = resolved.exists()
    executable = exists and os.access(resolved, os.X_OK)
    if not exists or not executable:
        return SqlclStatus(
            configured_path=config.sqlcl_path,
            resolved_path=str(resolved),
            exists=exists,
            executable=executable,
            version_checked=False,
            ok=False,
            error="sqlcl_missing_or_not_executable",
        )

    run = runner or _run_sqlcl_version
    try:
        result = run([str(resolved), "-version"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SqlclStatus(
            configured_path=config.sqlcl_path,
            resolved_path=str(resolved),
            exists=exists,
            executable=executable,
            version_checked=True,
            ok=False,
            error=f"sqlcl_version_check_failed:{exc.__class__.__name__}",
        )

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    first_line = next(
        (line.strip() for line in output.splitlines() if line.strip()), None
    )
    return SqlclStatus(
        configured_path=config.sqlcl_path,
        resolved_path=str(resolved),
        exists=exists,
        executable=executable,
        version_checked=True,
        ok=result.returncode == 0,
        version=redact(first_line) if result.returncode == 0 else None,
        error=None if result.returncode == 0 else "sqlcl_version_check_failed",
    )


def verify_wallet_paths(config: OracleAdwConfig) -> WalletPathStatus:
    wallet_path = (
        Path(config.db_wallet_path).expanduser() if config.db_wallet_path else None
    )
    wallet_file = (
        Path(config.db_wallet_file).expanduser() if config.db_wallet_file else None
    )

    wallet_path_exists = wallet_path.exists() if wallet_path else False
    wallet_path_is_dir = wallet_path.is_dir() if wallet_path else False
    wallet_file_exists = wallet_file.exists() if wallet_file else False
    wallet_file_is_file = wallet_file.is_file() if wallet_file else False

    return WalletPathStatus(
        wallet_path=str(wallet_path) if wallet_path else None,
        wallet_path_exists=wallet_path_exists,
        wallet_path_is_dir=wallet_path_is_dir,
        wallet_file=str(wallet_file) if wallet_file else None,
        wallet_file_exists=wallet_file_exists,
        wallet_file_is_file=wallet_file_is_file,
        ok=(wallet_path_is_dir or wallet_file_is_file),
    )


def build_read_only_sqlcl_execution_plan(
    config: OracleAdwConfig,
    sql: str,
    *,
    settings: SqlclReadOnlyExecutionSettings | None = None,
) -> SqlclReadOnlyExecutionPlan:
    effective_settings = settings or SqlclReadOnlyExecutionSettings()
    _validate_execution_settings(effective_settings)
    require_read_only_sql(sql)

    if not config.sqlcl_path:
        raise ValueError("SQLCL_PATH is required for SQLcl execution planning")
    working_user = _required_working_user_identifier(config.db_user)
    if not config.db_user_pass:
        raise ValueError("DB_USER_PASS is required for SQLcl execution planning")
    if not config.db_dsn:
        raise ValueError("DB_DSN is required for SQLcl execution planning")
    _require_sqlcl_connect_component(config.db_user_pass, name="DB_USER_PASS")
    _require_sqlcl_connect_component(config.db_dsn, name="DB_DSN")

    env: dict[str, str] = {}
    if config.db_wallet_path:
        env["TNS_ADMIN"] = str(Path(config.db_wallet_path).expanduser())

    normalized_sql = _strip_trailing_semicolon(sql.strip())
    limited_sql = _wrap_sql_with_row_limit(
        normalized_sql,
        row_limit=effective_settings.row_limit,
    )
    stdin = _build_sqlcl_read_only_stdin(
        working_user=working_user,
        password=config.db_user_pass,
        dsn=config.db_dsn,
        limited_sql=limited_sql,
    )
    sensitive_values = tuple(
        value
        for value in (
            config.admin_user_pass,
            config.db_user_pass,
            config.db_dsn,
            config.db_wallet_pass,
        )
        if value
    )
    return SqlclReadOnlyExecutionPlan(
        command=(str(Path(config.sqlcl_path).expanduser()), "-S", "-L", "-nolog"),
        env=env,
        stdin=stdin,
        timeout_seconds=effective_settings.timeout_seconds,
        row_limit=effective_settings.row_limit,
        max_output_bytes=effective_settings.max_output_bytes,
        max_error_bytes=effective_settings.max_error_bytes,
        sql_sha256=hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest(),
        working_user=working_user,
        _sensitive_values=sensitive_values,
    )


def classify_sqlcl_read_only_result(
    plan: SqlclReadOnlyExecutionPlan,
    result: SqlclRunResult,
) -> SqlclExecutionOutcome:
    if _byte_length(result.stdout) > plan.max_output_bytes:
        return SqlclExecutionOutcome(
            ok=False,
            error=SqlclExecutionError(
                code="output_too_large",
                message="SQLcl stdout exceeded the configured capture limit.",
                returncode=result.returncode,
            ),
        )
    if _byte_length(result.stderr) > plan.max_error_bytes:
        return SqlclExecutionOutcome(
            ok=False,
            error=SqlclExecutionError(
                code="error_output_too_large",
                message="SQLcl stderr exceeded the configured capture limit.",
                returncode=result.returncode,
            ),
        )
    if result.returncode != 0:
        return SqlclExecutionOutcome(
            ok=False,
            error=SqlclExecutionError(
                code="sqlcl_error",
                message="SQLcl returned a non-zero status for the read-only query.",
                returncode=result.returncode,
                stderr=plan.redact_text(result.stderr[-plan.max_error_bytes :]),
            ),
        )

    try:
        parsed = parse_sqlcl_json_output(result.stdout, row_limit=plan.row_limit)
    except ValueError as exc:
        return SqlclExecutionOutcome(
            ok=False,
            error=SqlclExecutionError(
                code=str(exc),
                message="SQLcl output could not be parsed as bounded JSON rows.",
                returncode=result.returncode,
            ),
        )
    return SqlclExecutionOutcome(ok=True, result=_redact_query_result(plan, parsed))


def classify_sqlcl_timeout(
    plan: SqlclReadOnlyExecutionPlan,
    exc: subprocess.TimeoutExpired,
) -> SqlclExecutionOutcome:
    return SqlclExecutionOutcome(
        ok=False,
        error=SqlclExecutionError(
            code="timeout",
            message=f"SQLcl read-only query exceeded {plan.timeout_seconds} seconds.",
            stderr=plan.redact_text(str(exc.stderr or "")) or None,
        ),
    )


def parse_sqlcl_json_output(stdout: str, *, row_limit: int) -> SqlclQueryResult:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("json_parse_failed") from exc

    columns, rows = _extract_sqlcl_rows(payload)
    if len(rows) > row_limit:
        raise ValueError("row_limit_exceeded")
    if not columns and rows:
        columns = tuple(rows[0].keys())
    return SqlclQueryResult(
        columns=tuple(columns),
        rows=tuple(rows),
        row_count=len(rows),
    )


def build_redacted_sqlcl_audit_record(
    event: str,
    plan: SqlclReadOnlyExecutionPlan,
    outcome: SqlclExecutionOutcome | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "event": event,
        "backend": "sqlcl",
        "mode": "read_only",
        "execution": plan.to_redacted_dict(),
    }
    if outcome is not None:
        record["outcome"] = outcome.to_redacted_dict()
    return redact(record)


def validate_read_only_sql(sql: str) -> SqlPolicyResult:
    if not sql or not sql.strip():
        return SqlPolicyResult(False, "empty_sql", "SQL text is empty.")

    if _has_sqlcl_slash_block(sql):
        return SqlPolicyResult(
            False,
            "procedural_block",
            "SQLcl slash block execution is not allowed.",
        )

    if _has_blank_line(sql):
        return SqlPolicyResult(
            False,
            "sqlcl_blank_line",
            "Blank lines are not allowed in SQLcl-bound SQL text.",
        )

    if _has_sqlcl_command_line(sql):
        return SqlPolicyResult(
            False,
            "sqlcl_command",
            "SQLcl command lines are not allowed in SQL text.",
        )

    statements = _split_sql_statements(sql)
    non_empty = [statement.strip() for statement in statements if statement.strip()]
    if len(non_empty) != 1:
        return SqlPolicyResult(
            False,
            "unsafe_multi_statement",
            "Exactly one read-only SQL statement is allowed.",
        )

    statement = non_empty[0]
    masked = _mask_comments_and_literals(statement)
    upper = masked.upper()

    if _has_resource_heavy_hint(statement):
        return SqlPolicyResult(
            False,
            "resource_heavy_hint",
            "Resource-heavy optimizer hints are not allowed.",
        )

    first_keyword = _first_keyword(upper)
    if first_keyword in {"BEGIN", "DECLARE"}:
        return SqlPolicyResult(
            False,
            "procedural_block",
            "PL/SQL blocks are not allowed.",
        )

    if re.search(r"\bFOR\s+UPDATE\b", upper):
        return SqlPolicyResult(
            False,
            "select_for_update",
            "SELECT FOR UPDATE is not read-only.",
        )

    blocked_token = _first_blocked_token(upper)
    if blocked_token:
        return SqlPolicyResult(
            False,
            "write_or_admin_sql",
            f"{blocked_token} is not allowed in read-only SQL.",
        )

    if first_keyword not in {"SELECT", "WITH"}:
        return SqlPolicyResult(
            False,
            "unsupported_statement",
            "Only SELECT and WITH read-only queries are allowed.",
        )

    if "@" in upper:
        return SqlPolicyResult(
            False,
            "database_link",
            "Database links are not allowed.",
        )

    callable_sql = _strip_sql_comments(_mask_string_literals_keep_identifiers(statement)).upper()
    if _has_disallowed_function_call(callable_sql):
        return SqlPolicyResult(
            False,
            "function_call_not_allowed",
            "Function and package calls are blocked until a safe allowlist exists.",
        )
    if _has_nested_select(callable_sql) and _has_dotted_reference(callable_sql):
        return SqlPolicyResult(
            False,
            "nested_dotted_reference_not_allowed",
            "Dotted references inside nested query shapes require a real SQL parser.",
        )
    if _has_compound_query(callable_sql) and _has_dotted_reference(callable_sql):
        return SqlPolicyResult(
            False,
            "compound_dotted_reference_not_allowed",
            "Dotted references inside compound query shapes require a real SQL parser.",
        )
    if _has_multi_part_dotted_reference(callable_sql):
        return SqlPolicyResult(
            False,
            "multi_part_dotted_reference_not_allowed",
            "Multi-part dotted references require a real SQL parser.",
        )
    if _has_sequence_mutation_reference(callable_sql):
        return SqlPolicyResult(
            False,
            "sequence_mutation_not_allowed",
            "Sequence NEXTVAL is a mutation and is not allowed in read-only SQL.",
        )
    if _has_unqualified_dotted_reference(callable_sql):
        return SqlPolicyResult(
            False,
            "dotted_reference_not_allowed",
            "Dotted references must use a table name or alias visible in FROM/JOIN.",
        )

    return SqlPolicyResult(True, "allowed", "SQL is read-only by policy.")


def require_read_only_sql(sql: str) -> None:
    result = validate_read_only_sql(sql)
    if not result.allowed:
        raise ValueError(f"{result.code}: {result.reason}")


def build_working_user_provisioning_plan(
    config: OracleAdwConfig,
    *,
    sample_schema: str,
    password_placeholder: str = "__DB_USER_PASS__",
    create_private_synonyms: bool = True,
) -> AdminProvisioningPlan:
    admin_user = _required_identifier(config.admin_user, "ADMIN_USER")
    working_user = _required_working_user_identifier(config.db_user)
    selected_schema = _required_sample_schema(sample_schema)
    clean_placeholder = _required_password_placeholder(password_placeholder)
    if not config.admin_user_pass:
        raise ValueError("ADMIN_USER_PASS is required to create the working user")
    if not config.db_user_pass:
        raise ValueError("DB_USER_PASS is required but must not be embedded in provisioning statements")

    required_tables = _required_tables_for_sample_schema(selected_schema)
    synonym_statements = (
        tuple(
            f"CREATE OR REPLACE SYNONYM {working_user}.{table_name} FOR {selected_schema}.{table_name}"
            for table_name in required_tables
        )
        if create_private_synonyms
        else ()
    )
    statements = (
        f"CREATE USER {working_user} IDENTIFIED BY \"{clean_placeholder}\"",
        f"GRANT CREATE SESSION TO {working_user}",
        f"ALTER USER {working_user} QUOTA 0 ON DATA",
        *(
            f"GRANT SELECT ON {selected_schema}.{table_name} TO {working_user}"
            for table_name in required_tables
        ),
        *synonym_statements,
    )
    return AdminProvisioningPlan(
        admin_user=admin_user,
        working_user=working_user,
        password_placeholder=clean_placeholder,
        sample_schema=selected_schema,
        statements=tuple(statements),
        warnings=(
            "Execute only through an admin-approved setup workflow.",
            "Replace the password placeholder only inside the SQLcl execution boundary.",
            "Do not log rendered DDL that contains the real password.",
            "Private synonyms are created so read-only analysis SQL can avoid schema-qualified dotted references.",
        ),
    )


def recommend_sample_dataset(table_rows: list[Mapping[str, object]]) -> SampleDatasetRecommendation:
    tables_by_owner: dict[str, set[str]] = {"SH": set(), "SSB": set()}
    for row in table_rows:
        owner = str(_mapping_value_case_insensitive(row, "owner", "")).upper()
        table_name = str(_mapping_value_case_insensitive(row, "table_name", "")).upper()
        if owner in tables_by_owner and table_name:
            tables_by_owner[owner].add(table_name)

    missing = {
        "SH": tuple(sorted(SH_REQUIRED_TABLES - tables_by_owner["SH"])),
        "SSB": tuple(sorted(SSB_REQUIRED_TABLES - tables_by_owner["SSB"])),
    }
    available = {
        "SH": not missing["SH"],
        "SSB": not missing["SSB"],
    }
    table_counts = {owner: len(tables) for owner, tables in tables_by_owner.items()}
    if available["SH"]:
        return SampleDatasetRecommendation(
            selected="SH",
            reason="SH is preferred for natural-language business analytics because it has sales, product, customer, channel, and time dimensions.",
            available=available,
            table_counts=table_counts,
            missing_required_tables=missing,
        )
    if available["SSB"]:
        return SampleDatasetRecommendation(
            selected="SSB",
            reason="SSB is available and suitable for star-schema query benchmarks when SH is not present.",
            available=available,
            table_counts=table_counts,
            missing_required_tables=missing,
        )
    return SampleDatasetRecommendation(
        selected="none",
        reason="Neither SH nor SSB has the required core tables visible to the current account.",
        available=available,
        table_counts=table_counts,
        missing_required_tables=missing,
    )


class OracleAdwReadOnlyConnector:
    """Read-only Oracle ADW boundary with real execution intentionally closed."""

    def __init__(self, config: OracleAdwConfig) -> None:
        self.config = config

    def validate_query(self, sql: str) -> SqlPolicyResult:
        return validate_read_only_sql(sql)

    def execute_read_only_query(self, sql: str) -> None:
        require_read_only_sql(sql)
        raise NotImplementedError(
            "Oracle ADW execution is intentionally not implemented in the "
            "Milestone 4 foundation skeleton."
        )


def _run_sqlcl_version(command: list[str]) -> SqlclRunResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=_minimal_sqlcl_version_env(),
        text=True,
        timeout=10,
    )
    return SqlclRunResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _minimal_sqlcl_version_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_execution_settings(settings: SqlclReadOnlyExecutionSettings) -> None:
    if not 1 <= settings.timeout_seconds <= 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    if not 1 <= settings.row_limit <= 10_000:
        raise ValueError("row_limit must be between 1 and 10000")
    if not 1_024 <= settings.max_output_bytes <= 10_485_760:
        raise ValueError("max_output_bytes must be between 1024 and 10485760")
    if not 1_024 <= settings.max_error_bytes <= 1_048_576:
        raise ValueError("max_error_bytes must be between 1024 and 1048576")


def _strip_trailing_semicolon(sql: str) -> str:
    return sql[:-1].rstrip() if sql.endswith(";") else sql


def _wrap_sql_with_row_limit(sql: str, *, row_limit: int) -> str:
    return f"SELECT * FROM (\n{sql}\n) WHERE ROWNUM <= {row_limit}"


def _build_sqlcl_read_only_stdin(
    *,
    working_user: str,
    password: str,
    dsn: str,
    limited_sql: str,
) -> str:
    escaped_password = password.replace('"', '""')
    return "\n".join(
        (
            "set echo off",
            "set feedback off",
            "set heading off",
            "set pagesize 0",
            "set sqlformat json",
            "set define off",
            "whenever sqlerror exit sql.sqlcode",
            "whenever oserror exit failure",
            f'connect {working_user}/"{escaped_password}"@{dsn}',
            f"{limited_sql};",
            "exit",
            "",
        )
    )


def _require_sqlcl_connect_component(value: str, *, name: str) -> None:
    if any(_is_disallowed_sqlcl_connect_char(char) for char in value):
        raise ValueError(
            f"{name} contains characters that are not allowed in SQLcl connect input"
        )


def _is_disallowed_sqlcl_connect_char(char: str) -> bool:
    return ord(char) < 32 or ord(char) == 127


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def _extract_sqlcl_rows(payload: object) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    if isinstance(payload, list):
        return (), [_string_keyed_row(item) for item in payload]
    if not isinstance(payload, dict):
        raise ValueError("json_shape_not_supported")

    result_payload = payload
    results = payload.get("results")
    if isinstance(results, list):
        if not results:
            return (), []
        first_result = results[0]
        if not isinstance(first_result, dict):
            raise ValueError("json_shape_not_supported")
        result_payload = first_result

    columns = _extract_sqlcl_columns(result_payload.get("columns"))
    items = result_payload.get("items", result_payload.get("rows", []))
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("json_shape_not_supported")
    return columns, [_string_keyed_row(item) for item in items]


def _extract_sqlcl_columns(columns_payload: object) -> tuple[str, ...]:
    if not isinstance(columns_payload, list):
        return ()
    columns: list[str] = []
    for item in columns_payload:
        if isinstance(item, str):
            columns.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("columnName") or item.get("label")
            if name is not None:
                columns.append(str(name))
    return tuple(columns)


def _string_keyed_row(row: object) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("json_shape_not_supported")
    return {str(key): value for key, value in row.items()}


def _redact_query_result(
    plan: SqlclReadOnlyExecutionPlan,
    result: SqlclQueryResult,
) -> SqlclQueryResult:
    return SqlclQueryResult(
        columns=result.columns,
        rows=tuple(_redact_sensitive_values(plan, row) for row in result.rows),
        row_count=result.row_count,
    )


def _redact_sensitive_values(plan: SqlclReadOnlyExecutionPlan, value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_sensitive_values(plan, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_values(plan, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_values(plan, item) for item in value)
    if isinstance(value, str):
        return plan.redact_text(value)
    return value


def _required_identifier(value: str | None, env_name: str) -> str:
    if not value:
        raise ValueError(f"{env_name} is required")
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", normalized):
        raise ValueError(f"{env_name} must be a simple Oracle identifier")
    return normalized


def _required_working_user_identifier(value: str | None) -> str:
    working_user = _required_identifier(value, "DB_USER")
    if working_user in PROTECTED_WORKING_USER_NAMES:
        raise ValueError("DB_USER must not be an administrative, system, or sample schema name")
    return working_user


def _required_sample_schema(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {"SH", "SSB"}:
        raise ValueError("sample_schema must be SH or SSB")
    return normalized


def _required_password_placeholder(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("password_placeholder is required")
    placeholder = value.strip()
    if not re.fullmatch(r"__[A-Z0-9_]+__", placeholder):
        raise ValueError("password_placeholder must be a symbolic __NAME__ token")
    return placeholder


def _required_tables_for_sample_schema(sample_schema: str) -> tuple[str, ...]:
    if sample_schema == "SH":
        return tuple(sorted(SH_REQUIRED_TABLES))
    if sample_schema == "SSB":
        return tuple(sorted(SSB_REQUIRED_TABLES))
    raise ValueError("sample_schema must be SH or SSB")


def _mapping_value_case_insensitive(
    row: Mapping[str, object], key: str, default: object = None
) -> object:
    if key in row:
        return row[key]
    upper_key = key.upper()
    if upper_key in row:
        return row[upper_key]
    lower_key = key.lower()
    if lower_key in row:
        return row[lower_key]
    return default


def _has_sqlcl_slash_block(sql: str) -> bool:
    return any(
        line.lstrip().startswith("/")
        for line in sql.splitlines()
    )


def _has_blank_line(sql: str) -> bool:
    return re.search(r"(?m)^\s*$", sql) is not None


def _has_sqlcl_command_line(sql: str) -> bool:
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("@", "!")):
            return True
        token = stripped.split(maxsplit=1)[0].upper()
        if token in {"H", "HO", "HOS"} or token.startswith("HOST"):
            return True
        if token.startswith("CONN"):
            return True
        if token in SQLCL_COMMAND_TOKENS:
            return True
    return False


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    start = 0
    i = 0
    state = "normal"
    while i < len(sql):
        char = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if state == "normal":
            if char == "'":
                state = "single_quote"
            elif char == '"':
                state = "double_quote"
            elif char == "-" and nxt == "-":
                state = "line_comment"
                i += 1
            elif char == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif char == ";":
                statements.append(sql[start:i])
                start = i + 1
        elif state == "single_quote":
            if char == "'" and nxt == "'":
                i += 1
            elif char == "'":
                state = "normal"
        elif state == "double_quote":
            if char == '"':
                state = "normal"
        elif state == "line_comment":
            if char == "\n":
                state = "normal"
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                state = "normal"
                i += 1

        i += 1

    statements.append(sql[start:])
    return statements


def _mask_comments_and_literals(sql: str) -> str:
    masked = _mask_literals_keep_comments(sql)
    masked = re.sub(r"--[^\n]*", " ", masked)
    masked = re.sub(r"/\*.*?\*/", " ", masked, flags=re.DOTALL)
    return masked


def _mask_literals_keep_comments(sql: str) -> str:
    chars = list(sql)
    i = 0
    state = "normal"
    while i < len(chars):
        char = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""

        if state == "normal":
            if char == "'":
                chars[i] = " "
                state = "single_quote"
            elif char == '"':
                chars[i] = " "
                state = "double_quote"
        elif state == "single_quote":
            chars[i] = " "
            if char == "'" and nxt == "'":
                i += 1
                chars[i] = " "
            elif char == "'":
                state = "normal"
        elif state == "double_quote":
            chars[i] = " "
            if char == '"':
                state = "normal"

        i += 1
    return "".join(chars)


def _mask_string_literals_keep_identifiers(sql: str) -> str:
    chars = list(sql)
    i = 0
    state = "normal"
    while i < len(chars):
        char = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""

        if state == "normal":
            if char == "'":
                chars[i] = " "
                state = "single_quote"
        elif state == "single_quote":
            chars[i] = " "
            if char == "'" and nxt == "'":
                i += 1
                chars[i] = " "
            elif char == "'":
                state = "normal"

        i += 1
    return "".join(chars)


def _strip_sql_comments(sql: str) -> str:
    chars: list[str] = []
    i = 0
    state = "normal"
    while i < len(sql):
        char = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if state == "normal":
            if char == '"':
                chars.append(char)
                state = "double_quote"
            elif char == "-" and nxt == "-":
                chars.append(" ")
                state = "line_comment"
                i += 1
            elif char == "/" and nxt == "*":
                chars.append(" ")
                state = "block_comment"
                i += 1
            else:
                chars.append(char)
        elif state == "double_quote":
            chars.append(char)
            if char == '"' and nxt == '"':
                i += 1
                chars.append(nxt)
            elif char == '"':
                state = "normal"
        elif state == "line_comment":
            if char == "\n":
                chars.append(char)
                state = "normal"
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                chars.append(" ")
                state = "normal"
                i += 1

        i += 1
    return "".join(chars)


def _has_resource_heavy_hint(sql: str) -> bool:
    sql_without_literals = _mask_literals_keep_comments(sql)
    for match in re.finditer(r"/\*\+(.*?)\*/", sql_without_literals, flags=re.DOTALL):
        hint_body = match.group(1).upper()
        hint_tokens = set(re.findall(r"[A-Z_]+", hint_body))
        if hint_tokens & RESOURCE_HEAVY_HINTS:
            return True
    for match in re.finditer(r"--\+(.*?)(?:\n|$)", sql_without_literals):
        hint_body = match.group(1).upper()
        hint_tokens = set(re.findall(r"[A-Z_]+", hint_body))
        if hint_tokens & RESOURCE_HEAVY_HINTS:
            return True
    return False


def _has_disallowed_function_call(upper_sql: str) -> bool:
    identifier = r'(?:[A-Z][A-Z0-9_$#]*|"(?:[^"]|"")+")'
    if re.search(rf"{identifier}\s*\.\s*{identifier}\s*\(", upper_sql):
        return True
    if re.search(r'"(?:[^"]|"")+"\s*\(', upper_sql):
        return True
    for match in re.finditer(r"\b([A-Z][A-Z0-9_$#]*)\s*\(", upper_sql):
        name = match.group(1)
        if name in SAFE_READ_ONLY_FUNCTIONS or name in SQL_CONSTRUCTS_WITH_PARENS:
            continue
        return True
    return False


def _has_unqualified_dotted_reference(upper_sql: str) -> bool:
    allowed_qualifiers = _visible_sql_qualifiers(upper_sql)
    identifier = r'(?:[A-Z][A-Z0-9_$#]*|"(?:[^"]|"")+")'
    for match in re.finditer(rf"({identifier})\s*\.\s*({identifier})", upper_sql):
        left = _normalize_identifier(match.group(1))
        if left not in allowed_qualifiers:
            return True
    return False


def _has_dotted_reference(upper_sql: str) -> bool:
    identifier = r'(?:[A-Z][A-Z0-9_$#]*|"(?:[^"]|"")+")'
    return re.search(rf"{identifier}\s*\.\s*{identifier}", upper_sql) is not None


def _has_multi_part_dotted_reference(upper_sql: str) -> bool:
    identifier = r'(?:[A-Z][A-Z0-9_$#]*|"(?:[^"]|"")+")'
    return re.search(rf"{identifier}\s*\.\s*{identifier}\s*\.\s*{identifier}", upper_sql) is not None


def _has_sequence_mutation_reference(upper_sql: str) -> bool:
    return re.search(r'\.\s*(?:NEXTVAL\b|"NEXTVAL")', upper_sql) is not None


def _has_nested_select(upper_sql: str) -> bool:
    return re.search(r"\(\s*SELECT\b", upper_sql) is not None


def _has_compound_query(upper_sql: str) -> bool:
    return re.search(r"\b(UNION(?:\s+ALL)?|INTERSECT|MINUS)\b", upper_sql) is not None


def _visible_sql_qualifiers(upper_sql: str) -> set[str]:
    identifier = r'(?:[A-Z][A-Z0-9_$#]*|"(?:[^"]|"")+")'
    qualifiers: set[str] = set()
    for match in re.finditer(
        rf"\b(?:FROM|JOIN)\s+({identifier}(?:\s*\.\s*{identifier}){{0,2}})(?:\s+(?:AS\s+)?({identifier}))?",
        upper_sql,
    ):
        table_path = match.group(1)
        path_parts = [
            _normalize_identifier(part)
            for part in re.findall(identifier, table_path)
        ]
        if path_parts:
            qualifiers.add(path_parts[-1])
        alias = match.group(2)
        if alias:
            normalized_alias = _normalize_identifier(alias)
            if normalized_alias not in {
                "CROSS",
                "FULL",
                "INNER",
                "JOIN",
                "LEFT",
                "ON",
                "RIGHT",
                "WHERE",
            }:
                qualifiers.add(normalized_alias)
    return qualifiers


def _normalize_identifier(identifier: str) -> str:
    stripped = identifier.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped[1:-1].replace('""', '"')
    return stripped


def _first_keyword(upper_sql: str) -> str | None:
    match = re.search(r"\b[A-Z][A-Z0-9_$#]*\b", upper_sql)
    return match.group(0) if match else None


def _first_blocked_token(upper_sql: str) -> str | None:
    for token in re.findall(r"\b[A-Z][A-Z0-9_$#]*\b", upper_sql):
        if token in BLOCKED_WRITE_OR_ADMIN_TOKENS:
            return token
    return None


__all__ = [
    "OracleAdwConfig",
    "AdminProvisioningPlan",
    "OracleAdwReadOnlyConnector",
    "SCHEMA_COLUMNS_QUERY",
    "SCHEMA_COMMENTS_QUERY",
    "SCHEMA_INTROSPECTION_QUERIES",
    "SCHEMA_TABLES_QUERY",
    "SAMPLE_SCHEMA_PROFILE_QUERY",
    "SampleDatasetRecommendation",
    "SqlclExecutionError",
    "SqlclExecutionOutcome",
    "SqlclQueryResult",
    "SqlclReadOnlyExecutionPlan",
    "SqlclReadOnlyExecutionSettings",
    "SqlPolicyResult",
    "SqlclRunResult",
    "SqlclStatus",
    "WalletPathStatus",
    "build_working_user_provisioning_plan",
    "build_read_only_sqlcl_execution_plan",
    "build_redacted_sqlcl_audit_record",
    "classify_sqlcl_read_only_result",
    "classify_sqlcl_timeout",
    "parse_sqlcl_json_output",
    "recommend_sample_dataset",
    "require_read_only_sql",
    "resolve_sqlcl_path",
    "validate_read_only_sql",
    "verify_sqlcl",
    "verify_wallet_paths",
]
