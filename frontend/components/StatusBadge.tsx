import { cn } from "@/lib/utils";

type Status = "running" | "completed" | "failed" | "timed_out" | "pending" | "unknown" | string;

const statusConfig: Record<string, { label: string; dot: string; bg: string; text: string }> = {
  running: {
    label: "Running",
    dot: "bg-[oklch(0.75_0.18_200)] animate-pulse",
    bg: "bg-[oklch(0.65_0.22_200/0.12)] border-[oklch(0.65_0.22_200/0.3)]",
    text: "text-[oklch(0.75_0.18_200)]",
  },
  completed: {
    label: "Completed",
    dot: "bg-[oklch(0.70_0.18_145)]",
    bg: "bg-[oklch(0.60_0.18_145/0.12)] border-[oklch(0.60_0.18_145/0.3)]",
    text: "text-[oklch(0.70_0.18_145)]",
  },
  failed: {
    label: "Failed",
    dot: "bg-[oklch(0.65_0.22_25)]",
    bg: "bg-[oklch(0.55_0.22_25/0.12)] border-[oklch(0.55_0.22_25/0.3)]",
    text: "text-[oklch(0.65_0.22_25)]",
  },
  timed_out: {
    label: "Timed Out",
    dot: "bg-[oklch(0.80_0.18_80)]",
    bg: "bg-[oklch(0.70_0.18_80/0.12)] border-[oklch(0.70_0.18_80/0.3)]",
    text: "text-[oklch(0.80_0.18_80)]",
  },
  pending: {
    label: "Pending",
    dot: "bg-[oklch(0.55_0.02_260)]",
    bg: "bg-[oklch(0.45_0.02_260/0.12)] border-[oklch(0.45_0.02_260/0.3)]",
    text: "text-[oklch(0.65_0.02_260)]",
  },
};

export function StatusBadge({ status }: { status: Status }) {
  const config = statusConfig[status] ?? {
    label: status,
    dot: "bg-muted-foreground",
    bg: "bg-muted/30 border-border",
    text: "text-muted-foreground",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border font-mono",
        config.bg,
        config.text
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", config.dot)} />
      {config.label}
    </span>
  );
}
