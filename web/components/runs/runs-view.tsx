"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { History } from "lucide-react";

import { Banner } from "@/components/answer/answer-view";
import { KVList } from "@/components/answer/data-table";
import { ChartGrid } from "@/components/charts/chart-card";
import { Workspace } from "@/components/shell/workspace";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getRuns, type RunsResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

// Run status in its hue (text stays, so never colour alone): answered positive, clarify warning, refused muted.
const STATUS = { answered: "positive", clarify: "warning", refused: "secondary", error: "destructive" } as const;
const StatusBadge = ({ status }: { status: string }) => (
  <Badge data-testid="run-status" variant={STATUS[status as keyof typeof STATUS] ?? "outline"}>
    {status}
  </Badge>
);

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
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Runs</h1>
        <p data-testid="runs-note" className="text-[13px] text-muted-foreground">
          Runs asked in the app. Test and eval runs are excluded.
        </p>
      </div>
      {error && <Banner tone="error" role="alert">{error}</Banner>}
      {!data && !error && <p className="text-sm text-muted-foreground">Loading runs…</p>}
      {data?.status === "unavailable" && (
        <Banner tone="info" data-testid="runs-unavailable">{data.message}</Banner>
      )}
      {ok && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            {ok.tiles.map((t, i) => (
              <div
                key={t.label}
                data-testid="run-tile"
                style={{ "--i": i } as CSSProperties}
                className="rise flex min-w-0 flex-col rounded-xl border bg-card p-3.5 shadow-sm"
              >
                <div className="section-label">{t.label}</div>
                <div className="mt-auto pt-1.5 text-xl font-semibold tabular-nums">{t.value}</div>
              </div>
            ))}
          </div>
          {ok.recent.length === 0 ? (
            <div
              data-testid="runs-empty"
              style={{ "--i": ok.tiles.length } as CSSProperties}
              className="rise grid justify-items-center gap-2 rounded-xl border border-dashed bg-card px-4 py-10 text-center"
            >
              <History aria-hidden className="size-5 text-muted-foreground" />
              <p className="text-sm font-medium">No runs yet. Ask a question and it shows up here.</p>
              <Link href="/" className="text-[13px] text-primary underline-offset-4 hover:underline">
                Go to Ask
              </Link>
            </div>
          ) : (
            <>
              <ChartGrid charts={ok.charts} from={ok.tiles.length} />
              <div
                style={{ "--i": ok.tiles.length + ok.charts.length } as CSSProperties}
                className="rise overflow-hidden rounded-xl border bg-card shadow-sm"
              >
                <Table data-testid="runs-table" className="text-[12.5px]" containerClassName="max-h-[70vh] overflow-auto">
                  <TableHeader className="sticky top-0 z-[1] bg-card/80 backdrop-blur-md">
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
                        className={cn("cursor-pointer", sel === i && "bg-accent-blue/8 hover:bg-accent-blue/8")}
                      >
                        <TableCell>{r.asked_at}</TableCell>
                        <TableCell>{r.persona}</TableCell>
                        <TableCell className="min-w-40 whitespace-normal wrap-break-word">{r.question}</TableCell>
                        <TableCell><StatusBadge status={r.status} /></TableCell>
                        <TableCell>{r.route}</TableCell>
                        <TableCell>{r.confidence}</TableCell>
                        <TableCell>{r.total}</TableCell>
                        <TableCell>{r.cost}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
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
