"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { THEMES, getTheme, setTheme, subscribeTheme } from "@/lib/theme";

const ICON = { light: Sun, dark: Moon, system: Monitor };

/** Cycles light -> dark -> system. */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getTheme, () => "system" as const);
  const Icon = ICON[theme];
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      data-testid="theme-toggle"
      aria-label={`Theme: ${theme}`}
      title={`Theme: ${theme}`}
      onClick={() => setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length])}
    >
      <Icon className="size-4" />
    </Button>
  );
}
