/** Risk score → severity colors (AuditObservationsPanel convention). */
export function RiskScoreBadge({ score }: { score: number }) {
  const n = Number(score) || 0;
  let label = "Low";
  let cls = "bg-gray-100 text-gray-600 ring-1 ring-gray-200";
  if (n >= 70) {
    label = "High";
    cls = "bg-red-50 text-red-700 ring-1 ring-red-200";
  } else if (n >= 40) {
    label = "Medium";
    cls = "bg-orange-50 text-orange-800 ring-1 ring-orange-200";
  } else if (n >= 20) {
    label = "Elevated";
    cls = "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${cls}`}
    >
      <span className="tabular-nums">{n}</span>
      <span className="font-medium opacity-80">{label}</span>
    </span>
  );
}
