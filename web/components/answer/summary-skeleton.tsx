import { PenLine } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";

/** In the headline's place while the narrator writes it: the numbers around it are already the real ones. */
export function HeadlineSkeleton() {
  return (
    <div data-testid="summary-skeleton" className="mt-1 grid gap-2">
      <p role="status" className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
        <PenLine aria-hidden className="size-3.5" />
        Writing the summary…
      </p>
      <Skeleton className="h-6 w-[92%]" />
      <Skeleton className="h-6 w-3/5" />
    </div>
  );
}

const ROWS = ["w-[88%]", "w-[72%]", "w-[80%]", "w-[56%]"];

/** In the claims' place, shaped like their card so the result swaps in without the page jumping. */
export function ClaimsSkeleton() {
  return (
    <section aria-hidden className="grid gap-2">
      <h3 className="section-label">What the evidence says</h3>
      <ol className="overflow-hidden rounded-xl border bg-card shadow-sm">
        {ROWS.map((w) => (
          <li
            key={w}
            className="grid gap-x-3 gap-y-2 border-b px-3 py-2.5 last:border-b-0 sm:grid-cols-[124px_minmax(0,1fr)]"
          >
            <Skeleton className="h-3.5 w-20" />
            <div className="grid gap-2">
              <Skeleton className={`h-4 ${w}`} />
              <Skeleton className="h-5 w-9" />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
