"use client";

import { Suspense, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

import { Chips } from "@/components/ask/chips";
import { QuestionBar } from "@/components/ask/question-bar";
import { AnswerView, Banner, StatusFallback } from "@/components/answer/answer-view";
import { Trace } from "@/components/answer/trace";
import { Workspace } from "@/components/shell/workspace";
import { useSherpa } from "@/lib/store";

/** `/?q=…&persona=…&fixture=…` asks once, after meta has loaded; an unknown persona is ignored. */
function DeepLink() {
  const params = useSearchParams();
  const { meta, ask, setPersona } = useSherpa();
  const done = useRef(false);
  useEffect(() => {
    const q = params.get("q");
    if (done.current || !meta || !q) return;
    done.current = true;
    const p = params.get("persona");
    const persona = meta.personas.some((x) => x.key === p) ? (p as string) : undefined;
    if (persona) setPersona(persona);
    void ask(q.slice(0, 500), { persona, fixture: params.get("fixture") ?? undefined });
  }, [params, meta, ask, setPersona]);
  return null;
}

function Center() {
  const { metaError, run } = useSherpa();
  const result = run.status === "done" ? run.result : undefined;
  return (
    <>
      <QuestionBar />
      <div className="mx-auto grid w-full max-w-[760px] gap-3.5 px-4 pt-4 pb-16 md:px-6">
        <h1 className="sr-only">Ask</h1>
        {metaError && (
          <Banner tone="error" data-testid="meta-error">
            {metaError}. Personas and example questions did not load; Ask tries again.
          </Banner>
        )}
        <Chips />
        {run.status !== "idle" && <Trace run={run} />}
        {run.status === "failed" && (
          <Banner tone="error" role="alert" data-testid="error-card">
            <b className="font-semibold">No answer.</b> {run.error}
            {run.question && <p className="mt-1 text-muted-foreground">Question: {run.question}</p>}
          </Banner>
        )}
        {result &&
          (result.bundle.status === "answered" ? (
            <AnswerView bundle={result.bundle} view={result.view} />
          ) : (
            <StatusFallback bundle={result.bundle} />
          ))}
      </div>
    </>
  );
}

export default function AskPage() {
  const { railOpen, setRailOpen } = useSherpa();
  return (
    <>
      <Suspense fallback={null}>
        <DeepLink />
      </Suspense>
      <Workspace
        railTitle="Inspector"
        railOpen={railOpen}
        onRailOpenChange={setRailOpen}
        center={<Center />}
        rail={<p className="p-4 text-sm text-muted-foreground">The plan, evidence and footprints of an answer show here.</p>}
      />
    </>
  );
}
