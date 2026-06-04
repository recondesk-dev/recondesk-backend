export function Avatar({
  initials,
  size = "md",
}: {
  initials: string;
  size?: "sm" | "md";
}) {
  const sz = size === "sm" ? "h-7 w-7 text-[10px]" : "h-9 w-9 text-xs";
  return (
    <span
      className={`inline-flex ${sz} shrink-0 items-center justify-center rounded-full bg-brand-dim font-semibold text-brand`}
    >
      {initials}
    </span>
  );
}
