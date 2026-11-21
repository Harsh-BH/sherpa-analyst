"use client";

import type { ComponentProps } from "react";
import { ChevronRight, CircleAlert, Download, Gauge, Info, ShieldCheck, TriangleAlert } from "lucide-react";

import { Claims } from "@/components/answer/claims";
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
  low: { label: "Low", cls: "bg-negative/10 text-negative" },
};
const pill = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12.5px] font-medium [&>svg]:size-3.5";

function download(bundle: AnswerBundle) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `sherpa-run-${bundle.run_id.replace(/[^A-Za-z0-9_.-]/g, "_")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url));
}

/** An answered bundle, in the spec's order: data quality first, never folded away. */
export function AnswerView({ bundle, view }: { bundle: AnswerBundle; view: View }) {
  const conf = bundle.confidence ? CONFIDENCE[bundle.confidence] : null;
  const assumptions = bundle.plan?.assumptions ?? [];
  return (
    <article className="grid gap-3.5">
      {bundle.dq.map((w, i) => (
        <Banner key={i} tone={w.severity} data-testid="dq-banner">
          <b className="font-semibold">Data quality · {w.check.replaceAll("_", " ")}:</b> {w.message}
        </Banner>
      ))}
      <h2
        data-testid="headline"
        className="mt-1 text-[22px] leading-[1.3] font-semibold tracking-[-0.01em] text-balance wrap-anywhere"
      >
        {bundle.headline || "No headline was produced."}
      </h2>
      <div className="flex flex-wrap items-center gap-2">
        {conf && (
          <span data-testid="badge-confidence" className={cn(pill, conf.cls)}>
            <Gauge />
            {conf.label} confidence
          </span>
        )}
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
            <ChevronRight className="size-4 transition-transform group-data-[state=open]:rotate-90" />
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
          <h3 className="text-xs font-medium text-muted-foreground">
            Assumptions
          </h3>
          <ul className="grid list-disc gap-1 pl-[18px] text-[13px] text-muted-foreground wrap-anywhere">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </section>
      )}
      <Claims claims={view.claims} />
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
    </article>
  );
}

/** Clarification, refusal and error bundles until their full cards exist: the one sentence that matters and the run id. */
export function StatusFallback({ bundle }: { bundle: AnswerBundle }) {
  const text =
    bundle.status === "clarify"
      ? (bundle.clarification?.question ?? "Sherpa needs a clarification.")
      : bundle.status === "refused"
        ? (bundle.refusal?.reason ?? "This request was refused.")
        : (bundle.error ?? "No error message was recorded.");
  return (
    <div data-testid="status-fallback" className="grid gap-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <p className="wrap-anywhere">{text}</p>
      <p className="font-mono text-xs text-muted-foreground wrap-anywhere">run {bundle.run_id}</p>
    </div>
  );
}
