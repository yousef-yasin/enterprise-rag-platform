import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { kbs } from "@/api/endpoints";
import type { KBRole } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";

export function KnowledgeBaseDetailPage() {
  const { kbId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const kbQ = useQuery({ queryKey: ["kb", kbId], queryFn: () => kbs.get(kbId) });
  const isOwner = kbQ.data?.your_role === "owner";

  const membersQ = useQuery({
    queryKey: ["kb", kbId, "members"],
    queryFn: () => kbs.members(kbId),
    enabled: isOwner,
  });

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Exclude<KBRole, "owner">>("viewer");

  const addMember = useMutation({
    mutationFn: () => kbs.addMember(kbId, email, role),
    onSuccess: () => {
      setEmail("");
      void qc.invalidateQueries({ queryKey: ["kb", kbId, "members"] });
    },
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) => kbs.removeMember(kbId, userId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb", kbId, "members"] }),
  });
  const deleteKb = useMutation({
    mutationFn: () => kbs.remove(kbId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kbs"] });
      navigate("/knowledge-bases");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    addMember.mutate();
  }

  if (kbQ.isLoading) return <p>Loading…</p>;
  if (kbQ.error) return <ErrorBanner error={kbQ.error} />;
  const kb = kbQ.data!;

  return (
    <>
      <h1>{kb.name}</h1>
      <p className="muted">
        /{kb.slug} · your role: {kb.your_role}
      </p>
      <ErrorBanner error={addMember.error || removeMember.error || deleteKb.error} />

      <div className="card">
        <div className="row">
          <Link to={`/knowledge-bases/${kbId}/documents`}>
            <button className="primary">Manage documents</button>
          </Link>
          <Link to="/chat">
            <button>Open chat</button>
          </Link>
        </div>
      </div>

      {isOwner && (
        <div className="card">
          <h2>Members</h2>
          <form className="row" onSubmit={submit}>
            <input
              className="grow"
              type="email"
              placeholder="teammate@example.com"
              value={email}
              required
              onChange={(e) => setEmail(e.target.value)}
            />
            <select
              style={{ width: 120 }}
              value={role}
              onChange={(e) => setRole(e.target.value as Exclude<KBRole, "owner">)}
            >
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
            </select>
            <button className="primary" disabled={addMember.isPending}>
              Add
            </button>
          </form>
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {membersQ.data?.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    {m.display_name || m.email}
                    <br />
                    <span className="muted">{m.email}</span>
                  </td>
                  <td>{m.role}</td>
                  <td>
                    {m.role !== "owner" && (
                      <button onClick={() => removeMember.mutate(m.user_id)}>Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isOwner && (
        <div className="card">
          <h2>Danger zone</h2>
          <button
            onClick={() => {
              if (confirm(`Delete "${kb.name}" and all its documents?`)) deleteKb.mutate();
            }}
          >
            Delete knowledge base
          </button>
        </div>
      )}
    </>
  );
}
