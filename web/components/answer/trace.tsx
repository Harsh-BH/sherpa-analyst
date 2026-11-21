"use client";

import { ChevronRight, CircleCheck, CircleX, LoaderCircle } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Run } from "@/lib/store";

const STAGE_LABELS: Record<string, string> = {
  plan: "Plan",
  triage: "Triage",
  analysis: "Analysis",
  dq: "Data-quality checks",
  narrate: "Narration",
  check: "Claim check",
};
export const stageLabel = (name: string) => STAGE_LABELS[name] ?? name;

/** The pipeline's stages as they stream in, each with the API's formatted elapsed time, then one line from the
 * bundle's footprint. The browser never formats a number. */
export function Trace({ run }: { run: Run }) {
  const times = [...run.stages.map((s) => [s.name, s.at]), ...(run.resultAt === undefined ? [] : [["result", run.resultAt]])];
  const box = "rounded-lg border bg-card text-[13px]";

  if (run.status === "done" && run.result) {
    const { summary, stages } = run.result.view.footprint;
    const line = (
      <>
        <CircleCheck className="size-4 text-muted-foreground" />
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
              <ChevronRight className="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="grid gap-1 border-t px-3 py-2">
                {stages.map((s) => (
                  <li key={s.label} className="flex justify-between gap-3">
                    <span>{stageLabel(s.label)}</span>
                    <span className="font-mono text-xs text-muted-foreground">{s.value}</span>
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
              {current ? (
                <LoaderCircle className="size-4 animate-spin text-muted-foreground motion-reduce:animate-none" />
              ) : (
                <CircleCheck className="size-4 text-muted-foreground" />
              )}
              {stageLabel(s.name)}
              <span className="ml-auto font-mono text-xs text-muted-foreground">{s.elapsed}</span>
            </li>
          );
        })}
        {running && run.stages.length === 0 && (
          <li className="flex items-center gap-2 text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            Waiting for the first stage
          </li>
        )}
      </ul>
    </div>
  );
}
