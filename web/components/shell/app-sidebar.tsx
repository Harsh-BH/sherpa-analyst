"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { TriangleAlert } from "lucide-react";

import { RecentRuns } from "@/components/shell/recent-runs";
import { PaletteHint } from "@/components/shell/command-palette";
import { NAV } from "@/components/shell/nav";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useSherpa } from "@/lib/store";

export function AppSidebar() {
  const { meta, metaError, persona, setPersona, run } = useSherpa();
  const pathname = usePathname();
  const bundle = run.result?.bundle;
  const { isMobile, setOpenMobile } = useSidebar();
  const backend = bundle?.llm_usage.backend;
  // The latest run's own provenance wins; before any run, what the API reports now.
  const footer = [
    ["data", bundle?.data_version ?? meta?.data_version],
    ["as of", run.result?.view.as_of ?? meta?.as_of],
    ["llm", typeof backend === "string" ? backend : meta?.llm_backend],
  ];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-3">
        <div className="flex h-8 items-center gap-2 px-1.5 font-semibold">
          <span
            aria-hidden
            className="size-5 shrink-0 rounded-[6px] bg-linear-135 from-accent-blue to-[color-mix(in_oklab,var(--accent-blue),black_35%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.25)]"
          />
          <span className="group-data-[collapsible=icon]:hidden">Sherpa</span>
        </div>
        <Select value={persona ?? ""} onValueChange={setPersona}>
          <SelectTrigger
            data-testid="persona"
            aria-label="Persona"
            size="sm"
            className="w-full bg-card group-data-[collapsible=icon]:hidden"
          >
            <SelectValue placeholder={metaError ? "Personas unavailable" : "Loading personas"} />
          </SelectTrigger>
          <SelectContent position="popper">
            {meta?.personas.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SidebarHeader>
      {/* On phones the sidebar is a sheet: following a link or a menu button inside it closes it. */}
      <SidebarContent
        onClick={(e) => isMobile && (e.target as Element).closest("a, [data-sidebar=menu-button]") && setOpenMobile(false)}
      >
        <SidebarGroup>
          <SidebarMenu>
            {NAV.map(({ href, label, icon: Icon }) => (
              <SidebarMenuItem key={href}>
                <SidebarMenuButton
                  asChild
                  isActive={pathname === href}
                  tooltip={label}
                  // accent-tinted pill with a 2px left indicator; the background and colour transition
                  className="relative text-muted-foreground transition-[width,height,padding,color,background-color] duration-200 ease-out before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-accent-blue before:opacity-0 before:transition-opacity data-active:bg-accent-blue/10 data-active:text-foreground data-active:before:opacity-100 data-active:hover:bg-accent-blue/15 data-active:[&_svg]:text-accent-blue"
                >
                  <Link href={href}>
                    <Icon />
                    <span>{label}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
        <RecentRuns />
      </SidebarContent>
      <SidebarFooter>
        <PaletteHint />
        {meta?.fixture_mode && (
          <p className="flex gap-2 px-1.5 text-xs text-warning group-data-[collapsible=icon]:hidden">
            <TriangleAlert className="size-4 shrink-0" />
            <span>
              <b className="font-medium">Fixture mode.</b> Answers are saved bundles, not the live pipeline.
            </span>
          </p>
        )}
        <dl className="grid gap-0.5 px-1.5 font-mono text-xs group-data-[collapsible=icon]:hidden">
          {footer.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="truncate">{v ?? "—"}</dd>
            </div>
          ))}
        </dl>
        <div className="flex items-center justify-between group-data-[collapsible=icon]:flex-col">
          <SidebarTrigger />
          <ThemeToggle />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
