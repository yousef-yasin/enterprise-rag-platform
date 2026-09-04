import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { conversations, kbs } from "@/api/endpoints";
import type { Citation, RetrievalMode } from "@/api/types";
import { useChatStream } from "@/hooks/useChatStream";
import { useUiStore } from "@/stores/ui";
import { Markdown } from "@/components/Markdown";
import { CitationPanel } from "@/components/CitationPanel";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { ErrorBanner } from "@/components/ErrorBanner";

interface Turn {
  role: "user" | "assistant";
  content: string;
  messageId?: string;
  citations?: Citation[];
  abstained?: boolean;
  lowConfidence?: boolean;
  degraded?: Record<string, boolean>;
}

const MODES: RetrievalMode[] = ["hybrid", "dense", "sparse"];

export function ChatPage() {
  const qc = useQueryClient();
  const { activeKbId, setActiveKb, activeConversationId, setActiveConversation, retrievalMode, setRetrievalMode } =
    useUiStore();

  const kbQ = useQuery({ queryKey: ["kbs"], queryFn: kbs.list });
  const convQ = useQuery({ queryKey: ["conversations"], queryFn: conversations.list });
  const historyQ = useQuery({
    queryKey: ["conversation", activeConversationId],
    queryFn: () => conversations.messages(activeConversationId!),
    enabled: !!activeConversationId,
  });

  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const stream = useChatStream();
  const scrollRef = useRef<HTMLDivElement>(null);

  // pick a default KB
  useEffect(() => {
    if (!activeKbId && kbQ.data?.items.length) setActiveKb(kbQ.data.items[0]!.id);
  }, [activeKbId, kbQ.data, setActiveKb]);

  // load persisted conversation into the transcript
  useEffect(() => {
    if (!activeConversationId) {
      setTurns([]);
      return;
    }
    if (historyQ.data) {
      setTurns(
        historyQ.data.items
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            messageId: m.id,
            abstained: m.abstained,
            lowConfidence: m.low_confidence,
            citations: m.citations.map((c, i) => ({
              index: c.citation_index || i + 1,
              chunk_id: null,
              document_id: null,
              filename: c.document_filename ?? "document",
              page_no: null,
              snippet: c.snippet ?? "",
              was_cited: c.was_cited,
              weak: c.weak,
              score: null,
            })),
          })),
      );
    }
  }, [activeConversationId, historyQ.data]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, stream.answer]);

  const lastAssistant = useMemo(
    () => [...turns].reverse().find((t) => t.role === "assistant"),
    [turns],
  );
  const panelCitations = stream.done?.citations ?? lastAssistant?.citations ?? [];

  async function submit(e: FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || !activeKbId || stream.streaming) return;
    setInput("");
    setActiveCite(null);
    setTurns((t) => [...t, { role: "user", content: message }, { role: "assistant", content: "" }]);

    const done = await stream.send({
      knowledgeBaseId: activeKbId,
      message,
      conversationId: activeConversationId,
      mode: retrievalMode,
    });

    if (done) {
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = {
          role: "assistant",
          content: done.answer,
          messageId: done.message_id ?? undefined,
          citations: done.citations,
          abstained: done.abstained,
          lowConfidence: done.low_confidence,
          degraded: done.degraded,
        };
        return copy;
      });
      if (!activeConversationId && done.conversation_id) {
        setActiveConversation(done.conversation_id);
      }
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    }
  }

  function newChat() {
    setActiveConversation(null);
    setTurns([]);
    stream.reset();
  }

  return (
    <div className="split">
      <div className="chat">
        <div>
          <div className="row" style={{ marginBottom: 12 }}>
            <select
              style={{ width: 220 }}
              value={activeKbId ?? ""}
              onChange={(e) => {
                setActiveKb(e.target.value);
                newChat();
              }}
            >
              <option value="" disabled>
                Select a knowledge base
              </option>
              {kbQ.data?.items.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <select
              style={{ width: 120 }}
              value={retrievalMode}
              onChange={(e) => setRetrievalMode(e.target.value as RetrievalMode)}
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <select
              className="grow"
              value={activeConversationId ?? ""}
              onChange={(e) => setActiveConversation(e.target.value || null)}
            >
              <option value="">New conversation</option>
              {convQ.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <button onClick={newChat}>New</button>
          </div>
          <ErrorBanner error={stream.error ? new Error(stream.error) : null} />
        </div>

        <div className="chat-scroll" ref={scrollRef}>
          {turns.length === 0 && (
            <p className="muted">Ask a question grounded in this knowledge base.</p>
          )}
          {turns.map((turn, i) => {
            const isLast = i === turns.length - 1;
            const streamingThis = isLast && turn.role === "assistant" && stream.streaming;
            return (
              <div className={`msg ${turn.role}`} key={i}>
                <div className="who">{turn.role === "user" ? "You" : "Assistant"}</div>
                <div className="bubble">
                  {turn.role === "assistant" ? (
                    <>
                      <Markdown
                        source={streamingThis ? stream.answer : turn.content}
                        activeCitation={activeCite}
                        onCitationClick={(n) => setActiveCite((cur) => (cur === n ? null : n))}
                      />
                      {streamingThis && <span className="muted">▍</span>}
                      {!streamingThis && (
                        <div className="row" style={{ marginTop: 8, gap: 6 }}>
                          {turn.abstained && <span className="pill warn">abstained</span>}
                          {turn.lowConfidence && <span className="pill warn">low confidence</span>}
                          {turn.degraded &&
                            Object.entries(turn.degraded)
                              .filter(([, v]) => v)
                              .map(([k]) => (
                                <span className="pill" key={k}>
                                  degraded: {k}
                                </span>
                              ))}
                        </div>
                      )}
                      {!streamingThis && turn.messageId && (
                        <FeedbackButtons messageId={turn.messageId} />
                      )}
                    </>
                  ) : (
                    <span>{turn.content}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <form className="composer" onSubmit={submit}>
          <textarea
            className="grow"
            placeholder="Ask a question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(e as unknown as FormEvent);
              }
            }}
          />
          {stream.streaming ? (
            <button type="button" onClick={stream.cancel}>
              Stop
            </button>
          ) : (
            <button className="primary" type="submit" disabled={!activeKbId}>
              Send
            </button>
          )}
        </form>
      </div>

      <aside className="card" style={{ overflowY: "auto" }}>
        <h2>Sources</h2>
        <CitationPanel citations={panelCitations} active={activeCite} onHover={setActiveCite} />
      </aside>
    </div>
  );
}
