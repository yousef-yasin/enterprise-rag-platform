import { useState } from "react";
import { conversations } from "@/api/endpoints";

export function FeedbackButtons({ messageId }: { messageId: string }) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [busy, setBusy] = useState(false);

  async function vote(rating: "up" | "down") {
    if (busy) return;
    setBusy(true);
    try {
      await conversations.feedback(messageId, rating);
      setSent(rating);
    } catch {
      /* non-critical */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="row" style={{ marginTop: 6, gap: 6 }}>
      <button
        aria-label="helpful"
        disabled={busy}
        className={sent === "up" ? "primary" : undefined}
        onClick={() => void vote("up")}
      >
        👍
      </button>
      <button
        aria-label="not helpful"
        disabled={busy}
        className={sent === "down" ? "primary" : undefined}
        onClick={() => void vote("down")}
      >
        👎
      </button>
      {sent ? <span className="muted">thanks for the feedback</span> : null}
    </div>
  );
}
