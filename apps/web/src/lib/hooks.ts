"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { APIError, Client, id } from "./api";
import { eventDecision, SSEDecoder } from "./events";
import type { Snapshot } from "./types";
export function useResource<T>(client: Client, path: string | null) {
  const [value, setValue] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((r) => r + 1), []);
  useEffect(() => {
    const abort = new AbortController();
    setValue(undefined);
    setError(undefined);
    setLoading(true);
    if (!path) {
      setLoading(false);
      return;
    }
    client
      .read<T>(path, abort.signal)
      .then((v) => {
        if (!abort.signal.aborted) setValue(v);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [client, path, revision]);
  return { value, error, loading, refresh };
}
export function useAction() {
  const lock = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function act(task: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await task();
    } catch (e) {
      if (mounted.current) setError(e);
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return { busy, error, act, clear: () => setError(undefined) };
}
export function useExperiment(client: Client, experiment: string) {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState<unknown>();
  const [connection, setConnection] = useState<
    "connecting" | "live" | "offline" | "denied"
  >("connecting");
  const [generation, setGeneration] = useState(0);
  const [resynced, setResynced] = useState(false);
  const refresh = useCallback(() => setGeneration((g) => g + 1), []);
  useEffect(() => {
    const abort = new AbortController();
    let cursor = 0;
    let delay = 1000;
    const path = `/experiments/${id(experiment)}`;
    setConnection("connecting");
    setError(undefined);
    async function reload() {
      const current = await client.read<Snapshot>(
        path + "/snapshot",
        abort.signal,
      );
      if (abort.signal.aborted) return;
      cursor = current.event_cursor;
      setSnapshot(current);
      setError(undefined);
    }
    async function sleep(ms: number) {
      await new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          abort.signal.removeEventListener("abort", finish);
          resolve();
        };
        const timer = setTimeout(finish, ms);
        abort.signal.addEventListener("abort", finish, { once: true });
        if (abort.signal.aborted) finish();
      });
    }
    async function run() {
      while (!abort.signal.aborted) {
        try {
          await reload();
          const response = await fetch("/api/v1" + path + "/events", {
            headers: { ...client.headers(), "Last-Event-ID": String(cursor) },
            signal: abort.signal,
            cache: "no-store",
          });
          if (!response.ok) {
            const result = await response.json();
            throw new APIError(
              result.error?.code || "SERVICE_UNAVAILABLE",
              response.status,
              result.error?.request_id,
            );
          }
          if (!response.body) throw new Error("Missing stream");
          setConnection("live");
          delay = 1000;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          const frames = new SSEDecoder();
          try {
            while (!abort.signal.aborted) {
              const chunk = await reader.read();
              if (chunk.done) break;
              for (const frame of frames.push(
                decoder.decode(chunk.value, { stream: true }),
              )) {
                if (frame.event === "stream.error") {
                  const problem = JSON.parse(frame.data);
                  throw new APIError(
                    problem.code,
                    problem.code === "UNAUTHENTICATED"
                      ? 401
                      : problem.code === "FORBIDDEN"
                        ? 403
                        : 409,
                  );
                }
                const decision = eventDecision(frame, cursor);
                if (decision !== "skip") {
                  if (decision === "resync") setResynced(true);
                  await reload();
                }
              }
            }
          } finally {
            await reader.cancel().catch(() => {});
          }
          await sleep(1000);
        } catch (e) {
          if (abort.signal.aborted) return;
          setError(e);
          setConnection("offline");
          if (e instanceof APIError && [401, 403].includes(e.status)) {
            setSnapshot(undefined);
            setConnection("denied");
            if (e.status === 401) client.invalidate();
            return;
          }
          if (e instanceof APIError && e.code === "RESYNC_REQUIRED")
            setResynced(true);
          await sleep(delay);
          delay = Math.min(delay * 2, 15000);
        }
      }
    }
    void run();
    return () => abort.abort();
  }, [client, experiment, generation]);
  return { snapshot, error, connection, refresh, resynced };
}
