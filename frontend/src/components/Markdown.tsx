import { useEffect, useRef } from "react";
import { renderMarkdown } from "@/lib/markdown";

interface Props {
  source: string;
  activeCitation?: number | null;
  onCitationClick?: (n: number) => void;
}

/**
 * Renders sanitized markdown by appending a DocumentFragment — never
 * dangerouslySetInnerHTML (§24.2, enforced by the `react/no-danger` lint rule).
 */
export function Markdown({ source, activeCitation, onCitationClick }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    host.replaceChildren(renderMarkdown(source));
    host.querySelectorAll<HTMLElement>("sup.cite").forEach((el) => {
      const n = Number(el.dataset.cite);
      el.classList.toggle("active", activeCitation === n);
      el.addEventListener("click", () => onCitationClick?.(n));
    });
  }, [source, activeCitation, onCitationClick]);

  return <div ref={ref} className="markdown" />;
}
