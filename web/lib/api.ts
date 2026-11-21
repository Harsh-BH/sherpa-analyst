import type { components } from "./api-types";

type S = components["schemas"];
export type Meta = S["Meta"];
export type AskRequest = S["AskRequest"];
export type AnswerBundle = S["AnswerBundle"];
export type View = S["View"];
export type AskResult = S["AskResult"];
export type ExploreForm = S["ExploreForm"];
export type ExplorePlan = S["ExplorePlan"];
export type EvalResponse = S["EvalOk"] | S["EvalMissing"] | S["EvalError"];
export type RunsResponse = S["RunsOk"] | S["RunsUnavailable"];
export type Stage = { name: string; t_ms: number };

/** fetch, with every network failure and non-2xx turned into one message the UI can show. */
async function request(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if (init?.signal?.aborted) throw e;
    throw new Error(`Sherpa API unreachable: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Sherpa API unreachable: HTTP ${res.status}${body ? ` ${body.slice(0, 300)}` : ""}`);
  }
  return res;
}

const getJSON = async <T>(path: string): Promise<T> => (await request(path)).json();

export const getMeta = () => getJSON<Meta>("/api/meta");
export const getEval = () => getJSON<EvalResponse>("/api/eval");
export const getRuns = () => getJSON<RunsResponse>("/api/runs");

export async function explorePlan(form: ExploreForm): Promise<ExplorePlan> {
  const res = await request("/api/explore/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  return res.json();
}

/** POST /api/ask and read its SSE stream: `stage` events as stages start, then one `result`. */
export async function ask(
  req: AskRequest,
  on: { stage(e: Stage): void; result(r: AskResult): void },
  signal: AbortSignal,
): Promise<void> {
  const res = await request("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(req),
    signal,
  });
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  let gotResult = false;
  for (;;) {
    let chunk: ReadableStreamReadResult<string>;
    try {
      chunk = await reader.read();
    } catch (e) {
      if (signal.aborted) throw e;
      break; // the connection dropped: without a result that is "ended early" below
    }
    if (chunk.done) break;
    buf += chunk.value;
    for (let m = /\r?\n\r?\n/.exec(buf); m; m = /\r?\n\r?\n/.exec(buf)) {
      const block = buf.slice(0, m.index);
      buf = buf.slice(m.index + m[0].length);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (event === "stage") on.stage(JSON.parse(data.join("\n")));
      else if (event === "result") {
        gotResult = true;
        on.result(JSON.parse(data.join("\n")));
      }
    }
  }
  if (!gotResult) throw new Error("The answer stream ended early");
}
