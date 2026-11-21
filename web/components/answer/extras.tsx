"use client";

import { useState, type CSSProperties } from "react";
import { ArrowDownRight, ArrowUpRight, Check, Copy } from "lucide-react";

import { chip } from "@/components/ask/chips";
import { Button } from "@/components/ui/button";
import type { View } from "@/lib/api";
import { useSherpa } from "@/lib/store";
import { cn } from "@/lib/utils";

type Part = View["headline_parts"][number];

const TONE = {
  positive: "bg-positive/10 text-positive",
  negative: "bg-negative/10 text-negative",
  neutral: "bg-muted text-foreground",
};

/** The headline with its numbers as chips: values subtle, signed deltas coloured by whether the move is good for
 * the metric, with an arrow. Spans and an aria-hidden icon only, so it reads as the same sentence. */
export function HeadlineText({ text, parts }: { text: string; parts: Part[] }) {
  if (!parts.length) return text;
  return parts.map((p, i) => {
    if (p.kind === "text") return p.text;
    const Arrow = p.kind === "up" ? ArrowUpRight : p.kind === "down" ? ArrowDownRight : null;
    return (
      <span
        key={i}
        data-kind={p.kind}
        data-tone={p.tone}
        className={cn(
          "rounded-md px-1 tabular-nums box-decoration-clone whitespace-nowrap",
          Arrow ? TONE[p.tone] : "bg-muted",
        )}
      >
        {Arrow && <Arrow aria-hidden className="mr-px inline size-[0.8em] align-[-0.05em]" />}
        {p.text}
      </span>
    );
  });
}

/** Copies view.markdown (the answer, built in Python) and says so for 1.5 s. */
export function CopyAnswer({ markdown }: { markdown: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setState("copied");
    } catch {
      setState("failed"); // no clipboard permission, or not a secure context
    }
    setTimeout(() => setState("idle"), 1500);
  };
  return (
    <Button variant="outline" size="sm" data-testid="copy-answer" className="ml-auto" onClick={copy}>
      {state === "copied" ? <Check /> : <Copy />}
      <span aria-live="polite">{{ idle: "Copy answer", copied: "Copied", failed: "Copy failed" }[state]}</span>
    </Button>
  );
}

/** "Ask next": follow-ups built in Python; each is asked with the plan it was built with, so it skips the planner. */
export function FollowUps({ items }: { items: View["follow_ups"] }) {
  const { ask } = useSherpa();
  if (!items.length) return null;
  return (
    <section className="grid gap-1.5">
      <h3 className="section-label">Ask next</h3>
      <div className="flex flex-wrap gap-1.5">
        {items.map((f, i) => (
          <button
            key={f.question}
            type="button"
            data-testid="follow-up"
            title={f.question}
            style={{ "--i": i } as CSSProperties}
            className={chip}
            onClick={() => void ask(f.question, { plan: f.plan })}
          >
            {f.label}
          </button>
        ))}
      </div>
    </section>
  );
}
