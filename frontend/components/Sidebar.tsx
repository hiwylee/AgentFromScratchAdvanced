"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  MessageSquare,
  Activity,
  FileText,
  GitBranch,
  Database,
  Zap,
  Brain,
  Settings2,
} from "lucide-react";

const navItems = [
  {
    href: "/",
    label: "Chat",
    icon: MessageSquare,
    description: "Ask the agent",
  },
  {
    href: "/status",
    label: "Run Status",
    icon: Activity,
    description: "Live monitoring",
  },
  {
    href: "/audit",
    label: "Audit Log",
    icon: FileText,
    description: "Event history",
  },
  {
    href: "/workflow",
    label: "Workflow",
    icon: GitBranch,
    description: "State machine runner",
  },
  {
    href: "/schema",
    label: "Schema Inspector",
    icon: Database,
    description: "Oracle ADW context",
  },
  {
    href: "/memory",
    label: "Memory",
    icon: Brain,
    description: "Session memory manager",
  },
  {
    href: "/operator",
    label: "Operator",
    icon: Settings2,
    description: "ADW tools & config",
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 flex-shrink-0 flex flex-col border-r border-border/50 bg-sidebar">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border/50">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md flex items-center justify-center bg-gradient-to-br from-[oklch(0.72_0.19_280)] to-[oklch(0.65_0.22_200)] glow-purple">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-xs font-bold tracking-wider text-foreground">
              AGENT<span className="gradient-text">FS</span>
            </div>
            <div className="text-[10px] text-muted-foreground tracking-widest uppercase">
              Runtime Console
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all duration-150 group",
                isActive
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
              )}
            >
              <Icon
                className={cn(
                  "w-4 h-4 flex-shrink-0 transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
                )}
              />
              <div className="min-w-0">
                <div className={cn("font-medium truncate", isActive && "text-primary")}>
                  {item.label}
                </div>
                <div className="text-[10px] text-muted-foreground/70 truncate">
                  {item.description}
                </div>
              </div>
              {isActive && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary pulse-glow flex-shrink-0" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border/50">
        <div className="text-[10px] text-muted-foreground/50 font-mono">
          AgentFromScratch v0.1
        </div>
        <div className="text-[10px] text-muted-foreground/30 font-mono">
          Python 3.13 · uv runtime
        </div>
      </div>
    </aside>
  );
}
