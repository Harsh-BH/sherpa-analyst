"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import * as api from "@/lib/api";

export type Run = {
  status: "idle" | "running" | "done" | "failed";
  question?: string;
  /** `at`: ms after the ask when the stage reached the browser (the trace's data-stage-times). */
  stages: (api.Stage & { at: number })[];
  resultAt?: number;
  /** The numbers before the narrative (`view.partial`): drawn while running, until the result replaces it. */
  partial?: api.AskResult;
  result?: api.AskResult;
  error?: string;
};

export type AskOptions = Pick<api.AskRequest, "plan" | "patch" | "fixture"> & { persona?: string };

type Sherpa = {
  meta: api.Meta | null;
  metaError: string | null;
  persona: string | null;
  setPersona(key: string): void;
  /** The question box. Kept here so it survives the centre remounting when the window crosses 1280 px.
   * ponytail: one context, so each keystroke re-renders every consumer; split the context if typing ever lags. */
  draft: string;
  setDraft(q: string): void;
  run: Run;
  ask(question: string, opts?: AskOptions): Promise<void>;
  /** The persona's reopenable runs, newest first (GET /api/history); refetched on persona change and after each run. */
  history: api.HistoryItem[];
  /** Reopen a saved run like a finished ask (no stages stream) at /?run=<id>; from another page it navigates there. */
  openRun(runId: string): Promise<void>;
  selectedEvidenceId: string | null;
  /** Selecting evidence also opens the rail's Evidence tab, even when that id was already selected. */
  selectEvidence(id: string | null): void;
  railTab: string;
  setRailTab(tab: string): void;
  /** The rail as a sheet below 1280 px: an evidence chip asks for it to open. */
  railOpen: boolean;
  setRailOpen(open: boolean): void;
};

const PERSONA_KEY = "sherpa.persona";
const NO_HISTORY: api.HistoryItem[] = [];
const Ctx = createContext<Sherpa | null>(null);

function storedPersona(): string | null {
  try {
    return localStorage.getItem(PERSONA_KEY);
  } catch {
    return null;
  }
}

/** The current persona if meta knows it, else the remembered one, else the default. */
function knownPersona(m: api.Meta, current: string | null): string {
  const known = (k: string | null): k is string => k !== null && m.personas.some((x) => x.key === k);
  const saved = storedPersona();
  return known(current) ? current : known(saved) ? saved : m.default_persona;
}

export function SherpaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<api.Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [persona, setPersonaState] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [run, setRun] = useState<Run>({ status: "idle", stages: [] });
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [railTab, setRailTab] = useState("evidence");
  const [railOpen, setRailOpen] = useState(false);
  const [recent, setRecent] = useState<{ persona: string; items: api.HistoryItem[] }>({ persona: "", items: [] });
  const [finished, countFinished] = useReducer((n: number) => n + 1, 0); // asks that reached their result
  const router = useRouter();
  const pathname = usePathname();
  const runCounter = useRef(0);
  const controller = useRef<AbortController | null>(null);

  /** Fetch meta and settle the persona. Throws the API's message; the page shows it as metaError. */
  const loadMeta = useCallback(async (): Promise<api.Meta> => {
    try {
      const m = await api.getMeta();
      setMeta(m);
      setMetaError(null);
      setPersonaState((p) => knownPersona(m, p));
      return m;
    } catch (e) {
      setMetaError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  }, []);

  useEffect(() => {
    loadMeta().catch(() => {}); // shown through metaError; the next ask retries
    return () => controller.current?.abort();
  }, [loadMeta]);

  const selectEvidence = useCallback((id: string | null) => {
    setSelectedEvidenceId(id);
    if (id) setRailTab("evidence");
  }, []);

  const setPersona = useCallback((key: string) => {
    setPersonaState(key);
    try {
      localStorage.setItem(PERSONA_KEY, key);
    } catch {}
  }, []);

  const ask = useCallback(
    async (raw: string, opts: AskOptions = {}) => {
      const question = raw.trim();
      if (!question) return; // the API would 422 an empty question
      const id = ++runCounter.current; // the latest ask wins; callbacks from older runs are dropped
      const live = () => id === runCounter.current;
      controller.current?.abort();
      const c = (controller.current = new AbortController());
      const t0 = performance.now();
      const since = () => Math.round(performance.now() - t0);
      setDraft(question);
      setRun({ status: "running", question, stages: [] });
      selectEvidence(null);
      const url = new URL(window.location.href); // a new answer is no longer the reopened run
      if (url.searchParams.has("run")) {
        url.searchParams.delete("run");
        window.history.replaceState(null, "", url);
      }
      const { persona: who, ...rest } = opts;
      try {
        // Never send an empty persona: without meta, fetch it now (and fail with its message).
        const p = who ?? persona ?? knownPersona(await loadMeta(), null);
        if (!live()) return;
        await api.ask(
          { question, persona: p, ...rest },
          {
            stage: (e) => live() && setRun((r) => ({ ...r, stages: [...r.stages, { ...e, at: since() }] })),
            partial: (partial) => live() && setRun((r) => ({ ...r, partial })),
            result: (result) => {
              if (!live()) return;
              setRun((r) => ({ ...r, status: "done", result, resultAt: since() }));
              countFinished(); // the run log has a new run: Recent refetches
            },
          },
          c.signal,
        );
      } catch (e) {
        if (live()) setRun((r) => ({ ...r, status: "failed", error: e instanceof Error ? e.message : String(e) }));
      }
    },
    [persona, loadMeta, selectEvidence],
  );

  const openRun = useCallback(
    async (runId: string) => {
      if (pathname !== "/") {
        router.push(`/?run=${encodeURIComponent(runId)}`); // the Ask page opens ?run= on load
        return;
      }
      const id = ++runCounter.current;
      const live = () => id === runCounter.current;
      controller.current?.abort();
      selectEvidence(null);
      try {
        const p = persona ?? knownPersona(await loadMeta(), null);
        const result = await api.getRun(runId, p);
        if (!live()) return;
        if (!result) {
          setRun({ status: "failed", stages: [], error: `Run ${runId} was not found for this persona.` });
          return;
        }
        setDraft(result.bundle.question);
        setRun({ status: "done", question: result.bundle.question, stages: [], result });
        window.history.replaceState(null, "", `/?run=${encodeURIComponent(runId)}`);
      } catch (e) {
        if (live()) setRun({ status: "failed", stages: [], error: e instanceof Error ? e.message : String(e) });
      }
    },
    [persona, loadMeta, selectEvidence, router, pathname],
  );

  // Recent runs: on persona change and after each finished ask (not when one starts, nor on reopening a run, which
  // adds none); kept with the persona they are for.
  useEffect(() => {
    if (!persona) return;
    let live = true;
    api.getHistory(persona).then(
      (items) => live && setRecent({ persona, items }),
      () => live && setRecent({ persona, items: [] }), // no run log (no DB): the Recent list hides
    );
    return () => {
      live = false;
    };
  }, [persona, finished]);
  const history = recent.persona === persona ? recent.items : NO_HISTORY;

  const value = useMemo(
    () => ({
      meta,
      metaError,
      persona,
      setPersona,
      draft,
      setDraft,
      run,
      ask,
      history,
      openRun,
      selectedEvidenceId,
      selectEvidence,
      railTab,
      setRailTab,
      railOpen,
      setRailOpen,
    }),
    [meta, metaError, persona, setPersona, draft, run, ask, history, openRun, selectedEvidenceId, selectEvidence, railTab, railOpen],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSherpa(): Sherpa {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSherpa needs <SherpaProvider>");
  return s;
}
