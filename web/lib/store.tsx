"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import * as api from "@/lib/api";

export type Run = {
  status: "idle" | "running" | "done" | "failed";
  question?: string;
  stages: api.Stage[];
  result?: api.AskResult;
  error?: string;
};

export type AskOptions = Pick<api.AskRequest, "plan" | "patch" | "fixture"> & { persona?: string };

type Sherpa = {
  meta: api.Meta | null;
  persona: string | null;
  setPersona(key: string): void;
  run: Run;
  ask(question: string, opts?: AskOptions): Promise<void>;
  selectedEvidenceId: string | null;
  selectEvidence(id: string | null): void;
};

const PERSONA_KEY = "sherpa.persona";
const Ctx = createContext<Sherpa | null>(null);

function storedPersona(): string | null {
  try {
    return localStorage.getItem(PERSONA_KEY);
  } catch {
    return null;
  }
}

export function SherpaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<api.Meta | null>(null);
  const [persona, setPersonaState] = useState<string | null>(null);
  const [run, setRun] = useState<Run>({ status: "idle", stages: [] });
  const [selectedEvidenceId, selectEvidence] = useState<string | null>(null);
  const runCounter = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getMeta()
      .then((m) => {
        if (!live) return;
        setMeta(m);
        const saved = storedPersona();
        setPersonaState((p) => {
          const known = (k: string | null) => k !== null && m.personas.some((x) => x.key === k);
          return known(p) ? p : known(saved) ? saved : m.default_persona;
        });
      })
      .catch(() => {}); // no meta: the sidebar shows dashes and the first ask reports the API as unreachable
    return () => {
      live = false;
      controller.current?.abort();
    };
  }, []);

  const setPersona = useCallback((key: string) => {
    setPersonaState(key);
    try {
      localStorage.setItem(PERSONA_KEY, key);
    } catch {}
  }, []);

  const ask = useCallback(
    async (question: string, opts: AskOptions = {}) => {
      const id = ++runCounter.current; // the latest ask wins; callbacks from older runs are dropped
      const live = () => id === runCounter.current;
      controller.current?.abort();
      const c = (controller.current = new AbortController());
      setRun({ status: "running", question, stages: [] });
      selectEvidence(null);
      const { persona: who, ...rest } = opts;
      try {
        await api.ask(
          { question, persona: who ?? persona ?? meta?.default_persona ?? "", ...rest },
          {
            stage: (e) => live() && setRun((r) => ({ ...r, stages: [...r.stages, e] })),
            result: (result) => live() && setRun((r) => ({ ...r, status: "done", result })),
          },
          c.signal,
        );
      } catch (e) {
        if (live()) setRun((r) => ({ ...r, status: "failed", error: e instanceof Error ? e.message : String(e) }));
      }
    },
    [persona, meta],
  );

  const value = useMemo(
    () => ({ meta, persona, setPersona, run, ask, selectedEvidenceId, selectEvidence }),
    [meta, persona, setPersona, run, ask, selectedEvidenceId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSherpa(): Sherpa {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSherpa needs <SherpaProvider>");
  return s;
}
