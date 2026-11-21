"use client";

import type { ReactNode } from "react";
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

/** One folded line that opens to `children`: the finished trace, and the running one once the numbers are in. */
function Folded({ line, children }: { line: ReactNode; children?: ReactNode }) {
  if (!children) return <div className="flex items-center gap-2 px-3 py-2">{line}</div>;
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left">
        {line}
        <ChevronRight className="ml-auto size-4 text-muted-foreground transition-transform duration-200 ease-out group-data-[state=open]:rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}

/** The streamed stages, each with the API's formatted elapsed time; the last one pulses while running. */
function StageList({ run, running }: { run: Run; running: boolean }) {
  return (
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
  );
}

/** The pipeline's stages as they stream in, each with the API's formatted elapsed time, then one line from the
 * bundle's footprint. Once the numbers arrive (a partial) it folds to that one line already, still naming the stage
 * in progress, so the answer under it does not move when the result lands. The browser never formats a number. */
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
        <Folded line={line}>
          {stages.length > 0 && (
            // label | timing bar (width = the API's share of the total, grows in) | the API's formatted time
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
          )}
        </Folded>
      </div>
    );
  }

  const running = run.status === "running";
  if (running && run.partial) {
    const now = run.stages.at(-1);
    const line = (
      <>
        {pulse}
        <span>Trace</span>
        <span className="font-mono text-xs text-muted-foreground">
          {now ? `${stageLabel(now.name)} · ${now.elapsed}` : "Running the pipeline"}
        </span>
      </>
    );
    return (
      <div data-testid="trace" data-stage-times={JSON.stringify(times)} className={box} aria-busy>
        <Folded line={line}>{run.stages.length > 0 && <StageList run={run} running />}</Folded>
      </div>
    );
  }

  return (
    <div data-testid="trace" data-stage-times={JSON.stringify(times)} className={box} aria-busy={running}>
      <div className="flex items-center gap-2 px-3 py-2 text-muted-foreground">
        {!running && <CircleX className="size-4" />}
        <span>Trace</span>
        <span className="ml-auto" role="status">
          {running ? "Running the pipeline" : "Stopped"}
        </span>
      </div>
      <StageList run={run} running={running} />
    </div>
  );
}
