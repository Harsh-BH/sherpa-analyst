import { DataTable } from "@/components/answer/data-table";
import type { View } from "@/lib/api";

/** What separates transaction GMV from the settled payout, and which table is the source of truth. */
export function Recon({ recon }: { recon: NonNullable<View["recon"]> }) {
  return (
    <section data-testid="recon" className="grid min-w-0 gap-2">
      <h3 className="text-xs font-medium text-muted-foreground">Reconciliation components</h3>
      <div className="min-w-0 rounded-lg border bg-card p-1">
        <DataTable table={recon.components} />
      </div>
      <p className="text-xs text-muted-foreground wrap-anywhere">Source of truth: {recon.source_of_truth}</p>
    </section>
  );
}
