"use client";

import { useState, type ReactNode } from "react";
import { Menu, PanelRight, Search } from "lucide-react";

import { usePalette } from "@/components/shell/command-palette";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useSidebar } from "@/components/ui/sidebar";
import { useIsMobile, useMediaQuery } from "@/hooks/use-mobile";

type Props = {
  center: ReactNode;
  rail: ReactNode;
  railTitle: string;
  railOpen?: boolean;
  onRailOpenChange?: (open: boolean) => void;
};

/** Centre and Inspector rail: resizable panes at 1280 px and wider, a slide-over sheet below, and on phones
 * (below 768 px) a bottom sheet under a compact top bar that also holds the menu and the command palette.
 * ponytail: the centre remounts when the window crosses 1280 px; keep state above <Workspace> if that ever bites. */
export function Workspace({ center, rail, railTitle, railOpen, onRailOpenChange }: Props) {
  const wide = useMediaQuery("(min-width: 1280px)", true);
  const phone = useIsMobile();
  const { setOpenMobile } = useSidebar();
  const openPalette = usePalette();
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
          <div className="bg-tint h-full overflow-y-auto">{center}</div>
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
      <div className="flex items-center gap-2 border-b px-3 py-1.5 md:px-4 md:py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Open menu"
          className="md:hidden"
          onClick={() => setOpenMobile(true)}
        >
          <Menu />
        </Button>
        <span className="font-semibold md:hidden">Sherpa</span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Open command palette"
          className="ml-auto md:hidden"
          onClick={() => openPalette(true)}
        >
          <Search />
        </Button>
        <Button variant="outline" size="sm" className="md:ml-auto" onClick={() => setOpen(true)}>
          <PanelRight className="size-4" />
          Inspector
        </Button>
      </div>
      <div className="bg-tint min-h-0 flex-1 overflow-y-auto">{center}</div>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side={phone ? "bottom" : "right"}
          data-testid="rail-sheet"
          aria-describedby={undefined}
          className="gap-0 data-[side=bottom]:max-h-[85vh] data-[side=bottom]:rounded-t-2xl data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
        >
          {/* a bottom sheet's drag-handle look; Esc, the close button and the overlay close it */}
          {phone && <div aria-hidden className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-muted-foreground/40" />}
          <SheetHeader className="border-b">
            <SheetTitle>{railTitle}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">{rail}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
