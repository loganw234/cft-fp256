// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The driver that turns demos_core.js's step machines into a running
// job: instantiate the module once, run one panel configuration to
// completion, post progress in batches, and stop when told to.
//
// It is written to be scope-agnostic. Inside a Web Worker it installs
// an onmessage handler and posts back; on a page where a Worker cannot
// be constructed - a file:// document in a browser that refuses blob:
// workers is the case that matters - the page evaluates this same
// source in its own scope and calls CftDemosDriver.handle() directly
// with a callback. One driver, so the fallback cannot drift from the
// thing it falls back from.
//
// The yielding is what makes both work: the loop hands control back
// every hundred milliseconds or so, which lets a worker see a cancel
// message and lets a main-thread fallback repaint.

(function (root) {
  "use strict";

  const D = root.CftDemos;
  if (!D) throw new Error("demos_worker.js loaded without demos_core.js");

  let modulePromise = null;
  function getModule() {
    if (!modulePromise) {
      if (typeof createCftModule !== "function")
        throw new Error("the wasm loader (createCftModule) is not here");
      modulePromise = createCftModule({});
    }
    return modulePromise;
  }

  const now = () => (typeof performance !== "undefined"
                     ? performance.now() : Date.now());
  const yieldToHost = () => new Promise((r) => setTimeout(r, 0));

  let cancelled = false;
  let busy = false;

  /** What a progress message carries for each panel: the newly
   *  computed part, never the whole state, so a long run does not
   *  re-post megabytes forty times a second. */
  function collector(panelId) {
    switch (panelId) {
      case "collatz": {
        const rows = [];
        let trail = 0;
        return {
          take(e) {
            if (!e) return;
            if (e.rows) for (const r of e.rows)
              rows.push({ n0: r.n0, steps: String(r.steps), peak: r.peak,
                          final: r.final, escaped: r.escaped });
            if (e.trail) trail = e.trail;
          },
          drain() { const out = { rows: rows.splice(0), trail }; return out; },
        };
      }
      case "zoom": {
        let pending = null;
        return {
          take(e, r) {
            if (!e) return;
            if (e.rowsDone !== undefined && e.iter) {
              const from = e.from, to = e.to;
              pending = {
                phase: r.phase, rowsDone: e.rowsDone, from, to,
                iter: Array.from(e.iter.subarray(from, to)),
                kind: Array.from(e.kind.subarray(from, to)),
              };
            } else if (e.orbit !== undefined) {
              pending = { phase: r.phase, orbit: e.orbit, k: r.k };
            }
          },
          drain() { const p = pending; pending = null; return p || {}; },
        };
      }
      case "orbits": {
        const samples = [];
        return {
          take(e) { if (e && e.sample) samples.push(e.sample); },
          drain() { return { samples: samples.splice(0) }; },
        };
      }
      case "enclose": {
        const records = [];
        return {
          take(e) { if (e && e.records) for (const r of e.records) records.push(r); },
          drain() { return { records: records.splice(0) }; },
        };
      }
      case "mersenne": {
        let last = null;
        const records = [];
        return {
          take(e) {
            if (!e) return;
            last = { exponent: e.exponent, step: e.step, need: e.need,
                     b: e.b, L: e.L, d: e.d };
            if (e.record) records.push(e.record);
          },
          drain() { return { at: last, records: records.splice(0) }; },
        };
      }
      default:
        return { take() {}, drain() { return {}; } };
    }
  }

  async function runOne(msg, post) {
    const panel = D.PANELS[msg.panel];
    if (!panel) throw new Error(`no panel ${msg.panel}`);
    const runSpec = panel.runs.find((r) => r.name === msg.run);
    if (!runSpec) throw new Error(`no run ${msg.run} in panel ${msg.panel}`);
    const cfg = Object.assign({}, runSpec.cfg, msg.overrides || {});
    const M = await getModule();
    const C = D.createCft(M);
    let result = null, error = null;
    const coll = collector(msg.panel);
    const t0 = now();
    let last = t0;
    try {
      const job = panel.create(C, cfg);
      post({ type: "started", panel: msg.panel, run: msg.run, cfg,
             command: panel.command(cfg), token: msg.token,
             backend: C.backend, abi: C.abiVersion() });
      for (;;) {
        const r = job.step();
        coll.take(r.emitted, r);
        if (r.done) break;
        const t = now();
        if (t - last >= 100) {
          post({ type: "progress", panel: msg.panel, run: msg.run,
                 token: msg.token, progress: r.progress || 0,
                 phase: r.phase, seconds: (t - t0) / 1000,
                 data: coll.drain() });
          last = t;
          await yieldToHost();
          if (cancelled) {
            post({ type: "cancelled", panel: msg.panel, run: msg.run,
                   token: msg.token, seconds: (now() - t0) / 1000 });
            return;
          }
        }
      }
      result = job.result();
      result.seconds = (now() - t0) / 1000;
      result.rate = result.seconds > 0 ? result.work / result.seconds : 0;
      result.command = panel.command(cfg);
      result.cfg = cfg;
      result.backend = C.backend;
      result.data = coll.drain();
    } catch (err) {
      error = err;
    } finally {
      try { C.close(C.dev); C.freeAll(); } catch (e) { /* teardown */ }
    }
    if (error) throw error;
    post({ type: "done", panel: msg.panel, run: msg.run, token: msg.token,
           result });
  }

  const Driver = {
    async handle(msg, post) {
      if (msg.type === "cancel") { cancelled = true; return; }
      if (msg.type !== "start") return;
      if (busy) {
        post({ type: "error", token: msg.token,
               message: "a run is already in flight" });
        return;
      }
      busy = true;
      cancelled = false;
      try {
        for (const run of msg.runs) {
          if (cancelled) break;
          await runOne({ type: "start", panel: msg.panel, run,
                         overrides: msg.overrides, token: msg.token }, post);
        }
        post({ type: "idle", token: msg.token, panel: msg.panel });
      } catch (err) {
        post({ type: "error", token: msg.token, panel: msg.panel,
               message: String(err && err.message ? err.message : err),
               stack: String(err && err.stack || "") });
      } finally {
        busy = false;
      }
    },
    cancel() { cancelled = true; },
    isBusy() { return busy; },
  };

  root.CftDemosDriver = Driver;

  // Only inside a real Worker; on the main-thread fallback the page
  // calls handle() itself and window.onmessage stays untouched.
  const inWorker = typeof WorkerGlobalScope !== "undefined" &&
                   typeof self !== "undefined" && self instanceof WorkerGlobalScope;
  if (inWorker) {
    self.onmessage = (ev) => {
      Driver.handle(ev.data, (m) => self.postMessage(m));
    };
    self.postMessage({ type: "ready" });
  }
})(typeof self !== "undefined" ? self : globalThis);
