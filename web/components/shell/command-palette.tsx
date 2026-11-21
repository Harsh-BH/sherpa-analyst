"use client";

import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useId,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { ArrowLeft, Clock, Keyboard, MessageCircleQuestion, Search, UserRound, type LucideIcon } from "lucide-react";

import { NAV } from "@/components/shell/nav";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { useSherpa } from "@/lib/store";

/** One entry of the palette's Recent group. Integration fills it from /api/history (track A). */
export type RecentItem = { label: string; onSelect(): void };

type Item = { key: string; group: string; label: string; hint?: string; icon: LucideIcon; run(): void; keep?: boolean };

const Ctx = createContext<(open: boolean) => void>(() => {});
/** Opens (or closes) the command palette. */
export const usePalette = () => useContext(Ctx);

// ⌘ on Apple platforms, Ctrl elsewhere. The server snapshot says "not Mac", so hydration matches; the client then
// re-renders with the real answer.
const never = () => () => {};
const useIsMac = () => useSyncExternalStore(never, () => /Mac|iPhone|iPad/.test(navigator.userAgent), () => false);

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

/** Holds the palette's open state and the global shortcuts: ⌘K / Ctrl+K toggles it, "/" focuses the question box
 * when nothing is being typed and no dialog or sheet is open. */
export function PaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (e.target instanceof Element && e.target.closest("[role=dialog]")) return;
      const box = document.querySelector<HTMLInputElement>("[data-testid=question]");
      if (!box) return;
      e.preventDefault();
      box.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <Ctx.Provider value={setOpen}>
      {children}
      {/* integration: pass recent={…} built from /api/history */}
      <CommandPalette open={open} onOpenChange={setOpen} />
    </Ctx.Provider>
  );
}

export function CommandPalette({
  open,
  onOpenChange,
  recent = [],
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  recent?: RecentItem[];
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/10 duration-100 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
        <Dialog.Content
          data-testid="palette"
          aria-describedby={undefined}
          className="fixed top-[12vh] left-1/2 z-50 flex max-h-[70vh] w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg duration-150 ease-out data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Palette close={() => onOpenChange(false)} recent={recent} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The palette's body: mounted on each open, so the filter and the active option start fresh. */
function Palette({ close, recent }: { close(): void; recent: RecentItem[] }) {
  const { meta, persona, setPersona, ask } = useSherpa();
  const router = useRouter();
  const pathname = usePathname();
  const mac = useIsMac();
  const id = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [shortcuts, setShortcuts] = useState(false);

  const go = (href: string) => pathname !== href && router.push(href);
  const personaLabel = (key: string) => meta?.personas.find((p) => p.key === key)?.label ?? key;
  const questions = [...(meta?.demo ?? [])]; // demo, then the catalog's verified questions not already there
  for (const question of meta?.verified ?? [])
    if (!questions.some((q) => q.question === question)) questions.push({ question, persona: null });

  const items: Item[] = [
    ...NAV.map(({ href, label, icon }) => ({ key: href, group: "Pages", label, icon, run: () => go(href) })),
    ...recent.map((r, i) => ({ key: `recent-${i}`, group: "Recent", label: r.label, icon: Clock, run: r.onSelect })),
    ...questions.map((q) => ({
      key: `q-${q.question}`,
      group: "Questions",
      label: q.question,
      hint: q.persona ? `as ${personaLabel(q.persona)}` : undefined,
      icon: MessageCircleQuestion,
      run: () => {
        if (q.persona) setPersona(q.persona); // the refusal demo is asked as the South manager, as on the chips
        go("/");
        void ask(q.question, { persona: q.persona ?? undefined });
      },
    })),
    ...(meta?.personas ?? []).map((p) => ({
      key: `persona-${p.key}`,
      group: "Personas",
      label: `Switch to ${p.label}`,
      hint: p.key === persona ? "current" : undefined,
      icon: UserRound,
      run: () => setPersona(p.key),
    })),
    { key: "shortcuts", group: "Help", label: "Keyboard shortcuts", icon: Keyboard, run: () => setShortcuts(true), keep: true },
  ];

  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = items.filter((it) => words.every((w) => `${it.group} ${it.label}`.toLowerCase().includes(w)));
  const groups = [...new Set(shown.map((it) => it.group))]; // items are built group by group, so order holds
  const act = Math.min(active, shown.length - 1);
  const activeId = act >= 0 ? `${id}-${act}` : undefined;

  useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView({ block: "nearest" });
  }, [activeId]);

  const choose = (it: Item) => {
    if (!it.keep) close();
    it.run();
  };

  if (shortcuts) return <Shortcuts mac={mac} back={() => setShortcuts(false)} />;

  return (
    <>
      <div className="flex items-center gap-2 border-b px-3">
        <Search aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <input
          data-testid="palette-input"
          role="combobox"
          aria-expanded
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-label="Search pages, questions and personas"
          placeholder="Search pages, questions and personas…"
          autoFocus
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if ((e.key === "ArrowDown" || e.key === "ArrowUp") && shown.length) {
              e.preventDefault();
              setActive((act + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length);
            } else if (e.key === "Enter" && shown[act]) {
              e.preventDefault();
              choose(shown[act]);
            }
          }}
          className="h-11 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      <div id={`${id}-list`} role="listbox" aria-label="Commands" className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {groups.map((g) => (
          <div key={g} role="group" aria-labelledby={`${id}-${g}`}>
            <div id={`${id}-${g}`} role="presentation" className="section-label px-2 pt-2 pb-1">
              {g}
            </div>
            {shown.map(
              (it, i) =>
                it.group === g && (
                  <div
                    key={it.key}
                    id={`${id}-${i}`}
                    role="option"
                    aria-selected={i === act}
                    data-testid="palette-option"
                    data-group={g}
                    onMouseMove={() => i !== act && setActive(i)}
                    onMouseDown={(e) => e.preventDefault()} // keep focus in the filter
                    onClick={() => choose(it)}
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm shadow-[inset_2px_0_0_transparent] aria-selected:bg-accent-blue/10 aria-selected:shadow-[inset_2px_0_0_var(--accent-blue)]"
                  >
                    <it.icon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 wrap-anywhere">{it.label}</span>
                    {it.hint && <span className="shrink-0 text-xs text-muted-foreground">{it.hint}</span>}
                  </div>
                ),
            )}
          </div>
        ))}
      </div>
      {!shown.length && (
        <p role="status" className="px-4 pb-4 text-sm text-muted-foreground">
          No matches
        </p>
      )}
    </>
  );
}

function Shortcuts({ mac, back }: { mac: boolean; back(): void }) {
  const mod = mac ? "⌘" : "Ctrl";
  const rows = [
    [`${mod} K`, "Open or close this palette"],
    ["/", "Focus the question box"],
    ["Enter", "Ask the question in the box"],
    [`${mod} B`, "Show or hide the sidebar"],
    ["↑ ↓", "Move through the palette"],
    ["Esc", "Close the palette or a sheet"],
  ];
  return (
    <div data-testid="shortcuts" className="grid gap-3 p-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon-sm" aria-label="Back to commands" autoFocus onClick={back}>
          <ArrowLeft />
        </Button>
        <h2 className="text-sm font-medium">Keyboard shortcuts</h2>
      </div>
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-center gap-x-4 gap-y-2 px-2 pb-1 text-sm">
        {rows.map(([keys, what]) => (
          <Fragment key={keys}>
            <dt>
              <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">{keys}</kbd>
            </dt>
            <dd className="text-muted-foreground">{what}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}

/** The sidebar footer's palette button, labelled with its shortcut (⌘K on Apple platforms, Ctrl K elsewhere). */
export function PaletteHint() {
  const setOpen = usePalette();
  const { setOpenMobile } = useSidebar();
  const mac = useIsMac();
  return (
    <Button
      variant="outline"
      size="sm"
      data-testid="palette-hint"
      aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}
      onClick={() => {
        setOpenMobile(false);
        setOpen(true);
      }}
      className="w-full justify-start bg-card text-muted-foreground group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
    >
      <Search />
      <span className="flex-1 text-left group-data-[collapsible=icon]:sr-only">Search</span>
      <kbd aria-hidden className="font-mono text-[11px] group-data-[collapsible=icon]:hidden">
        {mac ? "⌘K" : "Ctrl K"}
      </kbd>
    </Button>
  );
}
