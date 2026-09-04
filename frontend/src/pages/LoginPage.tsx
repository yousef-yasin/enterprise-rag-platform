import { FormEvent, useState } from "react";
import { auth } from "@/api/endpoints";
import { useAuthStore } from "@/stores/auth";
import { ErrorBanner } from "@/components/ErrorBanner";

export function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await auth.register(email, password, displayName);
      }
      await login(email, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
        <ErrorBanner error={error} />
        {mode === "register" && (
          <div style={{ marginBottom: 10 }}>
            <label htmlFor="dn">Display name</label>
            <input
              id="dn"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
            />
          </div>
        )}
        <div style={{ marginBottom: 10 }}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label htmlFor="pw">Password</label>
          <input
            id="pw"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </div>
        <button className="primary" type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? "…" : mode === "login" ? "Sign in" : "Register & sign in"}
        </button>
        <p className="muted" style={{ marginTop: 12, textAlign: "center" }}>
          {mode === "login" ? (
            <>
              First run or open registration?{" "}
              <button type="button" onClick={() => setMode("register")}>
                Register
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setMode("login")}>
              Back to sign in
            </button>
          )}
        </p>
      </form>
    </div>
  );
}
