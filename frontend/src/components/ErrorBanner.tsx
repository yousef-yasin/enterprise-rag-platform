import { RequestError } from "@/api/client";

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  let msg = "Something went wrong.";
  let rid: string | undefined;
  if (error instanceof RequestError) {
    msg = error.message;
    rid = error.requestId;
  } else if (error instanceof Error) {
    msg = error.message;
  }
  return (
    <div className="banner" role="alert">
      {msg}
      {rid ? <span className="muted"> (request {rid})</span> : null}
    </div>
  );
}
