import { Fragment } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { View } from "@/lib/api";
import { cn } from "@/lib/utils";

type Rows = NonNullable<View["evidence"][number]["table"]>;
type KV = View["footprint"]["items"][number];

/** A view table, every cell exactly as Python formatted it. A wide table scrolls inside its own box.
 * Values stay on one line ("-0.80 pp" never splits); only long text (over 40 characters: notes, names) wraps,
 * in a column at least 16rem wide. */
export function DataTable({ table }: { table: Rows }) {
  return (
    <Table className="text-[12.5px]">
      <TableHeader>
        <TableRow>
          {table.columns.map((c, i) => (
            <TableHead key={i} className="h-8 text-muted-foreground">
              {c}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {table.rows.map((row, i) => (
          <TableRow key={i}>
            {row.map((cell, j) => (
              <TableCell
                key={j}
                className={cn("py-1.5 align-top", cell.length > 40 && "min-w-64 whitespace-normal wrap-break-word")}
              >
                {cell}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
