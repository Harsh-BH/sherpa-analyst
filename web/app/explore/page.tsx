"use client";

import { useCallback, useState } from "react";

import { KVList } from "@/components/answer/data-table";
import { Banner, BundleView } from "@/components/answer/answer-view";
import { ExploreForm } from "@/components/explore/explore-form";
import { AnswerRail, planItems } from "@/components/rail/answer-rail";
import { Workspace } from "@/components/shell/workspace";
import type { ExplorePlan } from "@/lib/api";
import { useSherpa } from "@/lib/store";

export default function ExplorePage() {
  const { meta, metaError, run, railOpen, setRailOpen } = useSherpa();
  const [plan, setPlan] = useState<ExplorePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [ran, setRan] = useState(false); // an answer from the Ask page is not this form's result
  const onPlan = useCallback((p: ExplorePlan | null, e: string | null) => {
    setPlan(p);
    setPlanError(e);
  }, []);
  const result = ran && run.status === "done" ? run.result : undefined;

  const center = (
    <div className="mx-auto grid w-full max-w-[760px] gap-3.5 px-4 pt-4 pb-16 md:px-6">
      <h1 className="text-lg font-semibold">Explore</h1>
      {metaError && <Banner tone="error">{metaError}. The catalog did not load; reload to try again.</Banner>}
      {!meta && !metaError && <p className="text-sm text-muted-foreground">Loading the catalog…</p>}
      {meta && (
        <ExploreForm catalog={meta.catalog} onPlan={onPlan} onRun={() => setRan(true)} />
      )}
      {planError && <Banner tone="error" role="alert">{planError}</Banner>}
      {plan && <p className="text-[13px] text-muted-foreground wrap-anywhere">Question: {plan.question}</p>}
      {ran && run.status === "running" && <p className="text-sm text-muted-foreground">Running the plan…</p>}
      {ran && run.status === "failed" && (
        <Banner tone="error" role="alert" data-testid="error-card">
          <b className="font-semibold">No answer.</b> {run.error}
        </Banner>
      )}
      {result && <BundleView bundle={result.bundle} view={result.view} />}
    </div>
  );

  const rail = (
    <div className="grid min-w-0">
      <div className="grid min-w-0 gap-4 border-b p-4">
        <h3 className="text-xs font-medium text-muted-foreground">Plan</h3>
        {plan ? (
          <>
            <KVList items={planItems(plan.plan)} />
            <pre data-testid="plan-json" className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
              {JSON.stringify(plan.plan, null, 2)}
            </pre>
          </>
        ) : (
          <p className="text-[13px] text-muted-foreground">Choose a metric to see its plan.</p>
        )}
      </div>
      {result && <AnswerRail bundle={result.bundle} view={result.view} />}
    </div>
  );

  return <Workspace railTitle="Plan" railOpen={railOpen} onRailOpenChange={setRailOpen} center={center} rail={rail} />;
}
