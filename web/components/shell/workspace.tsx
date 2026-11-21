"use client";

import { useState, type ReactNode } from "react";
import { PanelRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/use-mobile";

type Props = {
  center: ReactNode;
  rail: ReactNode;
  railTitle: string;
  railOpen?: boolean;
  onRailOpenChange?: (open: boolean) => void;
};

/** Centre and Inspector rail: resizable panes at 1280 px and wider, a slide-over sheet below.
 * ponytail: the centre remounts when the window crosses 1280 px; keep state above <Workspace> if that ever bites. */
export function Workspace({ center, rail, railTitle, railOpen, onRailOpenChange }: Props) {
  const wide = useMediaQuery("(min-width: 1280px)", true);
  const [ownOpen, setOwnOpen] = useState(false);
  const open = railOpen ?? ownOpen;
  const setOpen = (o: boolean) => {
    setOwnOpen(o);
    onRailOpenChange?.(o);
  };

  if (wide)
    return (
      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="64%" className="min-w-0">
          <div className="h-full overflow-y-auto">{center}</div>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="36%" minSize="28%" className="min-w-0">
          <aside data-testid="rail" aria-label={railTitle} className="flex h-full flex-col bg-card">
            <h2 className="border-b px-4 py-2.5 text-sm font-medium">{railTitle}</h2>
            <div className="min-h-0 flex-1 overflow-y-auto">{rail}</div>
          </aside>
        </ResizablePanel>
      </ResizablePanelGroup>
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex justify-end border-b px-4 py-2">
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <PanelRight className="size-4" />
          Inspector
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{center}</div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          data-testid="rail-sheet"
          aria-describedby={undefined}
          className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
        >
          <SheetHeader className="border-b">
            <SheetTitle>{railTitle}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">{rail}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
