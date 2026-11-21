// Self-check for the SSE reader in api.ts (no server needed): pnpm -C web check
import assert from "node:assert/strict";

const { ask } = await import("./api.ts");

const stream = (...chunks) =>
  new Response(new ReadableStream({ start: (c) => (chunks.forEach((x) => c.enqueue(new TextEncoder().encode(x))), c.close()) }));
const run = async (respond) => {
  globalThis.fetch = async () => respond();
  const got = { stages: [], results: [] };
  const on = { stage: (e) => got.stages.push(e), result: (r) => got.results.push(r) };
  await ask({ question: "q", persona: "head" }, on, new AbortController().signal);
  return got;
};

// events split across chunks, with CRLF line ends
const ok = await run(() =>
  stream(': keepalive\n\nevent: stage\ndata: {"name":"plan","t_ms":3}\n', "\n: keepalive\n\nevent: result\r\ndata: ", '{"bundle":1,"view":2}\r\n\r\n'),
);
assert.deepEqual(ok, { stages: [{ name: "plan", t_ms: 3 }], results: [{ bundle: 1, view: 2 }] });

await assert.rejects(run(() => stream('event: stage\ndata: {"name":"plan","t_ms":3}\n\n')), {
  message: "The answer stream ended early",
});
await assert.rejects(run(() => stream("event: result\ndata: {not json\n\n")), {
  message: "The answer stream was malformed",
});
await assert.rejects(run(() => new Response("boom", { status: 500 })), { message: "Sherpa API unreachable: HTTP 500 boom" });
await assert.rejects(
  run(() => Promise.reject(new TypeError("fetch failed"))),
  { message: "Sherpa API unreachable: fetch failed" },
);
console.log("api.check: ok");
