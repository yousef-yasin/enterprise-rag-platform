import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { documents, kbs } from "@/api/endpoints";
import type { DocumentModel, DocumentStatus } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { UploadDropzone } from "@/components/UploadDropzone";
import { DocumentStatusBadge } from "@/components/DocumentStatusBadge";
import { useJobStatus } from "@/hooks/useJobStatus";

const ACTIVE = new Set<DocumentStatus>(["pending", "processing"]);

function DocRow({ doc, kbId }: { doc: DocumentModel; kbId: string }) {
  const qc = useQueryClient();
  const live = useJobStatus(doc.id, ACTIVE.has(doc.status));
  const status: DocumentStatus = live.status ?? doc.status;

  useEffect(() => {
    if (live.status && !ACTIVE.has(live.status)) {
      void qc.invalidateQueries({ queryKey: ["docs", kbId] });
    }
  }, [live.status, kbId, qc]);

  const reprocess = useMutation({
    mutationFn: () => documents.reprocess(doc.id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["docs", kbId] }),
  });
  const remove = useMutation({
    mutationFn: () => documents.remove(doc.id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["docs", kbId] }),
  });

  return (
    <tr>
      <td>
        {doc.filename}
        <br />
        <span className="muted" style={{ fontSize: 12 }}>
          {(doc.size_bytes / 1024).toFixed(0)} KB
          {doc.page_count ? ` · ${doc.page_count} pages` : ""}
          {doc.lang ? ` · ${doc.lang}` : ""}
          {doc.language_warning ? " ⚠︎" : ""}
        </span>
      </td>
      <td>
        <DocumentStatusBadge status={status} stage={live.stage} reason={doc.failure_reason} />
      </td>
      <td>{doc.active_index_version ?? "—"}</td>
      <td>
        <div className="row" style={{ gap: 6 }}>
          <button disabled={reprocess.isPending || ACTIVE.has(status)} onClick={() => reprocess.mutate()}>
            Reprocess
          </button>
          <button
            disabled={remove.isPending}
            onClick={() => {
              if (confirm(`Delete ${doc.filename}?`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
        <ErrorBanner error={reprocess.error || remove.error} />
      </td>
    </tr>
  );
}

export function DocumentsPage() {
  const { kbId = "" } = useParams();
  const qc = useQueryClient();
  const [uploadError, setUploadError] = useState<unknown>(null);

  const kbQ = useQuery({ queryKey: ["kb", kbId], queryFn: () => kbs.get(kbId) });
  const docsQ = useQuery({
    queryKey: ["docs", kbId],
    queryFn: () => documents.list(kbId),
    refetchInterval: (q) =>
      q.state.data?.items.some((d) => ACTIVE.has(d.status)) ? 4000 : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) => documents.upload(kbId, file),
    onError: (e) => setUploadError(e),
    onSuccess: () => {
      setUploadError(null);
      void qc.invalidateQueries({ queryKey: ["docs", kbId] });
    },
  });

  const canEdit = kbQ.data?.your_role === "owner" || kbQ.data?.your_role === "editor";

  return (
    <>
      <h1>
        <Link to={`/knowledge-bases/${kbId}`}>{kbQ.data?.name ?? "Knowledge base"}</Link> · Documents
      </h1>
      <ErrorBanner error={docsQ.error || uploadError} />

      {canEdit && (
        <div className="card">
          <UploadDropzone
            disabled={upload.isPending}
            onFiles={(files) => files.forEach((f) => upload.mutate(f))}
          />
          {upload.isPending ? <p className="muted">Uploading…</p> : null}
        </div>
      )}

      <div className="card">
        {docsQ.isLoading ? (
          <p>Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Index v.</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {docsQ.data?.items.map((doc) => (
                <DocRow key={doc.id} doc={doc} kbId={kbId} />
              ))}
            </tbody>
          </table>
        )}
        {docsQ.data && docsQ.data.items.length === 0 ? (
          <p className="muted">No documents yet.</p>
        ) : null}
      </div>
    </>
  );
}
