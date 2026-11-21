"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSherpa } from "@/lib/store";

/** The question box and Ask, on frosted glass; a thin indeterminate bar runs along its foot while a question is
 * in flight. Empty questions are dropped by the store's ask(). */
export function QuestionBar() {
  const { draft, setDraft, ask, run } = useSherpa();
  return (
    <form
      className="sticky top-0 z-10 flex gap-2.5 border-b bg-background/75 px-4 py-3 backdrop-blur-md md:px-5"
      onSubmit={(e) => {
        e.preventDefault();
        void ask(draft);
      }}
    >
      <Input
        data-testid="question"
        aria-label="Question"
        value={draft}
        maxLength={500}
        placeholder="Ask about payments, e.g. Why did success rate drop last week?"
        className="h-9 bg-card"
        onChange={(e) => setDraft(e.target.value)}
      />
      <Button type="submit" data-testid="ask-button" className="h-9 px-3.5">
        Ask
        <kbd aria-hidden className="font-mono text-[11px] opacity-85">
          ↵
        </kbd>
      </Button>
      {run.status === "running" && (
        <div
          role="progressbar"
          aria-label="Answering"
          data-testid="run-progress"
          className="absolute inset-x-0 -bottom-px h-0.5 overflow-hidden"
        >
          {/* reduced motion: a still, full-width bar instead of the sweep */}
          <div className="h-full w-1/3 animate-indeterminate rounded-full bg-accent-blue motion-reduce:w-full motion-reduce:opacity-60" />
        </div>
      )}
    </form>
  );
}
