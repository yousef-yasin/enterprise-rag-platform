import { create } from "zustand";
import { auth } from "@/api/endpoints";
import { clearSession, refreshSession, setAccessToken } from "@/api/client";
import type { User } from "@/api/types";

interface AuthState {
  user: User | null;
  status: "idle" | "loading" | "authenticated" | "anonymous";
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "idle",

  login: async (email, password) => {
    const { access_token } = await auth.login(email, password);
    setAccessToken(access_token);
    const user = await auth.me();
    set({ user, status: "authenticated" });
  },

  logout: async () => {
    try {
      await auth.logout(); // sends the CSRF header; clears the HttpOnly cookies
    } catch {
      /* best effort */
    }
    clearSession();
    set({ user: null, status: "anonymous" });
  },

  bootstrap: async () => {
    set({ status: "loading" });
    // The refresh token is an HttpOnly cookie — try to exchange it for an access
    // token. Success => restore the session; failure => anonymous.
    if (await refreshSession()) {
      try {
        const user = await auth.me();
        set({ user, status: "authenticated" });
        return;
      } catch {
        clearSession();
      }
    }
    set({ user: null, status: "anonymous" });
  },
}));
