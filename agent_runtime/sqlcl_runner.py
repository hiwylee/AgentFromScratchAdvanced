"""Standalone SQLcl subprocess runner boundary.

This module executes a prebuilt SQLcl plan and deliberately knows nothing about
agent tools or adapter policy. It is a narrow subprocess boundary that can be
wired into the read-only adapter later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import subprocess
import threading
import time
from typing import Any, Mapping, Protocol, Sequence

from agent_runtime.oracle_adw import SqlclReadOnlyExecutionPlan, SqlclRunResult
from agent_runtime.redaction import REDACTION

DEFAULT_ALLOWED_PLAN_ENV_KEYS = ("TNS_ADMIN",)


class SubprocessRunCallable(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        input: str,
        env: Mapping[str, str],
        timeout: int,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True, repr=False)
class SqlclRunnerResult:
    """Structured result from the SQLcl subprocess boundary."""

    returncode: int
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    timed_out: bool = False
    stdout_too_large: bool = False
    stderr_too_large: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    command: tuple[str, ...] = field(default=(), repr=False)
    env_keys: tuple[str, ...] = field(default=(), repr=False)
    timeout_seconds: int | None = None

    @property
    def status(self) -> str:
        if self.timed_out:
            return "timeout"
        if self.stdout_too_large:
            return "output_too_large"
        if self.stderr_too_large:
            return "error_output_too_large"
        if self.returncode == 0:
            return "completed"
        return "failed"

    def to_sqlcl_run_result(self) -> SqlclRunResult:
        return SqlclRunResult(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "stdout_too_large": self.stdout_too_large,
            "stderr_too_large": self.stderr_too_large,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "command": list(self.command),
            "env_keys": list(self.env_keys),
            "stdin": REDACTION,
            "timeout_seconds": self.timeout_seconds,
        }

    def __repr__(self) -> str:
        return f"SqlclRunnerResult({self.to_redacted_dict()!r})"


@dataclass(frozen=True, repr=False)
class SqlclSubprocessRequest:
    """Generic bounded SQLcl subprocess request."""

    command: Sequence[str]
    stdin: str = field(repr=False)
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    timeout_seconds: int = 30
    max_output_bytes: int = 1_048_576
    max_error_bytes: int = 65_536
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)


def run_sqlcl_subprocess(request: SqlclSubprocessRequest) -> SqlclRunnerResult:
    """Run SQLcl with bounded live stream capture and generic redaction."""

    argv = tuple(request.command)
    try:
        completed = _run_subprocess_with_stream_limits(
            argv,
            input_text=request.stdin,
            env=request.env,
            timeout_seconds=request.timeout_seconds,
            max_stdout_bytes=request.max_output_bytes,
            max_stderr_bytes=request.max_error_bytes,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _safe_process_text(exc.stdout)
        stderr = _append_runner_message(
            _safe_process_text(exc.stderr),
            f"SQLcl subprocess timed out after {request.timeout_seconds} seconds.",
        )
        return _build_subprocess_result(
            request,
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
    except OSError as exc:
        return _build_subprocess_result(
            request,
            returncode=-1,
            stdout="",
            stderr=f"SQLcl subprocess failed before returning output: {exc.__class__.__name__}.",
        )

    return _build_subprocess_result(
        request,
        returncode=int(completed.returncode),
        stdout=_safe_process_text(completed.stdout),
        stderr=_safe_process_text(completed.stderr),
    )


def run_sqlcl_plan(
    plan: SqlclReadOnlyExecutionPlan,
    *,
    base_env: Mapping[str, str] | None = None,
    allowed_plan_env_keys: tuple[str, ...] = DEFAULT_ALLOWED_PLAN_ENV_KEYS,
    runner: SubprocessRunCallable | None = None,
) -> SqlclRunnerResult:
    """Run a SQLcl execution plan through a bounded subprocess boundary.

    The argv comes only from ``plan.command``. The caller supplies the base
    environment; plan overrides are merged on top. Stdin is sent only as private
    process input and is never returned in metadata.
    """

    merged_env = dict(base_env or {})
    plan_env = _allowed_plan_env(plan.env, allowed_plan_env_keys)
    merged_env.update(plan_env)
    argv = tuple(plan.command)

    try:
        if runner is None:
            completed = _run_subprocess_with_stream_limits(
                argv,
                input_text=plan.stdin,
                env=merged_env,
                timeout_seconds=plan.timeout_seconds,
                max_stdout_bytes=plan.max_output_bytes,
                max_stderr_bytes=plan.max_error_bytes,
            )
        else:
            completed = runner(
                argv,
                input=plan.stdin,
                env=merged_env,
                timeout=plan.timeout_seconds,
                capture_output=True,
                text=True,
            )
    except subprocess.TimeoutExpired as exc:
        stdout = _safe_process_text(exc.stdout)
        stderr = _safe_process_text(exc.stderr)
        stderr = _append_runner_message(
            stderr,
            f"SQLcl subprocess timed out after {plan.timeout_seconds} seconds.",
        )
        return _build_result(
            plan,
            env=merged_env,
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )

    return _build_result(
        plan,
        env=merged_env,
        returncode=int(completed.returncode),
        stdout=_safe_process_text(completed.stdout),
        stderr=_safe_process_text(completed.stderr),
    )


@dataclass(frozen=True)
class _StreamLimitedCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


def _run_subprocess_with_stream_limits(
    args: Sequence[str],
    *,
    input_text: str,
    env: Mapping[str, str],
    timeout_seconds: int,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> _StreamLimitedCompletedProcess:
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        text=False,
    )
    stop_process = threading.Event()
    stdout = _BoundedProcessStream(max_stdout_bytes, stop_process)
    stderr = _BoundedProcessStream(max_stderr_bytes, stop_process)

    threads = [
        threading.Thread(
            target=_write_process_stdin,
            args=(process, input_text),
            daemon=True,
        ),
        threading.Thread(
            target=stdout.read_from,
            args=(process.stdout,),
            daemon=True,
        ),
        threading.Thread(
            target=stderr.read_from,
            args=(process.stderr,),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        while True:
            process_exited = process.poll() is not None
            streams_drained = stdout.done and stderr.done
            if process_exited and streams_drained:
                break
            if stop_process.is_set():
                _terminate_process(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process(process)
                break
            time.sleep(0.01)

        for thread in threads:
            thread.join(timeout=1)

        returncode = process.poll()
        if returncode is None:
            process.kill()
            returncode = process.wait()
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    if timed_out:
        raise subprocess.TimeoutExpired(
            cmd=args,
            timeout=timeout_seconds,
            output=stdout.text(),
            stderr=stderr.text(),
        )

    return _StreamLimitedCompletedProcess(
        returncode=int(returncode),
        stdout=stdout.text(),
        stderr=stderr.text(),
    )


class _BoundedProcessStream:
    def __init__(self, max_bytes: int, stop_process: threading.Event) -> None:
        self._max_bytes = max_bytes
        self._stop_process = stop_process
        self._buffer = bytearray()
        self._done = threading.Event()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def read_from(self, stream: Any) -> None:
        try:
            if stream is None:
                return
            fileno = stream.fileno()
            while True:
                try:
                    chunk = os.read(fileno, 8192)
                except OSError:
                    return
                if chunk == b"":
                    return
                remaining = self._max_bytes + 1 - len(self._buffer)
                if remaining > 0:
                    self._buffer.extend(chunk[:remaining])
                if len(self._buffer) > self._max_bytes:
                    self._stop_process.set()
                    return
        finally:
            self._done.set()

    def close(self) -> None:
        self._done.set()

    def text(self) -> str:
        return bytes(self._buffer).decode("utf-8", errors="replace")


def _write_process_stdin(process: subprocess.Popen[bytes], input_text: str) -> None:
    if process.stdin is None:
        return
    try:
        process.stdin.write(input_text.encode("utf-8"))
        process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def build_redacted_sqlcl_runner_metadata(
    plan: SqlclReadOnlyExecutionPlan,
    *,
    base_env: Mapping[str, str] | None = None,
    allowed_plan_env_keys: tuple[str, ...] = DEFAULT_ALLOWED_PLAN_ENV_KEYS,
) -> dict[str, object]:
    """Return subprocess metadata without stdin or environment values."""

    env_keys = set(base_env or {})
    plan_env = _allowed_plan_env(plan.env, allowed_plan_env_keys)
    rejected = _rejected_plan_env_keys(plan.env, allowed_plan_env_keys)
    env_keys.update(plan_env)
    return {
        "command": list(plan.command),
        "env_keys": sorted(env_keys),
        "plan_env": {key: REDACTION for key in plan_env},
        "rejected_plan_env_keys": rejected,
        "stdin": REDACTION,
        "timeout_seconds": plan.timeout_seconds,
        "max_output_bytes": plan.max_output_bytes,
        "max_error_bytes": plan.max_error_bytes,
    }


def _allowed_plan_env(
    plan_env: Mapping[str, str],
    allowed_plan_env_keys: tuple[str, ...],
) -> dict[str, str]:
    allowed = {key.upper() for key in allowed_plan_env_keys}
    return {
        key: value
        for key, value in plan_env.items()
        if key.upper() in allowed
    }


def _rejected_plan_env_keys(
    plan_env: Mapping[str, str],
    allowed_plan_env_keys: tuple[str, ...],
) -> list[str]:
    allowed = {key.upper() for key in allowed_plan_env_keys}
    return sorted(key for key in plan_env if key.upper() not in allowed)


def _build_result(
    plan: SqlclReadOnlyExecutionPlan,
    *,
    env: Mapping[str, str],
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool = False,
) -> SqlclRunnerResult:
    stdout_bytes = _byte_length(stdout)
    stderr_bytes = _byte_length(stderr)
    redacted_stdout = _redact_process_text(plan, env, stdout)
    redacted_stderr = _redact_process_text(plan, env, stderr)
    stdout_too_large = stdout_bytes > plan.max_output_bytes
    stderr_too_large = stderr_bytes > plan.max_error_bytes

    return SqlclRunnerResult(
        returncode=returncode,
        stdout=_bound_utf8_text(redacted_stdout, plan.max_output_bytes),
        stderr=_bound_utf8_text(redacted_stderr, plan.max_error_bytes),
        timed_out=timed_out,
        stdout_too_large=stdout_too_large,
        stderr_too_large=stderr_too_large,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        command=tuple(plan.command),
        env_keys=tuple(sorted(env)),
        timeout_seconds=plan.timeout_seconds,
    )


def _build_subprocess_result(
    request: SqlclSubprocessRequest,
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool = False,
) -> SqlclRunnerResult:
    stdout_bytes = _byte_length(stdout)
    stderr_bytes = _byte_length(stderr)
    redacted_stdout = _redact_sensitive_process_text(
        stdout,
        env=request.env,
        sensitive_values=request.sensitive_values,
    )
    redacted_stderr = _redact_sensitive_process_text(
        stderr,
        env=request.env,
        sensitive_values=request.sensitive_values,
    )
    stdout_too_large = stdout_bytes > request.max_output_bytes
    stderr_too_large = stderr_bytes > request.max_error_bytes
    return SqlclRunnerResult(
        returncode=returncode,
        stdout=_bound_utf8_text(redacted_stdout, request.max_output_bytes),
        stderr=_bound_utf8_text(redacted_stderr, request.max_error_bytes),
        timed_out=timed_out,
        stdout_too_large=stdout_too_large,
        stderr_too_large=stderr_too_large,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        command=tuple(request.command),
        env_keys=tuple(sorted(request.env)),
        timeout_seconds=request.timeout_seconds,
    )


def _redact_process_text(
    plan: SqlclReadOnlyExecutionPlan,
    env: Mapping[str, str],
    text: str,
) -> str:
    redacted = plan.redact_text(text)
    for key, value in env.items():
        if value and len(value) >= 4 and _is_sensitive_env_key(key):
            redacted = redacted.replace(value, REDACTION)
    return redacted


def _redact_sensitive_process_text(
    text: str,
    *,
    env: Mapping[str, str],
    sensitive_values: tuple[str, ...],
) -> str:
    redacted = text
    for value in sensitive_values:
        if value and len(value) >= 4:
            redacted = redacted.replace(value, REDACTION)
    for key, value in env.items():
        if value and len(value) >= 4 and _is_sensitive_env_key(key):
            redacted = redacted.replace(value, REDACTION)
    return redacted


def _is_sensitive_env_key(key: str) -> bool:
    upper = key.upper()
    return any(
        part in upper
        for part in (
            "PASS",
            "PASSWORD",
            "SECRET",
            "TOKEN",
            "API_KEY",
            "PRIVATE_KEY",
            "WALLET",
            "DSN",
        )
    )


def _safe_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _append_runner_message(stderr: str, message: str) -> str:
    if not stderr:
        return message
    return f"{stderr}\n{message}"


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def _bound_utf8_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


__all__ = [
    "DEFAULT_ALLOWED_PLAN_ENV_KEYS",
    "SqlclRunnerResult",
    "SqlclSubprocessRequest",
    "SubprocessRunCallable",
    "build_redacted_sqlcl_runner_metadata",
    "run_sqlcl_plan",
    "run_sqlcl_subprocess",
]
