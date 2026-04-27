export function PriorityScore({ score }: { score: number }) {
  let cls =
    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#F3F4F6] text-[#6B7280]";
  let label = "Low";

  if (score >= 86) {
    cls =
      "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#FEF2F2] text-[#EF4444] animate-pulse";
    label = "Critical";
  } else if (score >= 61) {
    cls =
      "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#FFEDD5] text-[#EA580C]";
    label = "High";
  } else if (score >= 31) {
    cls =
      "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#FEF9C3] text-[#CA8A04]";
    label = "Medium";
  }

  return (
    <span className={cls} title={`Priority score ${score}`}>
      {label}
    </span>
  );
}
