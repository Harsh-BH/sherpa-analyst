"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSherpa } from "@/lib/store";

/** The question box and Ask. Empty questions are dropped by the store's ask(). */
export function QuestionBar() {
  const { draft, setDraft, ask } = useSherpa();
  return (
    <form
      className="sticky top-0 z-10 flex gap-2.5 border-b bg-background px-4 py-3 md:px-5"
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
        <kbd aria-hidden className="font-mono text-[11px] opacity-70">
          ↵
        </kbd>
      </Button>
    </form>
  );
}
