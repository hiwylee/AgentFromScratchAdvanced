// Structured error parsing for workflow and agent results.
// Replaces fragile string matching with explicit error codes.

import type { StructuredError } from "./types";

const ERROR_CODE_MAP: Record<string, Partial<Omit<StructuredError, "code" | "message" | "isKnown">>> = {
  unsupported_workflow: {
    supported: ["patent_asset_replacement_registration"],
  },
  step_failed:     {},
  approval_denied: {},
  timeout:         {},
  plan_aborted:    {},
  tool_error:      {},
  policy_denied:   {},
};

// Known error substrings → code (fallback when error_code field is absent).
const ERROR_SUBSTRING_MAP: Array<[string, string]> = [
  ["unsupported_workflow", "unsupported_workflow"],
  ["approval_denied",      "approval_denied"],
  ["plan_aborted",         "plan_aborted"],
  ["step_failed",          "step_failed"],
  ["timed_out",            "timeout"],
  ["timeout",              "timeout"],
];

export function parseError(result: {
  error?: string;
  error_code?: string;
  step?: string;
}): StructuredError | null {
  if (!result.error && !result.error_code) return null;

  // 1. Prefer explicit error_code field
  if (result.error_code && ERROR_CODE_MAP[result.error_code] !== undefined) {
    return {
      code: result.error_code,
      message: result.error ?? result.error_code,
      step: result.step,
      ...ERROR_CODE_MAP[result.error_code],
      isKnown: true,
    };
  }

  // 2. Fallback: scan error string for known substrings
  if (result.error) {
    for (const [substr, code] of ERROR_SUBSTRING_MAP) {
      if (result.error.includes(substr)) {
        return {
          code,
          message: result.error,
          step: result.step,
          ...ERROR_CODE_MAP[code],
          isKnown: true,
        };
      }
    }
    // 3. Completely unknown error
    return {
      code: "unknown",
      message: result.error,
      step: result.step,
      isKnown: false,
    };
  }

  return null;
}
