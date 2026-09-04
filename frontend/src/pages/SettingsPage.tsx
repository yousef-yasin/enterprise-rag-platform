import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiKeys, kbs } from "@/api/endpoints";
import type { ApiKeyScope } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { ErrorBanner } from "@/components/ErrorBanner";

const SCOPES: ApiKeyScope[] = ["kb:read", "kb:ingest", "kb:manage", "chat"];

export function SettingsPage() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const keysQ = useQuery({ queryKey: ["apikeys"], queryFn: apiKeys.list });
  const kbQ = useQuery({ queryKey: ["kbs"], queryFn: kbs.list });

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>(["kb:read", "chat"]);
  const [kbId, setKbId] = useState("");
  const [freshToken, setFreshToken] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => apiKeys.create(name, scopes, kbId || undefined),
    onSuccess: (k) => {
      setFreshToken(k.token);
      setName("");
      void qc.invalidateQueries({ queryKey: ["apikeys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => apiKeys.revoke(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apikeys"] }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (scopes.length) create.mutate();
  }

  return (
    <>
      <h1>Settings</h1>

      <div className="card">
        <h2>Account</h2>
        <p>
          {user?.display_name || "—"} · {user?.email} {user?.is_admin ? "· admin" : ""}
        </p>
      </div>

      <div className="card">
        <h2>API keys</h2>
        <ErrorBanner error={keysQ.error || create.error || revoke.error} />
        {freshToken && (
          <div className="banner info">
            Copy this token now — it is shown only once:
            <br />
            <code>{freshToken}</code>
          </div>
        )}
        <form onSubmit={submit}>
          <div className="row">
            <div className="grow">
              <label htmlFor="kn">Key name</label>
              <input id="kn" required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label htmlFor="kkb">Scoped to KB (optional)</label>
              <select id="kkb" value={kbId} onChange={(e) => setKbId(e.target.value)}>
                <option value="">any of my KBs</option>
                {kbQ.data?.items.map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            {SCOPES.map((s) => (
              <label key={s} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={scopes.includes(s)}
                  onChange={(e) =>
                    setScopes((cur) =>
                      e.target.checked ? [...cur, s] : cur.filter((x) => x !== s),
                    )
                  }
                />
                {s}
              </label>
            ))}
          </div>
          <button className="primary" style={{ marginTop: 12 }} disabled={create.isPending}>
            Create key
          </button>
        </form>

        <table style={{ marginTop: 16 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Prefix</th>
              <th>Scopes</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keysQ.data?.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td>
                  <code>{k.key_prefix}…</code>
                </td>
                <td>{k.scopes.join(", ")}</td>
                <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                <td>
                  {k.revoked_at ? (
                    <span className="pill err">revoked</span>
                  ) : (
                    <button onClick={() => revoke.mutate(k.id)}>Revoke</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
