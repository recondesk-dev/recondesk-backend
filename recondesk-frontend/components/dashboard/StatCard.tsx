export function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between rounded-2xl bg-white p-6 shadow-sm">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
          {label}
        </p>
        <p className="mt-2 font-mono text-3xl font-semibold text-gray-900">{value}</p>
      </div>
      <div className="rounded-xl bg-gray-100 p-2.5 text-gray-500">{icon}</div>
    </div>
  );
}
