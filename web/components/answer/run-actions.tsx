"use client";

import { useState } from "react";
import { Check, Link2, ThumbsDown, ThumbsUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { sendFeedback } from "@/lib/api";
import { cn } from "@/lib/utils";

const THUMBS = [
  { rating: 1, label: "Helpful", icon: ThumbsUp, testid: "feedback-up", on: "aria-pressed:bg-positive/10 aria-pressed:text-positive" },
  { rating: -1, label: "Not helpful", icon: ThumbsDown, testid: "feedback-down", on: "aria-pressed:bg-negative/10 aria-pressed:text-negative" },
] as const;

/** Copy a permalink to the run, and rate it. Key it by run id so a new answer starts unrated, and a reopened one
 * with its latest thumb (`rated`) pressed. The other thumb undoes a rating: the API keeps every rating and the latest
 * wins. */
export function RunActions({
  runId,
  persona,
  rated,
  className,
}: {
  runId: string;
  persona: string;
  rated?: "up" | "down" | null;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<1 | -1 | null>(rated === "up" ? 1 : rated === "down" ? -1 : null);
  const [note, setNote] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/?run=${encodeURIComponent(runId)}`);
      setCopied(true);
      setNote("Link copied");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setNote("Could not copy the link");
    }
  }

  async function rate(r: 1 | -1) {
    if (r === rating) return;
    const before = rating;
    setRating(r);
    setNote("");
    try {
      await sendFeedback(runId, persona, r);
      setNote("Thanks");
    } catch {
      setRating(before);
      setNote("Feedback was not saved");
    }
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      <Button variant="outline" size="sm" data-testid="copy-link" onClick={() => void copy()}>
        {copied ? <Check /> : <Link2 />}
        {copied ? "Copied" : "Copy link"}
      </Button>
      {THUMBS.map(({ rating: r, label, icon: Icon, testid, on }) => (
        <Button
          key={r}
          variant="ghost"
          size="icon-sm"
          aria-label={label}
          title={label}
          aria-pressed={rating === r}
          data-testid={testid}
          className={cn("text-muted-foreground", on)}
          onClick={() => void rate(r)}
        >
          <Icon />
        </Button>
      ))}
      <span role="status" data-testid="feedback-note" className="text-[12.5px] text-muted-foreground">
        {note}
      </span>
    </div>
  );
}
