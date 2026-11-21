"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Calculator, CircleAlert, Info, Route, ShieldCheck, TriangleAlert } from "lucide-react";

import { useAskFromHome } from "@/components/ask/overview";
import { Skeleton } from "@/components/ui/skeleton";
import { getDataHealth, getEval, type DataHealthResponse } from "@/lib/api";
import { useSherpa } from "@/lib/store";

const SEVERITY = {
  error: { Icon: CircleAlert, label: "Error", cls: "text-negative" },
  warn: { Icon: TriangleAlert, label: "Warning", cls: "text-warning" },
  info: { Icon: Info, label: "Note", cls: "text-muted-foreground" },
};

const STEPS = [
  { Icon: Route, title: "1. Plan", text: "The question becomes a typed plan from the governed catalog." },
  {
    Icon: Calculator,
    title: "2. Compute",
    text: "The catalog compiles SQL that runs under your role, and code does the maths.",
  },
  {
    Icon: ShieldCheck,
    title: "3. Check",
    text: "Every number in the text is matched to an executed query, and the confidence is stated with reasons.",
  },
];

function DataHealth() {
  const { persona } = useSherpa();
  const askWhy = useAskFromHome();
  const [got, setGot] = useState<{ persona: string; data: DataHealthResponse | null } | null>(null);

  useEffect(() => {
    if (!persona) return;
    const c = new AbortController();
    getDataHealth(persona, c.signal).then(
      (data) => setGot({ persona, data }),
      () => c.signal.aborted || setGot({ persona, data: null }), // a failed call hides the section, like unavailable
    );
    return () => c.abort();
  }, [persona]);

  const data = persona && got?.persona === persona ? got.data : undefined;
  if (data === undefined)
    return (
      <div data-testid="data-health-loading" aria-hidden className="grid gap-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    );
  if (!data?.available) return null;
  return (
    <section data-testid="data-health" aria-labelledby="data-health-title" className="grid gap-1.5">
      <h3 id="data-health-title" className="section-label">
        Data health · last 30 days
      </h3>
      {data.issues.length === 0 ? (
        <p data-testid="data-health-empty" className="text-[13px] text-muted-foreground">
          No data-quality issues in the last 30 days
        </p>
      ) : (
        <ul className="-mx-2 grid">
          {data.issues.map((issue, i) => {
            const { Icon, label, cls } = SEVERITY[issue.severity];
            return (
              <li key={i}>
                <button
                  type="button"
                  data-testid="data-health-row"
                  data-severity={issue.severity}
                  onClick={() => askWhy(issue.question)}
                  className="group flex w-full gap-2.5 rounded-lg border border-transparent px-2 py-2 text-left transition-colors outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${cls}`} />
                  <span className="grid min-w-0 gap-0.5">
                    <span className="text-xs font-medium tabular-nums">
                      <span className="sr-only">{label}, </span>
                      {issue.when}
                    </span>
                    <span className="text-[13px] leading-snug">{issue.text}</span>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground group-hover:text-foreground">
                      <ArrowRight aria-hidden className="size-3 shrink-0" />
                      <span className="sr-only">Ask: </span>
                      {issue.question}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The Inspector rail when no answer is open: data health for the persona, how Sherpa answers, and the eval result. */
export function HomeRail() {
  const [proof, setProof] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    getEval().then(
      (e) => live && setProof(e.status === "ok" ? (e.proof ?? null) : null),
      () => {}, // no eval: the line stays hidden
    );
    return () => {
      live = false;
    };
  }, []);

  return (
    <div data-testid="home-rail" className="grid gap-6 p-4">
      <DataHealth />
      <section aria-labelledby="how-title" className="grid gap-2">
        <h3 id="how-title" className="section-label">
          How Sherpa answers
        </h3>
        <ol className="grid gap-2.5">
          {STEPS.map(({ Icon, title, text }) => (
            <li key={title} className="flex gap-2.5">
              <span className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
                <Icon aria-hidden className="size-4" />
              </span>
              <p className="text-[13px] leading-snug">
                <b className="font-medium">{title}.</b>{" "}
                <span className="text-muted-foreground">{text}</span>
              </p>
            </li>
          ))}
        </ol>
        {proof && (
          <Link
            href="/eval"
            data-testid="eval-proof"
            className="mt-1 inline-flex items-center gap-1 justify-self-start rounded-sm text-[13px] font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {proof}
            <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </section>
      <p className="text-[13px] text-muted-foreground">The plan, evidence and footprints of an answer show here.</p>
    </div>
  );
}
