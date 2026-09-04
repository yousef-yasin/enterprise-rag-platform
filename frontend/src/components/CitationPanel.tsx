import type { Citation } from "@/api/types";

interface Props {
  citations: Citation[];
  active: number | null;
  onHover: (n: number | null) => void;
}

// Source-panel content is rendered as PLAIN TEXT, never markdown (§24.2).
export function CitationPanel({ citations, active, onHover }: Props) {
  if (!citations.length) {
    return <p className="muted">No sources for this answer.</p>;
  }
  return (
    <div className="sources">
      {citations.map((c) => (
        <div
          key={c.index}
          className="source"
          style={active === c.index ? { borderColor: "var(--accent)" } : undefined}
          onMouseEnter={() => onHover(c.index)}
          onMouseLeave={() => onHover(null)}
        >
          <div className="row">
            <span className="idx">[{c.index}]</span>
            <span className="grow">{c.filename || "document"}</span>
            {c.page_no != null ? <span className="muted">p.{c.page_no}</span> : null}
            {c.weak ? <span className="pill warn">weak match</span> : null}
            {!c.was_cited ? <span className="pill">not cited</span> : null}
          </div>
          <div className="snip">{c.snippet}</div>
        </div>
      ))}
    </div>
  );
}
