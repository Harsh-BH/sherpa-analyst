"use client";

import type { CSSProperties } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useSherpa } from "@/lib/store";

type Item = { question: string; persona: string | null };

/** A question chip (also the answer's "Ask next" chips); `--i` staggers its fade-in. */
export const chip =
  "max-w-full animate-in fade-in-0 rounded-full border bg-card px-2.5 py-1 text-left text-[13px] wrap-anywhere text-foreground shadow-xs transition-[color,border-color,box-shadow,translate,scale] duration-150 ease-out animation-duration-300 fill-mode-backwards [--tw-animation-delay:calc(var(--i)*30ms)] hover:-translate-y-px hover:border-accent-blue/60 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none active:scale-[0.98]";

function Row({ label, testId, items }: { label: string; testId: string; items: Item[] }) {
  const { meta, ask, setPersona } = useSherpa();
  const personaLabel = (key: string) => meta?.personas.find((p) => p.key === key)?.label ?? key;
  return (
    <div className="grid gap-1.5">
      <h2 className="section-label">{label}</h2>
      <div className="flex flex-wrap gap-1.5">
        {items.map(({ question, persona }, i) => (
          <button
            key={question}
            type="button"
            data-testid={testId}
            style={{ "--i": i } as CSSProperties}
            className={chip}
            onClick={() => {
              if (persona) setPersona(persona); // the refusal demo is asked as the South manager
              void ask(question, { persona: persona ?? undefined });
            }}
          >
            {question}
            {persona && <span className="text-muted-foreground"> · as {personaLabel(persona)}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Demo and verified questions from /api/meta. Open on the empty page, folded away once there is an answer. */
export function Chips() {
  const { meta, run } = useSherpa();
  if (!meta) return null;
  const rows = (
    <div className="grid gap-3">
      <Row label="Demo questions" testId="demo-chip" items={meta.demo} />
      <Row
        label="Verified questions (catalog)"
        testId="verified-chip"
        items={meta.verified.map((question) => ({ question, persona: null }))}
      />
    </div>
  );
  if (run.status === "idle") return rows;
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground">
        <ChevronRight className="size-4 transition-transform duration-200 ease-out group-data-[state=open]:rotate-90" />
        Example questions
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2">{rows}</CollapsibleContent>
    </Collapsible>
  );
}
