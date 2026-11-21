"use client";

import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";

import { Banner } from "@/components/answer/answer-view";
import { Workspace } from "@/components/shell/workspace";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getEval, type EvalResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Ok = Extract<EvalResponse, { status: "ok" }>;
type Case = Ok["cases"][number];

/** Pass or fail as icon plus text, never colour alone. */
function Verdict({ pass }: { pass: boolean }) {
  const Icon = pass ? Check : X;
  return (
    <span className="inline-flex items-center gap-1">
      <Icon className="size-4" aria-hidden />
      {pass ? "Pass" : "Fail"}
    </span>
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
          <h3 className="text-xs font-medium text-muted-foreground">{name}</h3>
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

  useEffect(() => {
    getEval().then(setData, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const ok = data?.status === "ok" ? data : null;
  const selected = ok && sel !== null ? ok.cases[sel] : null;

  const center = (
    <div className="mx-auto grid w-full max-w-[960px] gap-3.5 px-4 pt-4 pb-16 md:px-6">
      <h1 className="text-lg font-semibold">Eval</h1>
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
            {ok.tiles.map((t) => (
              <div key={t.label} data-testid="eval-tile" className="min-w-0 rounded-lg border bg-card p-3">
                <div className="text-xs text-muted-foreground">{t.label}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums">{t.sherpa}</div>
                <div className="text-xs text-muted-foreground tabular-nums">baseline {t.baseline}</div>
              </div>
            ))}
          </div>
          <div className="overflow-x-auto rounded-lg border bg-card">
            <Table data-testid="eval-cases" className="text-[12.5px]">
              <TableHeader>
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
                    onClick={() => setSel(i)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(i))}
                    className={cn("cursor-pointer", sel === i && "bg-muted")}
                  >
                    <TableCell>{c.id}</TableCell>
                    <TableCell>{c.kind}</TableCell>
                    <TableCell className="min-w-64 whitespace-normal wrap-break-word">{c.question}</TableCell>
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

  return <Workspace railTitle="Case" center={center} rail={rail} />;
}
