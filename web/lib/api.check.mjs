// Self-check for the SSE reader in api.ts (no server needed): pnpm -C web check
import assert from "node:assert/strict";

const { ask } = await import("./api.ts");

const stream = (...chunks) =>
  new Response(new ReadableStream({ start: (c) => (chunks.forEach((x) => c.enqueue(new TextEncoder().encode(x))), c.close()) }));
const run = async (respond) => {
  globalThis.fetch = async () => respond();
  const got = { stages: [], partials: [], results: [] };
  const on = { stage: (e) => got.stages.push(e), partial: (r) => got.partials.push(r), result: (r) => got.results.push(r) };
  await ask({ question: "q", persona: "head" }, on, new AbortController().signal);
  return got;
};

// events split across chunks, with CRLF line ends
const ok = await run(() =>
  stream(': keepalive\n\nevent: stage\ndata: {"name":"plan","t_ms":3}\n', "\n: keepalive\n\nevent: result\r\ndata: ", '{"bundle":1,"view":2}\r\n\r\n'),
);
assert.deepEqual(ok, { stages: [{ name: "plan", t_ms: 3 }], partials: [], results: [{ bundle: 1, view: 2 }] });

// a partial (the numbers before the narrative) arrives between stages, before the result
const withPartial = await run(() =>
  stream(
    'event: stage\ndata: {"name":"dq","t_ms":5}\n\nevent: partial\ndata: {"bundle":1,"view":{"partial":true}}\n\n',
    'event: stage\ndata: {"name":"narrate","t_ms":9}\n\nevent: result\ndata: {"bundle":1,"view":{"partial":false}}\n\n',
  ),
);
assert.deepEqual(withPartial, {
  stages: [{ name: "dq", t_ms: 5 }, { name: "narrate", t_ms: 9 }],
  partials: [{ bundle: 1, view: { partial: true } }],
  results: [{ bundle: 1, view: { partial: false } }],
});
// a partial is not a result: a stream that stops after it ended early
await assert.rejects(run(() => stream('event: partial\ndata: {"bundle":1,"view":{"partial":true}}\n\n')), {
  message: "The answer stream ended early",
});

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

// getRun: the API's bare 404 (missing, or another persona's run) is null; any other failure still throws
const { getRun } = await import("./api.ts");
globalThis.fetch = async () => new Response('{"detail":"Not Found"}', { status: 404 });
assert.equal(await getRun("r1", "head"), null);
globalThis.fetch = async () => new Response("boom", { status: 500 });
await assert.rejects(getRun("r1", "head"), { message: "Sherpa API unreachable: HTTP 500 boom" });
console.log("api.check: ok");
