"use client";

import { Suspense, useEffect, useRef, useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";

import { Chips } from "@/components/ask/chips";
import { Overview } from "@/components/ask/overview";
import { QuestionBar } from "@/components/ask/question-bar";
import { Banner, BundleView } from "@/components/answer/answer-view";
import { Trace } from "@/components/answer/trace";
import { AnswerRail } from "@/components/rail/answer-rail";
import { HomeRail } from "@/components/rail/home-rail";
import { Workspace } from "@/components/shell/workspace";
import { useSherpa, type Run } from "@/lib/store";

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

/** `/?run=<id>` reopens that saved run, once, as soon as the persona is known (the API scopes runs to it). */
function RunLink() {
  const params = useSearchParams();
  const { persona, openRun } = useSherpa();
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !persona) return;
    done.current = true; // later ?run= changes are openRun's own replaceState
    const id = params.get("run");
    if (id) void openRun(id);
  }, [params, persona, openRun]);
  return null;
}

const noEvents = () => () => {};
/** `/?run=<id>` that openRun has not loaded yet: home's overview and rail stay out, so they neither flash nor fetch.
 * Read from the URL on each render (no event fires for replaceState); the server and hydration say no. */
function useOpening(run: Run) {
  const linked = useSyncExternalStore(noEvents, () => new URLSearchParams(window.location.search).has("run"), () => false);
  return linked && run.status === "idle";
}

/** The finished answer, or while running the numbers that arrived before its narrative. */
const shown = (run: Run) => (run.status === "done" ? run.result : run.status === "running" ? run.partial : undefined);

function Center() {
  const { metaError, run } = useSherpa();
  const result = shown(run);
  const opening = useOpening(run);
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
        {run.status === "idle" && !opening && <Overview />}
        <Chips />
        {run.status !== "idle" && <Trace run={run} />}
        {run.status === "failed" && (
          <Banner tone="error" role="alert" data-testid="error-card">
            <b className="font-semibold">No answer.</b> {run.error}
            {run.question && <p className="mt-1 text-muted-foreground">Question: {run.question}</p>}
          </Banner>
        )}
        {result && <BundleView bundle={result.bundle} view={result.view} feedback={result.feedback} />}
      </div>
    </>
  );
}

export default function AskPage() {
  const { run, railOpen, setRailOpen } = useSherpa();
  const result = shown(run);
  const opening = useOpening(run);
  return (
    <>
      <Suspense fallback={null}>
        <DeepLink />
        <RunLink />
      </Suspense>
      <Workspace
        railTitle="Inspector"
        railOpen={railOpen}
        onRailOpenChange={setRailOpen}
        center={<Center />}
        rail={
          result ? <AnswerRail bundle={result.bundle} view={result.view} /> : opening ? null : <HomeRail />
        }
      />
    </>
  );
}
