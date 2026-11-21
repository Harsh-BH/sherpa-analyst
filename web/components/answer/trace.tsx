"use client";

import { ChevronRight, CircleCheck, CircleX } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Run } from "@/lib/store";
import { cn } from "@/lib/utils";

const STAGE_LABELS: Record<string, string> = {
  plan: "Plan",
  triage: "Triage",
  analysis: "Analysis",
  dq: "Data-quality checks",
  narrate: "Narration",
  check: "Claim check",
};
export const stageLabel = (name: string) => STAGE_LABELS[name] ?? name;

/** The stage in progress: an accent dot with a ping around it (an in-progress indicator, so it may loop). */
const pulse = (
  <span aria-hidden data-testid="stage-pulse" className="relative flex size-4 shrink-0 items-center justify-center">
    <span className="absolute size-2.5 animate-ping rounded-full bg-accent-blue/50" />
    <span className="size-2 rounded-full bg-accent-blue" />
  </span>
);

/** The pipeline's stages as they stream in, each with the API's formatted elapsed time, then one line from the
 * bundle's footprint. The browser never formats a number. */
export function Trace({ run }: { run: Run }) {
  const times = [...run.stages.map((s) => [s.name, s.at]), ...(run.resultAt === undefined ? [] : [["result", run.resultAt]])];
  const box = "rounded-xl border bg-card text-[13px] shadow-sm";

  if (run.status === "done" && run.result) {
    const { summary, stages } = run.result.view.footprint;
    const line = (
      <>
        <CircleCheck className={cn("size-4", run.result.bundle.status === "answered" ? "text-positive" : "text-muted-foreground")} />
        <span>Trace</span>
        <span className="font-mono text-xs text-muted-foreground">{summary || "done"}</span>
      </>
    );
    return (
      <div data-testid="trace" data-stage-times={JSON.stringify(times)} className={box}>
        {stages.length === 0 ? (
          <div className="flex items-center gap-2 px-3 py-2">{line}</div>
        ) : (
          <Collapsible>
            <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left">
              {line}
              <ChevronRight className="ml-auto size-4 text-muted-foreground transition-transform duration-200 ease-out group-data-[state=open]:rotate-90" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              {/* label | timing bar (width = the API's share of the total, grows in) | the API's formatted time */}
              <ul className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 border-t px-3 py-2">
                {stages.map((s, i) => (
                  <li key={s.label} data-testid="trace-stage" className="col-span-3 grid grid-cols-subgrid items-center">
                    <span>{stageLabel(s.label)}</span>
                    <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-muted">
                      {s.fraction != null && (
                        <span
                          data-testid="stage-bar"
                          style={{ width: `${s.fraction * 100}%`, animationDelay: `${i * 50}ms` }}
                          className="block h-full origin-left animate-grow rounded-full bg-accent-blue"
                        />
                      )}
                    </span>
                    <span className="text-right font-mono text-xs text-muted-foreground">{s.value}</span>
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    );
  }

  const running = run.status === "running";
  return (
    <div data-testid="trace" data-stage-times={JSON.stringify(times)} className={box} aria-busy={running}>
      <div className="flex items-center gap-2 px-3 py-2 text-muted-foreground">
        {!running && <CircleX className="size-4" />}
        <span>Trace</span>
        <span className="ml-auto" role="status">
          {running ? "Running the pipeline" : "Stopped"}
        </span>
      </div>
      <ul className="grid gap-1 border-t px-3 py-2 empty:hidden">
        {run.stages.map((s, i) => {
          const current = running && i === run.stages.length - 1;
          return (
            <li key={`${s.name}-${i}`} className="flex items-center gap-2">
              {current ? pulse : <CircleCheck className="size-4 shrink-0 animate-pop text-positive" />}
              {stageLabel(s.name)}
              <span className="ml-auto font-mono text-xs text-muted-foreground">{s.elapsed}</span>
            </li>
          );
        })}
        {running && run.stages.length === 0 && (
          <li className="flex items-center gap-2 text-muted-foreground">
            {pulse}
            Waiting for the first stage
          </li>
        )}
      </ul>
    </div>
  );
}
