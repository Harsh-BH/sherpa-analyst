"use client";

import { useEffect, useState } from "react";

import { Banner } from "@/components/answer/answer-view";
import { KVList } from "@/components/answer/data-table";
import { Workspace } from "@/components/shell/workspace";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getRuns, type RunsResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

export function RunsView() {
  const [data, setData] = useState<RunsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);

  useEffect(() => {
    getRuns().then(setData, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const ok = data?.status === "ok" ? data : null;
  const selected = ok && sel !== null ? ok.recent[sel] : null;

  const center = (
    <div className="mx-auto grid w-full max-w-[960px] gap-3.5 px-4 pt-4 pb-16 md:px-6">
      <h1 className="text-lg font-semibold">Runs</h1>
      {error && <Banner tone="error" role="alert">{error}</Banner>}
      {!data && !error && <p className="text-sm text-muted-foreground">Loading runs…</p>}
      {data?.status === "unavailable" && (
        <Banner tone="info" data-testid="runs-unavailable">{data.message}</Banner>
      )}
      {ok && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            {ok.tiles.map((t) => (
              <div key={t.label} data-testid="run-tile" className="min-w-0 rounded-lg border bg-card p-3">
                <div className="text-xs text-muted-foreground">{t.label}</div>
                <div className="mt-1 text-xl font-semibold tabular-nums">{t.value}</div>
              </div>
            ))}
          </div>
          {ok.recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">No runs recorded yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border bg-card">
              <Table data-testid="runs-table" className="text-[12.5px]">
                <TableHeader>
                  <TableRow>
                    {["Asked", "Persona", "Question", "Status", "Route", "Confidence", "Total", "Cost"].map((h) => (
                      <TableHead key={h} className="h-8 text-muted-foreground">{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ok.recent.map((r, i) => (
                    <TableRow
                      key={r.run_id}
                      tabIndex={0}
                      aria-selected={sel === i}
                      onClick={() => setSel(i)}
                      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(i))}
                      className={cn("cursor-pointer", sel === i && "bg-muted")}
                    >
                      <TableCell>{r.asked_at}</TableCell>
                      <TableCell>{r.persona}</TableCell>
                      <TableCell className="min-w-64 whitespace-normal wrap-break-word">{r.question}</TableCell>
                      <TableCell>{r.status}</TableCell>
                      <TableCell>{r.route}</TableCell>
                      <TableCell>{r.confidence}</TableCell>
                      <TableCell>{r.total}</TableCell>
                      <TableCell>{r.cost}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}
    </div>
  );

  const rail = selected ? (
    <div data-testid="run-footprint" className="grid min-w-0 gap-3 p-4">
      <div className="font-mono text-xs text-muted-foreground wrap-anywhere">{selected.run_id}</div>
      <KVList items={selected.footprint} />
    </div>
  ) : (
    <p className="p-4 text-[13px] text-muted-foreground">Select a run to see its footprint.</p>
  );

  return <Workspace railTitle="Footprint" center={center} rail={rail} />;
}
