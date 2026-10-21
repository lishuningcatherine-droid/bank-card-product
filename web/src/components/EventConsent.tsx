"use client";

import { useEffect, useState } from "react";

import { anonId, deleteMyData, type EventConfig, getEventConfig, optIn, optOut } from "@/lib/ranking-events";

/** Opt-in control for anonymous ranking events. Hidden unless the operator enabled logging; off until turned on. */
export function EventConsent({ detailed = false }: { detailed?: boolean }) {
  const [cfg, setCfg] = useState<EventConfig | null>(null);
  const [on, setOn] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void getEventConfig().then((c) => {
      if (!live) return;
      setCfg(c);
      setOn(anonId() !== null);
    });
    return () => {
      live = false;
    };
  }, []);
  if (!cfg?.enabled) {
    return detailed ? <p className="text-sm">Anonymous ranking events are not being collected. Nothing about your visits is recorded.</p> : null;
  }
  return (
    <section aria-labelledby="consent-h" className="rounded-md border border-border p-4 text-sm">
      <h2 id="consent-h" className="text-base">Help improve rankings (optional)</h2>
      <p className="mt-1">
        Off unless you turn it on. If on, we record anonymously which results were shown to you and which you opened —
        never your answers. Records are deleted after {cfg.retention_days} days, or right away if you ask.
      </p>
      {detailed ? (
        <div className="mt-2 grid gap-3 md:grid-cols-2">
          <div><p className="font-medium text-ink-900">Recorded</p><ul className="list-disc pl-5">{cfg.stored.map((s) => <li key={s}>{s}</li>)}</ul></div>
          <div><p className="font-medium text-ink-900">Never recorded</p><ul className="list-disc pl-5">{cfg.never_stored.map((s) => <li key={s}>{s}</li>)}</ul></div>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="font-medium text-ink-900">Status: {on ? "on" : "off"}</span>
        {on ? (
          <button type="button" className="min-h-11 rounded-md border border-border px-4 hover:border-border-strong" onClick={() => { optOut(); setOn(false); setMsg("Turned off. Nothing more will be recorded."); }}>Turn off</button>
        ) : (
          <button type="button" className="min-h-11 rounded-md border border-border px-4 hover:border-border-strong" onClick={() => { if (optIn()) { setOn(true); setMsg("Turned on for this browser."); } }}>Turn on</button>
        )}
        {on ? (
          <button type="button" className="min-h-11 rounded-md border border-border px-4 hover:border-border-strong" onClick={() => { void deleteMyData().then((n) => { if (n === null) { setMsg("We couldn't delete your data right now. Please try again."); } else { setOn(false); setMsg(`Deleted ${n} record${n === 1 ? "" : "s"} and turned off.`); } }); }}>Delete my data</button>
        ) : null}
      </div>
      {msg ? <p className="mt-2" role="status">{msg}</p> : null}
    </section>
  );
}
