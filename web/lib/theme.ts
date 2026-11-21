export type Theme = "light" | "dark" | "system";

export const THEMES: Theme[] = ["light", "dark", "system"];
const KEY = "sherpa.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Runs in <head> before paint, so the first frame already has the right theme. Storage may throw: then follow the OS. */
export const THEME_SCRIPT = `(function(){var t;try{t=localStorage.getItem("${KEY}")}catch(e){}var d=t==="dark"||(t!=="light"&&matchMedia("${DARK_QUERY}").matches);document.documentElement.classList.toggle("dark",d)})()`;

let current: Theme | null = null; // the session's theme: still works when storage is blocked, just not remembered
const listeners = new Set<() => void>();

function stored(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return THEMES.includes(t as Theme) ? (t as Theme) : "system";
  } catch {
    return "system";
  }
}

function apply(t: Theme) {
  const dark = t === "dark" || (t === "system" && matchMedia(DARK_QUERY).matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function getTheme(): Theme {
  return (current ??= stored());
}

export function setTheme(t: Theme) {
  current = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {}
  apply(t);
  listeners.forEach((l) => l());
}

/** For useSyncExternalStore; also re-applies "system" when the OS switches. */
export function subscribeTheme(onChange: () => void) {
  const mq = matchMedia(DARK_QUERY);
  const onOs = () => {
    if (getTheme() === "system") apply("system");
    onChange();
  };
  listeners.add(onChange);
  mq.addEventListener("change", onOs);
  return () => {
    listeners.delete(onChange);
    mq.removeEventListener("change", onOs);
  };
}
