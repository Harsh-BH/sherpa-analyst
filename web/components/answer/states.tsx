"use client";

import { useState, type ReactNode } from "react";
import { Check, CircleAlert, Copy, CornerDownRight, HelpCircle, Ban } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AnswerBundle } from "@/lib/api";
import { useSherpa } from "@/lib/store";

function Card({ icon, title, testid, children }: { icon: ReactNode; title: string; testid?: string; children: ReactNode }) {
  return (
    <section data-testid={testid} className="rise grid gap-3 rounded-xl border bg-card px-4 py-3.5 text-sm shadow-sm [&_svg]:size-4">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold">
        {icon}
        {title}
      </h2>
      {children}
    </section>
  );
}

/** The question was ambiguous: one button per reading, each re-asking with that option's plan patch. */
export function Clarification({ bundle }: { bundle: AnswerBundle }) {
  const { ask } = useSherpa();
  const c = bundle.clarification;
  if (!c) return null;
  return (
    <Card icon={<HelpCircle className="text-muted-foreground" />} title="One thing to confirm">
      <p className="wrap-anywhere">{c.question}</p>
      <p className="text-[13px] text-muted-foreground wrap-anywhere">Your question: {bundle.question}</p>
      <div className="grid gap-2">
        {c.options.map((o, i) => (
          <Button
            key={i}
            variant="outline"
            data-testid="clarify-option"
            disabled={!bundle.plan}
            className="h-auto justify-start py-2 text-left whitespace-normal wrap-anywhere"
            onClick={() => void ask(bundle.question, { plan: bundle.plan, patch: o.plan_patch, persona: bundle.persona })}
          >
            {o.label}
            {o.preview ? ` · ${o.preview}` : ""}
          </Button>
        ))}
      </div>
    </Card>
  );
}

/** Out of scope: the reason, what Sherpa can do instead, and a one-click way to get that. */
export function RefusalCard({ bundle }: { bundle: AnswerBundle }) {
  const { ask } = useSherpa();
  const r = bundle.refusal;
  if (!r) return null;
  const patch = r.plan_patch;
  return (
    <Card icon={<Ban className="text-muted-foreground" />} title="Not answered">
      <p className="wrap-anywhere">{r.reason}</p>
      {r.suggestion && <p className="text-muted-foreground wrap-anywhere">{r.suggestion}</p>}
      {patch && bundle.plan && (
        <Button
          data-testid="refusal-accept"
          className="justify-self-start"
          onClick={() => void ask(bundle.question, { plan: bundle.plan, patch, persona: bundle.persona })}
        >
          <CornerDownRight />
          Show me that instead
        </Button>
      )}
      <p className="font-mono text-xs text-muted-foreground wrap-anywhere">
        Run {bundle.run_id} · persona {bundle.persona}
      </p>
    </Card>
  );
}

/** The pipeline failed: what it said, the question, and the run id to quote. */
export function ErrorCard({ bundle }: { bundle: AnswerBundle }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(bundle.run_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {} // clipboard blocked: the id stays selectable text
  };
  return (
    <section
      role="alert"
      data-testid="error-card"
      className="rise grid gap-2 rounded-xl border border-negative/40 bg-negative/8 px-4 py-3.5 text-sm" // /8: AA for the red heading on the page bg
    >
      <h2 className="flex items-center gap-2 text-[15px] font-semibold text-negative">
        <CircleAlert className="size-4" />
        This run failed.
      </h2>
      <p className="wrap-anywhere">{bundle.error ?? "No error message was recorded."}</p>
      <p className="text-[13px] text-muted-foreground wrap-anywhere">Question: {bundle.question}</p>
      <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
        Run id
        <code className="font-mono text-xs text-foreground wrap-anywhere">{bundle.run_id}</code>
        <Button variant="ghost" size="icon-sm" aria-label="Copy run id" onClick={copy}>
          {copied ? <Check /> : <Copy />}
        </Button>
      </p>
    </section>
  );
}
