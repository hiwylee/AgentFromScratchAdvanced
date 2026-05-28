// Dynamic audit event color assignment.
// Known events get fixed OKLch colors; unknown events get a deterministic hash-based color.

type ColorToken = "cyan" | "green" | "red" | "purple" | "amber" | "blue" | "violet" | "orange";

const PALETTE: ColorToken[] = ["cyan", "green", "red", "purple", "amber", "blue", "violet", "orange"];

const COLOR_CLASSES: Record<ColorToken, string> = {
  cyan:   "text-[oklch(0.75_0.18_200)] bg-[oklch(0.65_0.22_200/0.1)] border-[oklch(0.65_0.22_200/0.3)]",
  green:  "text-[oklch(0.75_0.15_145)] bg-[oklch(0.60_0.18_145/0.1)] border-[oklch(0.60_0.18_145/0.3)]",
  red:    "text-[oklch(0.70_0.20_25)]  bg-[oklch(0.55_0.22_25/0.1)]  border-[oklch(0.55_0.22_25/0.3)]",
  purple: "text-[oklch(0.75_0.17_280)] bg-[oklch(0.72_0.19_280/0.1)] border-[oklch(0.72_0.19_280/0.3)]",
  amber:  "text-[oklch(0.82_0.16_80)]  bg-[oklch(0.70_0.18_80/0.1)]  border-[oklch(0.70_0.18_80/0.3)]",
  blue:   "text-[oklch(0.72_0.18_240)] bg-[oklch(0.65_0.20_240/0.1)] border-[oklch(0.65_0.20_240/0.3)]",
  violet: "text-[oklch(0.75_0.18_290)] bg-[oklch(0.72_0.19_290/0.1)] border-[oklch(0.72_0.19_290/0.3)]",
  orange: "text-[oklch(0.78_0.18_55)]  bg-[oklch(0.70_0.18_55/0.1)]  border-[oklch(0.70_0.18_55/0.3)]",
};

const EVENT_CATEGORY: Record<string, ColorToken> = {
  run_started:        "cyan",
  run_completed:      "green",
  run_failed:         "red",
  action_executed:    "purple",
  schema_inspected:   "blue",
  answer_evaluated:   "amber",    // P9
  session_summarized: "violet",   // P10
  intent_analyzed:    "cyan",
  parse_error:        "orange",
  tool_completed:     "green",
  tool_failed:        "red",
  memory_injected:    "violet",
  plan_shadow_recorded: "blue",
};

function hashColor(event: string): ColorToken {
  let h = 0;
  for (let i = 0; i < event.length; i++) {
    h = (h * 31 + event.charCodeAt(i)) | 0;
  }
  return PALETTE[(h >>> 0) % PALETTE.length];
}

export function getEventClasses(event?: string): string {
  if (!event) return "text-muted-foreground bg-muted/20 border-border/30";
  const color = EVENT_CATEGORY[event] ?? hashColor(event);
  return COLOR_CLASSES[color];
}

export function getEventCategory(event?: string): ColorToken | "unknown" {
  if (!event) return "unknown";
  return EVENT_CATEGORY[event] ?? hashColor(event);
}
