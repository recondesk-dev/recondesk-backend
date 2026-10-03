import type { ReactNode } from "react";

export function StatCard({
  label, value, hint, icon, empty = false, emptyCaption, emptyIcon = "dash",
  tone = "default", onClick, isActive = false, subtitle, badge, fullValue,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  empty?: boolean;
  emptyCaption?: string;
  emptyIcon?: "dash" | "check";
  tone?: "default" | "emphasis";
  trend?: "up" | "none";
  onClick?: () => void;
  isActive?: boolean;
  subtitle?: string;
  badge?: ReactNode;
  fullValue?: string;
}) {
  const content = (
    <>
      <span className="rd-stat-topline">
        <span className="rd-stat-label">{label}</span>
        <span className="rd-stat-symbol" aria-hidden="true">{icon}</span>
      </span>
      <span className={`rd-stat-value${empty ? " rd-stat-empty" : ""}`}>
        {empty ? emptyIcon === "check" ? <><span aria-hidden="true">✓</span> {emptyCaption ?? "All caught up"}</> : "—" : value}
      </span>
      <span className="rd-stat-bottomline">
        <span>{empty && emptyIcon === "dash" ? emptyCaption : subtitle}</span>
        {badge ?? (onClick ? <span className="rd-stat-arrow" aria-hidden="true">↗</span> : <span className="rd-stat-seal" aria-hidden="true">✓</span>)}
      </span>
    </>
  );
  const className = `rd-stat-card${tone === "emphasis" ? " rd-stat-emphasis" : ""}`;
  const title = fullValue ? `${hint ? `${hint} — ` : ""}${fullValue}` : hint;

  return onClick ? (
    <button type="button" className={className} aria-pressed={isActive} onClick={onClick} title={title}>
      {content}
    </button>
  ) : (
    <div className={className} title={title}>{content}</div>
  );
}
