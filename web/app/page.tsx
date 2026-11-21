import { Workspace } from "@/components/shell/workspace";

export default function AskPage() {
  return (
    <Workspace
      railTitle="Inspector"
      center={
        <div className="p-6">
          <h1 className="text-lg font-semibold">Ask</h1>
        </div>
      }
      rail={<p className="p-4 text-sm text-muted-foreground">The plan, evidence and footprints of an answer show here.</p>}
    />
  );
}
