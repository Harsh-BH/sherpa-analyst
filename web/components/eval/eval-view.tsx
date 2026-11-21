"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { Check, X } from "lucide-react";

import { Banner } from "@/components/answer/answer-view";
import { ChartGrid } from "@/components/charts/chart-card";
import { Workspace } from "@/components/shell/workspace";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getEval, type EvalResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Ok = Extract<EvalResponse, { status: "ok" }>;
type Case = Ok["cases"][number];

/** Pass or fail as icon plus text in its status hue, never colour alone. */
function Verdict({ pass }: { pass: boolean }) {
  const Icon = pass ? Check : X;
  return (
    <Badge variant={pass ? "positive" : "negative"} data-testid="verdict" data-pass={pass}>
      <Icon aria-hidden />
      {pass ? "Pass" : "Fail"}
    </Badge>
  );
}

function CaseDetail({ c }: { c: Case }) {
  const rows: [string, boolean, string | null][] = [
    ["Sherpa", c.sherpa_pass, c.sherpa_detail],
    ["Baseline", c.baseline_pass, c.baseline_detail],
  ];
  return (
    <div data-testid="eval-case-detail" className="grid min-w-0 gap-3 p-4 text-[12.5px]">
      <div>
        <div className="text-xs text-muted-foreground">
          {c.id} · {c.kind}
        </div>
        <p className="mt-1 wrap-anywhere">{c.question}</p>
      </div>
      {rows.map(([name, pass, detail]) => (
        <div key={name} className="grid gap-1">
          <h3 className="section-label">{name}</h3>
          <Verdict pass={pass} />
          <p className="wrap-anywhere">{detail ?? "No detail recorded."}</p>
        </div>
      ))}
    </div>
  );
}

export function EvalView() {
  const [data, setData] = useState<EvalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  // Below 1280 px the rail is a sheet: picking a row opens it.
  const pick = (i: number) => {
    setSel(i);
    setRailOpen(true);
  };

  useEffect(() => {
    getEval().then(setData, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const ok = data?.status === "ok" ? data : null;
  const selected = ok && sel !== null ? ok.cases[sel] : null;

  const center = (
    <div className="mx-auto grid w-full max-w-[960px] gap-3.5 px-4 pt-4 pb-16 md:px-6">
      <h1 className="text-lg font-semibold tracking-tight">Eval</h1>
      {error && <Banner tone="error" role="alert">{error}</Banner>}
      {!data && !error && <p className="text-sm text-muted-foreground">Loading eval results…</p>}
      {data?.status === "missing" && (
        <Banner tone="info">No eval results yet: {data.path} does not exist. Run the eval to create it.</Banner>
      )}
      {data?.status === "error" && <Banner tone="error" role="alert">{data.message}</Banner>}
      {ok && (
        <>
          {ok.fixture && (
            <Banner tone="info">Showing fixture results: the eval has not been run against the live pipeline.</Banner>
          )}
          <p className="text-[13px] text-muted-foreground">
            Generated {ok.generated_at ?? "n/a"} · data {ok.data_version ?? "n/a"}
          </p>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            {ok.tiles.map((t, i) => (
              <div
                key={t.label}
                data-testid="eval-tile"
                style={{ "--i": i } as CSSProperties}
                className="rise flex min-w-0 flex-col rounded-xl border bg-card p-3.5 shadow-sm"
              >
                <div className="section-label">{t.label}</div>
                <div className="mt-auto pt-1.5 text-xl font-semibold tabular-nums">{t.sherpa}</div>
                <div className="text-xs text-muted-foreground tabular-nums">baseline {t.baseline}</div>
              </div>
            ))}
          </div>
          <ChartGrid charts={ok.charts} from={ok.tiles.length} />
          <div
            style={{ "--i": ok.tiles.length + ok.charts.length } as CSSProperties}
            className="rise overflow-hidden rounded-xl border bg-card shadow-sm"
          >
            <Table data-testid="eval-cases" className="text-[12.5px]" containerClassName="max-h-[70vh] overflow-auto">
              <TableHeader className="sticky top-0 z-[1] bg-card/80 backdrop-blur-md">
                <TableRow>
                  {["Case", "Kind", "Question", "Sherpa", "Baseline"].map((h) => (
                    <TableHead key={h} className="h-8 text-muted-foreground">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {ok.cases.map((c, i) => (
                  <TableRow
                    key={i}
                    tabIndex={0}
                    aria-selected={sel === i}
                    onClick={() => pick(i)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick(i))}
                    className={cn("cursor-pointer", sel === i && "bg-accent-blue/8 hover:bg-accent-blue/8")}
                  >
                    <TableCell>{c.id}</TableCell>
                    <TableCell>{c.kind}</TableCell>
                    <TableCell className="min-w-48 whitespace-normal wrap-break-word">{c.question}</TableCell>
                    <TableCell><Verdict pass={c.sherpa_pass} /></TableCell>
                    <TableCell><Verdict pass={c.baseline_pass} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );

  const rail = selected ? (
    <CaseDetail c={selected} />
  ) : (
    <p className="p-4 text-[13px] text-muted-foreground">Select a case to see its details.</p>
  );

  return (
    <Workspace railTitle="Case" railOpen={railOpen} onRailOpenChange={setRailOpen} center={center} rail={rail} />
  );
}
