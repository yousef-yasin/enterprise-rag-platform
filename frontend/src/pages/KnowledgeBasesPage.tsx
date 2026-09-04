import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { kbs } from "@/api/endpoints";
import { ErrorBanner } from "@/components/ErrorBanner";

export function KnowledgeBasesPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["kbs"], queryFn: kbs.list });
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");

  const create = useMutation({
    mutationFn: () => kbs.create(name, slug, description),
    onSuccess: () => {
      setName("");
      setSlug("");
      setDescription("");
      void qc.invalidateQueries({ queryKey: ["kbs"] });
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <>
      <h1>Knowledge bases</h1>
      <ErrorBanner error={error || create.error} />

      <form className="card" onSubmit={submit}>
        <h2>New knowledge base</h2>
        <div className="row">
          <div className="grow">
            <label htmlFor="n">Name</label>
            <input
              id="n"
              value={name}
              required
              onChange={(e) => {
                setName(e.target.value);
                if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
              }}
            />
          </div>
          <div className="grow">
            <label htmlFor="s">Slug</label>
            <input
              id="s"
              value={slug}
              required
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              onChange={(e) => setSlug(e.target.value)}
            />
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <label htmlFor="d">Description</label>
          <input id="d" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <button className="primary" style={{ marginTop: 12 }} disabled={create.isPending}>
          Create
        </button>
      </form>

      {isLoading ? (
        <p>Loading…</p>
      ) : (
        <div>
          {data?.items.map((kb) => (
            <div className="card" key={kb.id}>
              <div className="row">
                <Link to={`/knowledge-bases/${kb.id}`} className="grow">
                  <strong>{kb.name}</strong> <span className="muted">/{kb.slug}</span>
                </Link>
                <span className="pill">{kb.your_role}</span>
                <Link to={`/knowledge-bases/${kb.id}/documents`}>
                  <button>Documents</button>
                </Link>
              </div>
              {kb.description ? <p className="muted">{kb.description}</p> : null}
              <p className="muted" style={{ fontSize: 12 }}>
                embedding profile: {kb.active_embedding_profile_id ?? "not indexed yet"}
              </p>
            </div>
          ))}
          {data && data.items.length === 0 ? (
            <p className="muted">No knowledge bases yet — create one above.</p>
          ) : null}
        </div>
      )}
    </>
  );
}
