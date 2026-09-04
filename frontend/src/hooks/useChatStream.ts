import { useCallback, useRef, useState } from "react";
import { RequestError, streamSse } from "@/api/client";
import type { ChatStreamDone, RetrievalMode } from "@/api/types";

export interface StreamState {
  streaming: boolean;
  answer: string;
  done: ChatStreamDone | null;
  error: string | null;
}

const INITIAL: StreamState = { streaming: false, answer: "", done: null, error: null };

/**
 * Streams POST /chat/stream via fetch + ReadableStream (§23.2 — not EventSource,
 * so the Authorization header is sent). The partial-`[[` buffering the arch calls
 * for happens at render time in the citation renderer, not here.
 */
export function useChatStream() {
  const [state, setState] = useState<StreamState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => setState(INITIAL), []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState((s) => ({ ...s, streaming: false }));
  }, []);

  const send = useCallback(
    async (args: {
      knowledgeBaseId: string;
      message: string;
      conversationId: string | null;
      mode: RetrievalMode;
    }): Promise<ChatStreamDone | null> => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setState({ streaming: true, answer: "", done: null, error: null });

      let acc = "";
      let finished: ChatStreamDone | null = null;
      try {
        for await (const frame of streamSse(
          "/chat/stream",
          {
            knowledge_base_id: args.knowledgeBaseId,
            message: args.message,
            conversation_id: args.conversationId,
            params: { mode: args.mode },
          },
          ctrl.signal,
        )) {
          if (frame.event === "token") {
            const text = (frame.data as { text?: string }).text ?? "";
            acc += text;
            setState((s) => ({ ...s, answer: acc }));
          } else if (frame.event === "done") {
            finished = frame.data as ChatStreamDone;
            setState((s) => ({ ...s, streaming: false, done: finished, answer: finished!.answer }));
          } else if (frame.event === "error") {
            const msg = (frame.data as { message?: string }).message ?? "generation failed";
            setState((s) => ({ ...s, streaming: false, error: msg }));
          }
        }
      } catch (err) {
        if (ctrl.signal.aborted) return null;
        const msg = err instanceof RequestError ? err.message : "connection lost";
        setState((s) => ({ ...s, streaming: false, error: msg }));
        return null;
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
      }
      return finished;
    },
    [],
  );

  return { ...state, send, cancel, reset };
}
