"use client";

import { SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

// Run status as a dot; the status is also in the button's name, so never colour alone.
const DOT: Record<string, string> = {
  answered: "bg-positive",
  clarify: "bg-warning",
  refused: "bg-muted-foreground",
  error: "bg-negative",
};

/** The persona's last 8 reopenable runs, under the nav. Hidden when there are none or the run log is unavailable. */
export function RecentRuns() {
  const { history, openRun, run } = useSherpa();
  if (history.length === 0) return null;
  const open = run.status === "done" ? run.result?.bundle.run_id : undefined;
  return (
    <SidebarGroup data-testid="recent" className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Recent</SidebarGroupLabel>
      <SidebarMenu>
        {history.slice(0, 8).map((h) => (
          <SidebarMenuItem key={h.run_id}>
            <SidebarMenuButton
              size="sm"
              data-testid="recent-run"
              data-run-id={h.run_id}
              isActive={h.run_id === open}
              title={`${h.question} · ${h.status} · ${h.asked_at}`}
              onClick={() => void openRun(h.run_id)}
            >
              <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT[h.status] ?? "bg-muted-foreground")} />
              <span className="sr-only">{h.status}: </span>
              <span>{h.question}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
