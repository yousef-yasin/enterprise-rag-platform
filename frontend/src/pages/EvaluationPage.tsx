import { useQuery } from "@tanstack/react-query";
import { evaluation } from "@/api/endpoints";
import { RequestError } from "@/api/client";
import type { EvalMetric } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";

function fmt(m: EvalMetric): string {
  const v = m.value.toFixed(3);
  if (m.ci_low != null && m.ci_high != null) {
    return `${v}  [${m.ci_low.toFixed(3)}, ${m.ci_high.toFixed(3)}]`;
  }
  return v;
}

export function EvaluationPage() {
  const runsQ = useQuery({
    queryKey: ["eval", "runs"],
    queryFn: evaluation.runs,
    retry: false,
  });

  return (
    <>
      <h1>Evaluation</h1>
      <p className="muted">
        Runs are produced by <code>rag eval run &lt;dataset&gt;</code> or the nightly workflow.
        Metrics carry bootstrap 95% confidence intervals.
      </p>

      {runsQ.error instanceof RequestError && runsQ.error.status === 404 ? (
        <div className="banner info">
          No evaluation runs recorded yet. Run <code>make eval</code> to produce one.
        </div>
      ) : (
        <ErrorBanner error={runsQ.error} />
      )}

      {runsQ.data?.items.map((run) => (
        <div className="card" key={run.id}>
          <div className="row">
            <strong className="grow">
              {run.dataset} / {run.split}
            </strong>
            <span className="pill">{run.status}</span>
            {run.config_label ? <span className="pill">{run.config_label}</span> : null}
            {run.git_sha ? <code>{run.git_sha.slice(0, 8)}</code> : null}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            {run.n_samples} samples · {new Date(run.created_at).toLocaleString()}
          </p>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value (95% CI)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(run.metrics).map(([k, m]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>
                    <code>{fmt(m)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {runsQ.data && runsQ.data.items.length === 0 ? (
        <p className="muted">No runs yet.</p>
      ) : null}
    </>
  );
}
