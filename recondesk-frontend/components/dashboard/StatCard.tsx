export function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {label}
        </p>
        <p className="mt-2 font-mono text-2xl font-semibold text-[var(--text-primary)]">{value}</p>
      </div>
      <div className="rounded-lg bg-[var(--accent-dim)] p-2.5 text-[var(--accent)]">{icon}</div>
    </div>
  );
}
