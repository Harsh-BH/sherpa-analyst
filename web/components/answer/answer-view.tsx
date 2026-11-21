"use client";

import type { ComponentProps } from "react";
import { ChevronRight, CircleAlert, Download, Gauge, Info, ShieldCheck, TriangleAlert } from "lucide-react";

import { Claims } from "@/components/answer/claims";
import { Drivers } from "@/components/answer/drivers";
import { KeyChart } from "@/components/answer/key-chart";
import { Recon } from "@/components/answer/recon";
import { Clarification, ErrorCard, RefusalCard } from "@/components/answer/states";
import { ClaimsSkeleton, HeadlineSkeleton } from "@/components/answer/summary-skeleton";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { AnswerBundle, View } from "@/lib/api";
import { cn } from "@/lib/utils";

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

/** Save the bundle as JSON; the file name keeps only safe characters of the run id. */
export function download(bundle: AnswerBundle) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `sherpa-run-${bundle.run_id.replace(/[^A-Za-z0-9_.-]/g, "_")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url));
}

/** An answered bundle, in the spec's order: data quality first, never folded away. A partial view (the numbers before
 * the narrative) draws the same tree with skeletons for the headline and claims, so the result swaps in without the
 * page jumping or the charts redrawing: only the headline and claims animate in. */
export function AnswerView({ bundle, view }: { bundle: AnswerBundle; view: View }) {
  const conf = bundle.confidence ? CONFIDENCE[bundle.confidence] : null;
  const assumptions = bundle.plan?.assumptions ?? [];
  return (
    // stagger: each section fades in and rises, 50 ms after the one before
    <article className="stagger grid gap-3.5">
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
          className="mt-1 text-[22px] leading-[1.3] font-semibold tracking-tight text-balance wrap-anywhere"
        >
          {bundle.headline || "No headline was produced."}
        </h2>
      )}
      <div className="flex flex-wrap items-center gap-2">
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
      <KeyChart key={bundle.run_id} view={view} />
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

/** One bundle, by status: the answer, a clarification, a refusal or an error. */
export function BundleView({ bundle, view }: { bundle: AnswerBundle; view: View }) {
  if (view.partial) return <AnswerView bundle={bundle} view={view} />; // its bundle.status is not final yet
  switch (bundle.status) {
    case "error":
      return <ErrorCard bundle={bundle} />;
    case "clarify":
      return <Clarification bundle={bundle} />;
    case "refused":
      return <RefusalCard bundle={bundle} />;
    default:
      return <AnswerView bundle={bundle} view={view} />;
  }
}
