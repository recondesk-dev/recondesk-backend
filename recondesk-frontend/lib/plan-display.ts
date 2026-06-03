/** Human-readable plan names for sidebar / settings UI. */
const SOLO_PLAN_LABELS: Record<string, string> = {
  free: "Free",
  starter: "Solo Starter",
  growth: "Solo Growth",
  pro: "Solo Pro",
};

export function displayPlanName(plan: string | null | undefined): string {
  const key = (plan ?? "free").toLowerCase().trim();
  if (SOLO_PLAN_LABELS[key]) return SOLO_PLAN_LABELS[key];
  if (!key || key === "free") return "Free";
  return key
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
