import { Fragment, type ReactNode } from "react";

type StatTone = "default" | "emphasis";

export function StatCard({
  label,
  value,
  hint,
  icon,
  empty = false,
  emptyCaption,
  emptyIcon = "dash",
  tone = "default",
  trend,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  empty?: boolean;
  emptyCaption?: string;
  emptyIcon?: "dash" | "check";
  tone?: StatTone;
  trend?: "up" | "none";
}) {
  const emphasized = tone === "emphasis";

  return (
    <div
      className={`group relative flex min-h-[148px] flex-col justify-between rounded-[1.5rem] p-5 transition-transform duration-200 hover:-translate-y-0.5 ${
        emphasized
          ? "bg-[var(--ink)] text-white shadow-[var(--shadow-lift)]"
          : "dashboard-card"
      }`}
      title={hint}
    >
      <div className="flex items-start justify-between gap-3">
        <span
          className={`inline-flex h-11 w-11 items-center justify-center rounded-full ${
            emphasized ? "bg-white/15 text-white" : "bg-[#F3F4F6] text-gray-700"
          }`}
          aria-hidden
        >
          {icon ?? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M4 19V5M4 19h16M8 15v4M12 10v9M16 7v12"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          )}
        </span>
        {trend === "up" ? (
          <span
            className={`inline-flex h-8 w-8 items-center justify-center rounded-full ${
              emphasized ? "bg-white/15 text-white" : "bg-gray-100 text-gray-600"
            }`}
            aria-hidden
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path
                d="M7 17L17 7M10 7h7v7"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        ) : null}
      </div>

      <div className="mt-6">
        {empty ? (
          emptyIcon === "check" ? (
            <div className="flex items-start gap-2.5">
              <span
                className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                  emphasized ? "bg-white/15 text-white" : "bg-emerald-50 text-emerald-600"
                }`}
                aria-hidden
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M9.5 12l1.8 1.8L14.8 10"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <p
                className={`text-sm font-medium leading-snug ${
                  emphasized ? "text-white/85" : "text-gray-700"
                }`}
              >
                {emptyCaption ?? "All caught up"}
              </p>
            </div>
          ) : (
            <>
              <p
                className={`font-sans text-[1.75rem] font-semibold tracking-tight ${
                  emphasized ? "text-white/40" : "text-gray-300"
                }`}
              >
                —
              </p>
              {emptyCaption ? (
                <p
                  className={`mt-1 text-xs ${
                    emphasized ? "text-white/55" : "text-gray-400"
                  }`}
                >
                  {emptyCaption}
                </p>
              ) : null}
            </>
          )
        ) : (
          <p
            className={`font-sans text-[1.85rem] font-semibold tracking-tight ${
              emphasized ? "text-white" : "text-[var(--ink)]"
            }`}
          >
            {typeof value === "string" && value.includes("₹") ? (
              <>
                {value.split("₹").map((part, idx) => (
                  <Fragment key={idx}>
                    {idx > 0 && (
                      <span
                        style={{
                          fontFamily: "Arial, system-ui, -apple-system, sans-serif",
                          fontWeight: "inherit",
                        }}
                      >
                        ₹
                      </span>
                    )}
                    {part}
                  </Fragment>
                ))}
              </>
            ) : (
              value
            )}
          </p>
        )}
        <p
          className={`mt-1.5 text-[13px] font-medium ${
            emphasized ? "text-white/65" : "text-gray-500"
          }`}
        >
          {label}
        </p>
      </div>
    </div>
  );
}
