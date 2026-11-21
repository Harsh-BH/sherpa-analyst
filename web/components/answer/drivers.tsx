import { DataTable } from "@/components/answer/data-table";
import type { View } from "@/lib/api";

const caption = "px-2 pt-1 text-xs text-muted-foreground wrap-anywhere";

/** The driver effect tables, one per dimension, then the drill-down cells. */
export function Drivers({ drivers }: { drivers: NonNullable<View["drivers"]> }) {
  return (
    <section data-testid="drivers" className="grid min-w-0 gap-2">
      <h3 className="text-xs font-medium text-muted-foreground wrap-anywhere">{drivers.heading}</h3>
      {drivers.tables.map(([title, table]) => (
        <div key={title} className="grid min-w-0 gap-1 rounded-lg border bg-card p-1">
          <p className={caption}>{title}</p>
          <DataTable table={table} />
        </div>
      ))}
      {drivers.drilldown && (
        <div className="grid min-w-0 gap-1 rounded-lg border bg-card p-1">
          <p className={caption}>Drill-down cells</p>
          <DataTable table={drivers.drilldown} />
        </div>
      )}
    </section>
  );
}
