"use client";

import { Fragment, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { View } from "@/lib/api";
import { cn } from "@/lib/utils";

type Rows = Omit<NonNullable<View["evidence"][number]["table"]>, "key_columns" | "more_label"> & {
  key_columns?: string[];
  more_label?: string | null;
};
type KV = View["footprint"]["items"][number];

// "More columns" is one choice for every table, kept for the page's session (module state, not per answer).
let allColumns = false;
const listeners = new Set<() => void>();
function subscribe(f: () => void) {
  listeners.add(f);
  return () => {
    listeners.delete(f);
  };
}
function setAllColumns(v: boolean) {
  allColumns = v;
  listeners.forEach((f) => f());
}

// The first column stays put when the table scrolls sideways; opaque, so cells pass under it (row hover included).
const sticky = "sticky left-0 z-[1] bg-card [tr:hover>&]:bg-[color-mix(in_oklch,var(--muted)_50%,var(--card))]";

/** A view table, every cell exactly as Python formatted it. A wide table scrolls inside its own box.
 * Values stay on one line ("-0.80 pp" never splits); only long text (over 40 characters: notes, names) wraps,
 * in a column at least 16rem wide. With `more_label` (Python's "More columns (7)"), only `key_columns` show until it is
 * pressed. */
export function DataTable({ table }: { table: Rows }) {
  const all = useSyncExternalStore(subscribe, () => allColumns, () => false);
  const key = table.key_columns ?? [];
  const more = table.more_label;
  const shown = table.columns.flatMap((c, j) => (all || !more || key.includes(c) ? [j] : []));
  return (
    <div className="grid min-w-0">
      <Table className="text-[12.5px]">
        <TableHeader>
          <TableRow>
            {shown.map((j) => (
              <TableHead key={j} className={cn("h-8 text-muted-foreground", j === 0 && sticky)}>
                {table.columns[j]}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {table.rows.map((row, i) => (
            <TableRow key={i}>
              {shown.map((j) => (
                <TableCell
                  key={j}
                  className={cn(
                    "py-1.5 align-top",
                    row[j].length > 40 && "min-w-64 whitespace-normal wrap-break-word",
                    j === 0 && sticky,
                  )}
                >
                  {row[j]}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {more && (
        <Button
          variant="ghost"
          size="xs"
          data-testid="more-columns"
          aria-expanded={all}
          className="justify-self-start text-muted-foreground"
          onClick={() => setAllColumns(!all)}
        >
          {all ? "Fewer columns" : more}
        </Button>
      )}
    </div>
  );
}

/** Label and value pairs from the view. */
export function KVList({ items }: { items: KV[] }) {
  return (
    <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-[12.5px]">
      {items.map((kv, i) => (
        <Fragment key={i}>
          <dt className="text-muted-foreground">{kv.label}</dt>
          <dd className="min-w-0 whitespace-pre-line wrap-anywhere">{kv.value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
