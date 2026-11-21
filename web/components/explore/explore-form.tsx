"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import * as api from "@/lib/api";
import { useSherpa } from "@/lib/store";

type Window = api.ExploreForm["window"];
type Intent = api.ExploreForm["intent"];
const NEEDS_BASELINE: Intent[] = ["compare_periods", "explain_change"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid content-start gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

function Pick({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: api.Meta["catalog"]["windows"];
  onChange(v: string): void;
}) {
  return (
    <Field label={label}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label} className="w-full min-w-0">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}

/** The plan the form describes, fetched from the API (debounced 250 ms); `plan` is null while it is out of date or invalid. */
export function useExplorePlan(form: api.ExploreForm) {
  const [state, setState] = useState<{ form: api.ExploreForm | null; plan: api.ExplorePlan | null; error: string | null }>({ form: null, plan: null, error: null });
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.explorePlan(form).then(
        (plan) => live && setState({ form, plan, error: null }),
        (e) => live && setState({ form, plan: null, error: e instanceof Error ? e.message : String(e) }),
      );
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [form]);
  // A result only counts for the exact form it was fetched for; while the form has moved on, report nothing.
  return state.form === form ? state : { plan: null, error: null };
}

/** The Explore form: a governed plan built from catalog choices. Reports the plan up; "Run plan" asks it. */
export function ExploreForm({ catalog, onPlan, onRun }: { catalog: api.Meta["catalog"]; onPlan(p: api.ExplorePlan | null, error: string | null): void; onRun(): void }) {
  const { run, ask } = useSherpa();
  const [intent, setIntent] = useState<Intent>("metric_value");
  const [metric, setMetric] = useState(catalog.metrics[0].name);
  const [dims, setDims] = useState<string[]>([]);
  const [window, setWindow] = useState<Window>("last_7_days");
  const [baseline, setBaseline] = useState<Window>("previous_7_days");
  const [grain, setGrain] = useState<"day" | "hour">("day");
  const [filterDims, setFilterDims] = useState<string[]>([]);
  const [filterVals, setFilterVals] = useState<Record<string, string[]>>({});

  const table = catalog.metrics.find((m) => m.name === metric)?.table;
  const dimensions = useMemo(() => catalog.dimensions.filter((d) => table && d.tables.includes(table)), [catalog, table]);
  const names = useMemo(() => new Set(dimensions.map((d) => d.name)), [dimensions]);

  const form = useMemo<api.ExploreForm>(
    () => ({
      intent,
      metric,
      dimensions: dims.filter((d) => names.has(d)),
      window,
      baseline: NEEDS_BASELINE.includes(intent) ? baseline : null,
      grain,
      filters: filterDims
        .filter((d) => names.has(d) && filterVals[d]?.length)
        .map((d) => ({ dimension: d, op: "in" as const, values: filterVals[d] })),
    }),
    [intent, metric, dims, names, window, baseline, grain, filterDims, filterVals],
  );
  const { plan, error } = useExplorePlan(form);
  useEffect(() => onPlan(plan, error), [plan, error, onPlan]);

  return (
    <div className="grid gap-4 rounded-lg border bg-card p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Pick label="Intent" value={intent} options={catalog.intents} onChange={(v) => setIntent(v as Intent)} />
        <Pick
          label="Metric"
          value={metric}
          options={catalog.metrics.map((m) => ({ value: m.name, label: m.label }))}
          onChange={setMetric}
        />
        <Pick label="Window" value={window} options={catalog.windows} onChange={(v) => setWindow(v as Window)} />
        {NEEDS_BASELINE.includes(intent) && (
          <Pick label="Baseline" value={baseline} options={catalog.windows} onChange={(v) => setBaseline(v as Window)} />
        )}
        {intent === "trend" && (
          <Pick
            label="Grain"
            value={grain}
            options={catalog.grains.map((g) => ({ value: g, label: g }))}
            onChange={(v) => setGrain(v as "day" | "hour")}
          />
        )}
      </div>
      <Field label="Dimensions">
        <ToggleGroup type="multiple" variant="outline" size="sm" aria-label="Dimensions" value={dims} onValueChange={setDims} className="flex-wrap">
          {dimensions.map((d) => (
            <ToggleGroupItem key={d.name} value={d.name} data-testid={`dim-${d.name}`}>
              {d.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      <Field label="Filter by">
        <ToggleGroup type="multiple" variant="outline" size="sm" aria-label="Filter dimensions" value={filterDims} onValueChange={setFilterDims} className="flex-wrap">
          {dimensions.map((d) => (
            <ToggleGroupItem key={d.name} value={d.name} data-testid={`filter-dim-${d.name}`}>
              {d.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      {dimensions
        .filter((d) => filterDims.includes(d.name))
        .map((d) => (
          <Field key={d.name} label={`${d.label} is one of`}>
            <ToggleGroup
              type="multiple"
              variant="outline"
              size="sm"
              aria-label={`${d.label} values`}
              value={filterVals[d.name] ?? []}
              onValueChange={(v) => setFilterVals((f) => ({ ...f, [d.name]: v }))}
              className="flex-wrap"
            >
              {d.values.map((v) => (
                <ToggleGroupItem key={v} value={v} data-testid={`filter-val-${d.name}-${v}`}>
                  {v}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Field>
        ))}
      <Button
        className="justify-self-start"
        disabled={!plan || run.status === "running"}
        onClick={() => {
          if (!plan) return;
          onRun();
          void ask(plan.question, { plan: plan.plan });
        }}
      >
        Run plan
      </Button>
    </div>
  );
}
