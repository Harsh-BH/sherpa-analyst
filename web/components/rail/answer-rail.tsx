"use client";

import { ChevronRight, Download } from "lucide-react";

import { download } from "@/components/answer/answer-view";
import { KVList } from "@/components/answer/data-table";
import { stageLabel } from "@/components/answer/trace";
import { EvidenceEntry } from "@/components/rail/evidence-entry";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AnswerBundle, View } from "@/lib/api";
import { useSherpa } from "@/lib/store";

type Plan = NonNullable<AnswerBundle["plan"]>;

const caption = "text-xs font-medium text-muted-foreground";
const empty = "px-4 py-3 text-[13px] text-muted-foreground";

/** The plan's fields that are set, as label and value pairs. Every value is the plan's own text. */
export function planItems(p: Plan) {
  const when = (w: Plan["window"]) => w && (w.label || w.preset || [w.start, w.end].filter(Boolean).join(" to "));
  const rows: [string, string | null | undefined][] = [
    ["Question", p.question],
    ["Route", p.route],
    ["Intent", p.intent],
    ["Metric", p.metric],
    ["Dimensions", p.dimensions.join(", ")],
    ["Filters", p.filters.map((f) => `${f.dimension} ${f.op.replace("_", " ")} ${f.values.join(", ")}`).join("; ")],
    ["Window", when(p.window)],
    ["Baseline", when(p.baseline)],
    ["Grain", p.grain],
    ["Assumptions", p.assumptions.join("\n")],
    ["Ambiguities", p.ambiguities.map((a) => `${a.kind.replaceAll("_", " ")}: ${a.description}`).join("\n")],
    ["Refusal", p.refuse_reason],
    ["Clarify", p.clarify_question],
  ];
  return rows.flatMap(([label, value]) => (value ? [{ label, value }] : []));
}

function PlanTab({ plan }: { plan: AnswerBundle["plan"] }) {
  if (!plan) return <p className={empty}>No plan was produced for this run.</p>;
  return (
    <div className="grid min-w-0 gap-4 p-4">
      <KVList items={planItems(plan)} />
      {plan.sql && (
        <section className="grid min-w-0 gap-1">
          <h4 className={caption}>SQL</h4>
          <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
            {plan.sql}
          </pre>
        </section>
      )}
      <Collapsible>
        <CollapsibleTrigger className="group flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground">
          <ChevronRight className="size-4 transition-transform group-data-[state=open]:rotate-90" />
          Raw JSON
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mt-2 overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
            {JSON.stringify(plan, null, 2)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

/** The Inspector rail for one answer: its plan, its evidence (linked to the claims) and its footprint. */
export function AnswerRail({ bundle, view }: { bundle: AnswerBundle; view: View }) {
  const { railTab, setRailTab } = useSherpa();
  return (
    <Tabs value={railTab} onValueChange={setRailTab} className="gap-0">
      <TabsList
        variant="line"
        className="sticky top-0 z-10 w-full justify-start rounded-none border-b bg-card px-2 group-data-horizontal/tabs:h-10"
      >
        <TabsTrigger value="plan" className="flex-none px-2">
          Plan
        </TabsTrigger>
        <TabsTrigger value="evidence" className="flex-none px-2">
          Evidence ({view.evidence.length})
        </TabsTrigger>
        <TabsTrigger value="footprints" className="flex-none px-2">
          Footprints
        </TabsTrigger>
      </TabsList>
      <TabsContent value="plan">
        <PlanTab plan={bundle.plan} />
      </TabsContent>
      <TabsContent value="evidence">
        {view.evidence.length ? (
          <ul>
            {view.evidence.map((e) => (
              <EvidenceEntry key={e.id} e={e} />
            ))}
          </ul>
        ) : (
          <p className={empty}>This answer has no evidence.</p>
        )}
      </TabsContent>
      <TabsContent value="footprints" className="grid min-w-0 content-start gap-4 p-4">
        <KVList items={view.footprint.items} />
        {view.footprint.stages.length > 0 && (
          <section className="grid gap-1.5">
            <h4 className={caption}>Time per stage</h4>
            <KVList items={view.footprint.stages.map((s) => ({ ...s, label: stageLabel(s.label) }))} />
          </section>
        )}
        <Button
          variant="outline"
          size="sm"
          data-testid="download-bundle-rail"
          className="justify-self-start"
          onClick={() => download(bundle)}
        >
          <Download />
          Download run bundle
        </Button>
      </TabsContent>
    </Tabs>
  );
}
