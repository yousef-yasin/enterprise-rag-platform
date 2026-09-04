import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearSession,
  currentAccessToken,
  getCsrfToken,
  refreshSession,
  setAccessToken,
} from "./client";

afterEach(() => {
  clearSession();
  document.cookie = "rag_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  vi.restoreAllMocks();
});

describe("auth client — cookie + CSRF model (§24.2)", () => {
  it("keeps the access token in memory only", () => {
    setAccessToken("abc123");
    expect(currentAccessToken()).toBe("abc123");
    clearSession();
    expect(currentAccessToken()).toBeNull();
  });

  it("reads the non-HttpOnly CSRF cookie", () => {
    document.cookie = "rag_csrf=tok-9f8e; path=/";
    expect(getCsrfToken()).toBe("tok-9f8e");
  });

  it("sends the CSRF header and credentials on refresh, stores the new access token", async () => {
    document.cookie = "rag_csrf=csrf-xyz; path=/";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: "new-access", token_type: "bearer" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const ok = await refreshSession();
    expect(ok).toBe(true);
    expect(currentAccessToken()).toBe("new-access");

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init?.credentials).toBe("include");
    expect((init?.headers as Record<string, string>)["x-csrf-token"]).toBe("csrf-xyz");
    // no refresh token is ever sent in the body
    expect(init?.body).toBeUndefined();
  });

  it("clears the session when refresh fails", async () => {
    setAccessToken("stale");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
    const ok = await refreshSession();
    expect(ok).toBe(false);
    expect(currentAccessToken()).toBeNull();
  });
});
