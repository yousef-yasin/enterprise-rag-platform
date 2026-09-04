import type { DocumentStatus } from "@/api/types";

const CLASS: Record<DocumentStatus, string> = {
  ready: "pill ok",
  partially_indexed: "pill warn",
  failed: "pill err",
  pending: "pill",
  processing: "pill",
};

export function DocumentStatusBadge({
  status,
  stage,
  reason,
}: {
  status: DocumentStatus;
  stage?: string | null;
  reason?: string | null;
}) {
  const label =
    status === "failed" && reason
      ? `failed: ${reason}`
      : stage && !["ready", "failed", "partially_indexed"].includes(status)
        ? `${status} (${stage})`
        : status;
  return <span className={CLASS[status] ?? "pill"}>{label}</span>;
}
