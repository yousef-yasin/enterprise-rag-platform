import { useEffect, useRef, useState } from "react";
import { currentAccessToken } from "@/api/client";
import { documents } from "@/api/endpoints";
import type { DocumentStatus } from "@/api/types";

const TERMINAL: DocumentStatus[] = ["ready", "partially_indexed", "failed"];

interface JobState {
  status: DocumentStatus | null;
  stage: string | null;
  connected: boolean;
}

/**
 * Follows GET /documents/{id}/status/stream (SSE, `data:`-only frames) until the
 * document reaches a terminal state, then stops. Falls back to nothing on error
 * (the Documents page also polls via react-query as a backstop).
 */
export function useJobStatus(documentId: string | null, enabled: boolean): JobState {
  const [state, setState] = useState<JobState>({ status: null, stage: null, connected: false });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!documentId || !enabled) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let cancelled = false;

    (async () => {
      try {
        const token = currentAccessToken();
        const res = await fetch(documents.statusStreamPath(documentId), {
          credentials: "include",
          headers: token ? { authorization: `Bearer ${token}` } : {},
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) return;
        setState((s) => ({ ...s, connected: true }));
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buf.indexOf("\n\n")) !== -1) {
            const raw = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            const dataLine = raw.split("\n").find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            const payload = JSON.parse(dataLine.slice(5).trim()) as {
              status?: DocumentStatus;
              stage?: string | null;
              event?: string;
            };
            if (payload.event === "done") {
              ctrl.abort();
              return;
            }
            if (payload.status) {
              setState({ status: payload.status, stage: payload.stage ?? null, connected: true });
              if (TERMINAL.includes(payload.status)) {
                ctrl.abort();
                return;
              }
            }
          }
        }
      } catch {
        /* aborted or network error — react-query polling covers it */
      } finally {
        setState((s) => ({ ...s, connected: false }));
      }
    })();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [documentId, enabled]);

  return state;
}
