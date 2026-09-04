// Renders model output as safe HTML (docs/ARCHITECTURE.md §24.2).
//
//  - markdown-it with html:false  -> raw HTML in the answer is escaped, never parsed
//  - a strict allowlist pass over the generated DOM  -> only known-safe tags/attrs
//  - image syntax is disabled      -> rendered as an inert "image (blocked)" chip
//  - links: http/https/mailto only, forced rel + target
//  - `[[n]]` citation markers become <sup data-cite="n"> chips for the UI to wire up
//
// No dangerouslySetInnerHTML anywhere: callers get a DocumentFragment.

import MarkdownIt from "markdown-it";

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
});

// Disable image parsing entirely.
md.disable(["image"]);

const ALLOWED_TAGS = new Set([
  "p", "br", "hr",
  "strong", "em", "del", "code", "pre", "blockquote",
  "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "a", "sup",
  "table", "thead", "tbody", "tr", "th", "td",
  "span",
]);
const ALLOWED_ATTRS: Record<string, Set<string>> = {
  a: new Set(["href", "title", "rel", "target"]),
  sup: new Set(["data-cite", "class"]),
  span: new Set(["class"]),
  td: new Set(["style"]),
  th: new Set(["style"]),
};
const SAFE_LINK = /^(https?:|mailto:)/i;
const CITE = /\[\[(\d{1,3})\]\]/g;

function sanitizeElement(el: Element): void {
  const tag = el.tagName.toLowerCase();
  if (!ALLOWED_TAGS.has(tag)) {
    // unwrap: keep the text, drop the element
    el.replaceWith(...Array.from(el.childNodes));
    return;
  }
  for (const attr of Array.from(el.attributes)) {
    const ok = ALLOWED_ATTRS[tag]?.has(attr.name.toLowerCase());
    if (!ok) {
      el.removeAttribute(attr.name);
      continue;
    }
    if (tag === "a" && attr.name.toLowerCase() === "href" && !SAFE_LINK.test(attr.value.trim())) {
      el.removeAttribute("href");
    }
    if (tag === "td" || tag === "th") {
      // markdown-it emits `style="text-align:..."` for aligned columns; allow only that
      if (attr.name === "style" && !/^text-align:\s*(left|right|center);?$/.test(attr.value)) {
        el.removeAttribute("style");
      }
    }
  }
  if (tag === "a") {
    el.setAttribute("rel", "noopener noreferrer nofollow");
    el.setAttribute("target", "_blank");
  }
  for (const child of Array.from(el.children)) sanitizeElement(child);
}

function wrapCitations(root: DocumentFragment): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  let n: Node | null;
  while ((n = walker.nextNode())) textNodes.push(n as Text);

  for (const textNode of textNodes) {
    const value = textNode.nodeValue ?? "";
    if (!CITE.test(value)) continue;
    CITE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = CITE.exec(value))) {
      const n = m[1] ?? "";
      frag.append(document.createTextNode(value.slice(last, m.index)));
      const sup = document.createElement("sup");
      sup.className = "cite";
      sup.setAttribute("data-cite", n);
      sup.textContent = n;
      frag.append(sup);
      last = m.index + m[0].length;
    }
    frag.append(document.createTextNode(value.slice(last)));
    textNode.replaceWith(frag);
  }
}

export function renderMarkdown(source: string): DocumentFragment {
  const html = md.render(source ?? "");
  const template = document.createElement("template");
  template.innerHTML = html;
  const frag = template.content;
  for (const child of Array.from(frag.children)) sanitizeElement(child);
  wrapCitations(frag);
  return frag;
}

/** True when the sanitizer would strip something (used by the security test). */
export function containsUnsafeMarkup(source: string): boolean {
  const html = md.render(source ?? "");
  return /<(script|iframe|object|embed|style|img|svg|link|form)\b/i.test(html);
}
