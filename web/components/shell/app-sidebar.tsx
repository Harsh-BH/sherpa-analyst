"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, FlaskConical, History, MessageSquare, TriangleAlert } from "lucide-react";

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
} from "@/components/ui/sidebar";
import { useSherpa } from "@/lib/store";

const NAV = [
  { href: "/", label: "Ask", icon: MessageSquare },
  { href: "/explore", label: "Explore", icon: Compass },
  { href: "/eval", label: "Eval", icon: FlaskConical },
  { href: "/runs", label: "Runs", icon: History },
];

export function AppSidebar() {
  const { meta, persona, setPersona, run } = useSherpa();
  const pathname = usePathname();
  const bundle = run.result?.bundle;
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
          <span aria-hidden className="size-5 shrink-0 rounded-[5px] bg-foreground" />
          <span className="group-data-[collapsible=icon]:hidden">Sherpa</span>
        </div>
        <Select value={persona ?? ""} onValueChange={setPersona}>
          <SelectTrigger
            data-testid="persona"
            aria-label="Persona"
            size="sm"
            className="w-full bg-card group-data-[collapsible=icon]:hidden"
          >
            <SelectValue placeholder="Loading personas" />
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
      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            {NAV.map(({ href, label, icon: Icon }) => (
              <SidebarMenuItem key={href}>
                <SidebarMenuButton
                  asChild
                  isActive={pathname === href}
                  tooltip={label}
                  className="text-muted-foreground data-active:text-foreground data-active:ring-1 data-active:ring-sidebar-border"
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
      </SidebarContent>
      <SidebarFooter>
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
