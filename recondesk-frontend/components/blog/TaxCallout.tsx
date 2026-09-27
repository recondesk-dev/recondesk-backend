import React from "react";
import { AlertCircle, BookOpen, CheckCircle, Info } from "lucide-react";

interface TaxCalloutProps {
  type?: "info" | "warning" | "success" | "law";
  title?: string;
  children: React.ReactNode;
}

export function TaxCallout({ type = "info", title, children }: TaxCalloutProps) {
  const styles = {
    info: {
      border: "border-blue-200",
      bg: "bg-blue-50/50",
      icon: <Info className="h-4 w-4 text-blue-600" />,
      text: "text-blue-900",
    },
    warning: {
      border: "border-amber-200",
      bg: "bg-amber-50/50",
      icon: <AlertCircle className="h-4 w-4 text-amber-600" />,
      text: "text-amber-900",
    },
    success: {
      border: "border-emerald-200",
      bg: "bg-emerald-50/50",
      icon: <CheckCircle className="h-4 w-4 text-emerald-600" />,
      text: "text-emerald-900",
    },
    law: {
      border: "border-purple-200",
      bg: "bg-purple-50/40",
      icon: <BookOpen className="h-4 w-4 text-[#7B5CFA]" />,
      text: "text-[#0A0A0A]",
    },
  }[type];

  return (
    <div className={`my-6 rounded-xl border ${styles.border} ${styles.bg} p-4 sm:p-5 text-sm`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">{styles.icon}</div>
        <div className="space-y-1">
          {title && <h5 className={`font-bold ${styles.text}`}>{title}</h5>}
          <div className="text-xs sm:text-sm text-[#4A4A4A] leading-relaxed">{children}</div>
        </div>
      </div>
    </div>
  );
}
