"use client";

import { useState, type ComponentProps } from "react";
import { ChevronRight, CircleAlert, Download, Gauge, Info, ShieldCheck, TriangleAlert } from "lucide-react";

import { Claims } from "@/components/answer/claims";
import { Drivers } from "@/components/answer/drivers";
import { CopyAnswer, FollowUps, HeadlineText } from "@/components/answer/extras";
import { KeyChart } from "@/components/answer/key-chart";
import { Recon } from "@/components/answer/recon";
import { RunActions } from "@/components/answer/run-actions";
import { Clarification, ErrorCard, RefusalCard } from "@/components/answer/states";
import { ClaimsSkeleton, HeadlineSkeleton } from "@/components/answer/summary-skeleton";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { AnswerBundle, AskResult, View } from "@/lib/api";
import { cn } from "@/lib/utils";

type Feedback = AskResult["feedback"];

const TONES = {
  error: { icon: CircleAlert, cls: "bg-negative/10 [&>svg]:text-negative" },
  warn: { icon: TriangleAlert, cls: "bg-warning/12 [&>svg]:text-warning" },
  info: { icon: Info, cls: "bg-muted [&>svg]:text-muted-foreground" },
};

/** A tinted strip with a severity icon: data quality, the unverified-SQL warning, and errors. */
export function Banner({ tone, className, children, ...props }: { tone: keyof typeof TONES } & ComponentProps<"div">) {
  const { icon: Icon, cls } = TONES[tone];
  return (
    <div className={cn("flex items-start gap-2.5 rounded-md px-3.5 py-2.5 text-[13.5px]", cls, className)} {...props}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 wrap-anywhere">{children}</div>
    </div>
  );
}

const CONFIDENCE = {
  high: { label: "High", cls: "bg-positive/10 text-positive" },
  medium: { label: "Medium", cls: "bg-warning/12 text-warning" },
  low: { label: "Low", cls: "bg-negative/8 text-negative" }, // /8: /10 over the page bg is 4.48:1
};
const pill = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12.5px] font-medium [&>svg]:size-3.5";

/** `sherpa-run-<run id>`, keeping only the run id's safe characters: the bundle and chart download names. */
export const fileName = (runId: string) => `sherpa-run-${runId.replace(/[^A-Za-z0-9_.-]/g, "_")}`;

/** Save the bundle as JSON; the file name keeps only safe characters of the run id. */
export function download(bundle: AnswerBundle) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${fileName(bundle.run_id)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url));
}

/** An answered bundle, in the spec's order: data quality first, never folded away. A partial view (the numbers before
 * the narrative) draws the same tree with skeletons for the headline and claims, and room kept for the action buttons,
 * the footprint's last items and the confidence reasons, so the result swaps in without the page jumping or the charts
 * redrawing: only the headline and claims (`data-swap-in`) animate in. */
export function AnswerView({ bundle, view, feedback }: { bundle: AnswerBundle; view: View; feedback?: Feedback }) {
  const [fromPartial] = useState(view.partial); // mounted as a partial: the result is a swap, not a fresh answer
  const conf = bundle.confidence ? CONFIDENCE[bundle.confidence] : null;
  const assumptions = bundle.plan?.assumptions ?? [];
  // the swap target's height on a phone or touch screen, where its buttons are 40 px tap targets
  const tall = "max-md:min-h-10 pointer-coarse:min-h-10";
  return (
    // stagger: each section fades in and rises, 50 ms after the one before
    <article className={cn("stagger grid gap-3.5", fromPartial && !view.partial && "stagger-swap")}>
      {bundle.dq.map((w, i) => (
        <Banner key={i} tone={w.severity} data-testid="dq-banner">
          <b className="font-semibold">Data quality · {w.check.replaceAll("_", " ")}:</b> {w.message}
        </Banner>
      ))}
      {view.partial ? (
        <HeadlineSkeleton />
      ) : (
        <h2
          data-testid="headline"
          data-swap-in
          className="mt-1 text-[22px] leading-[1.3] font-semibold tracking-tight text-balance wrap-anywhere"
        >
          {bundle.headline ? (
            <HeadlineText text={bundle.headline} parts={view.headline_parts} />
          ) : (
            "No headline was produced."
          )}
        </h2>
      )}
      <div className={cn("flex min-h-8 flex-wrap items-center gap-2", tall)}>
        {conf && (
          <span data-testid="badge-confidence" className={cn(pill, conf.cls)}>
            <Gauge />
            {conf.label} confidence
          </span>
        )}
        {/* Hue is allowed here: the sql route caps confidence at medium, so it is a confidence signal (spec, hue rule). */}
        {bundle.route === "sql" && (
          <span data-testid="badge-route" className={cn(pill, "bg-warning/12 text-warning")}>
            <TriangleAlert />
            Unverified SQL
          </span>
        )}
        {bundle.route === "catalog" && (
          <span data-testid="badge-route" className={cn(pill, "bg-secondary text-secondary-foreground")}>
            <ShieldCheck />
            Governed metric
          </span>
        )}
        {!view.partial && (
          <>
            <CopyAnswer markdown={view.markdown} />
            <RunActions key={bundle.run_id} runId={bundle.run_id} persona={bundle.persona} rated={feedback} />
          </>
        )}
      </div>
      {bundle.route === "sql" && (
        <Banner tone="warn" data-testid="sql-warning">
          <b className="font-semibold">Unverified SQL.</b> The model wrote this query; it passed the guard but is not a
          governed metric, so confidence is capped at medium. Check the SQL in the evidence.
        </Banner>
      )}
      <p data-testid="footprint-line" className="font-mono text-xs text-muted-foreground wrap-anywhere">
        {view.footprint.items.map((kv, i) => (
          <span key={kv.label}>
            {i > 0 && " · "}
            {kv.label.toLowerCase()} <span className="text-foreground">{kv.value}</span>
          </span>
        ))}
      </p>
      {view.partial && (
        <div aria-hidden className={cn("flex min-h-5 items-center", tall)}>
          <Skeleton className="h-3.5 w-44" />
        </div>
      )}
      {bundle.confidence_reasons.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground">
            <ChevronRight className="size-4 transition-transform duration-200 ease-out group-data-[state=open]:rotate-90" />
            Why {bundle.confidence ?? "this"} confidence
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-2 grid list-disc gap-1 pl-[18px] text-[13px] text-muted-foreground wrap-anywhere">
              {bundle.confidence_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
      {assumptions.length > 0 && (
        <section className="grid gap-1">
          <h3 className="section-label">Assumptions</h3>
          <ul className="grid list-disc gap-1 pl-[18px] text-[13px] text-muted-foreground wrap-anywhere">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </section>
      )}
      {view.partial ? <ClaimsSkeleton /> : <Claims claims={view.claims} />}
      <KeyChart key={bundle.run_id} view={view} name={fileName(bundle.run_id)} />
      {!view.partial && <FollowUps items={view.follow_ups} />}
      {view.drivers && <Drivers drivers={view.drivers} />}
      {view.recon && <Recon recon={view.recon} />}
      {!view.partial && (
        <Button
          variant="outline"
          size="sm"
          data-testid="download-bundle"
          className="justify-self-start"
          onClick={() => download(bundle)}
        >
          <Download />
          Download run bundle
        </Button>
      )}
    </article>
  );
}

/** One bundle, by status: the answer, a clarification, a refusal or an error. `feedback`: a reopened run's thumb. */
export function BundleView({ bundle, view, feedback }: { bundle: AnswerBundle; view: View; feedback?: Feedback }) {
  if (view.partial) return <AnswerView bundle={bundle} view={view} />; // its bundle.status is not final yet
  switch (bundle.status) {
    case "error":
      return <ErrorCard bundle={bundle} />;
    case "clarify":
      return <Clarification bundle={bundle} />;
    case "refused":
      return <RefusalCard bundle={bundle} />;
    default:
      return <AnswerView bundle={bundle} view={view} feedback={feedback} />;
  }
}
