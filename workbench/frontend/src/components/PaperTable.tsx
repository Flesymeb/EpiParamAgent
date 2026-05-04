import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

function toneForDecision(value: string) {
  if (value.includes("Strong")) return "green";
  if (value.includes("Possible")) return "amber";
  if (value.includes("Error")) return "rose";
  if (value.includes("Full")) return "blue";
  return "stone";
}

function toneForStatus(value: string) {
  if (value === "screened" || value === "converted") return "green";
  if (value.includes("failed")) return "rose";
  if (value === "pending") return "amber";
  return "stone";
}

export function PaperTable({
  rows,
}: {
  rows: Array<Record<string, string | number | boolean | null>>;
}) {
  const visible = rows.slice(0, 120);
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-sage-100 px-5 py-4">
        <div className="section-title">Paper Review Table</div>
        <div className="mt-1 text-xs text-slate-500">
          Showing {visible.length} of {rows.length} rows for responsive inspection.
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead className="bg-sage-50/60 text-left text-[11px] uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th className="px-4 py-3">PMID</th>
              <th className="px-4 py-3">GT</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Decision</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3">Full-text</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, idx) => {
              const decision = String(row.llm_suggest ?? "");
              const status = String(row.fulltext_status ?? "");
              return (
                <tr key={`${row.PMID ?? idx}`} className="border-t border-sage-100/80 align-top hover:bg-sage-50/35">
                  <td className="px-4 py-3 font-mono text-xs text-slate-700">{String(row.PMID ?? "-")}</td>
                  <td className="px-4 py-3">
                    {String(row.is_ground_truth ?? "") === "✓" || String(row.is_ground_truth ?? "") === "GT" ? (
                      <Badge tone="blue">GT</Badge>
                    ) : null}
                  </td>
                  <td className="max-w-xl px-4 py-3 text-slate-800">{String(row.Title ?? "-")}</td>
                  <td className="px-4 py-3">
                    {decision ? <Badge tone={toneForDecision(decision) as never}>{decision}</Badge> : null}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-700">{String(row.overall_score ?? "-")}</td>
                  <td className="px-4 py-3 text-slate-700">{String(row.screening_stage ?? "-")}</td>
                  <td className="px-4 py-3">
                    {status ? <Badge tone={toneForStatus(status) as never}>{status}</Badge> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
