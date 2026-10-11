"use client";

import React, { useState } from "react";
import Link from "next/link";
import { type ComplianceDeadlineItem } from "@/lib/api";
import {
  Calendar,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Filter,
  ArrowRight,
  ShieldAlert,
  Info,
} from "lucide-react";

interface Props {
  deadlines: ComplianceDeadlineItem[];
  selectedPeriod?: string;
  onSelectPeriod?: (period: string) => void;
  onRefresh?: () => void;
}

export function ComplianceCalendarView({
  deadlines,
  selectedPeriod,
  onSelectPeriod,
  onRefresh,
}: Props) {
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");

  const filtered = deadlines.filter((item) => {
    if (typeFilter !== "ALL" && item.return_type !== typeFilter) return false;
    if (categoryFilter !== "ALL" && item.category !== categoryFilter) return false;
    return true;
  });

  const getUrgencyBadge = (item: ComplianceDeadlineItem) => {
    if (item.is_overdue) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-500 border border-rose-500/30">
          <AlertTriangle className="w-3.5 h-3.5" />
          Overdue ({Math.abs(item.days_remaining)}d)
        </span>
      );
    }
    if (item.urgency === "HIGH" || item.days_remaining <= 3) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-500 border border-amber-500/30">
          <Clock className="w-3.5 h-3.5" />
          Due Soon ({item.days_remaining}d)
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 border border-emerald-500/30">
        <CheckCircle2 className="w-3.5 h-3.5" />
        {item.days_remaining} days left
      </span>
    );
  };

  const returnTypes = Array.from(new Set(deadlines.map((d) => d.return_type)));
  const categories = Array.from(new Set(deadlines.map((d) => d.category)));

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-white border border-gray-200 shadow-sm">
        <div>
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <Calendar className="w-5 h-5 text-indigo-600" />
            Statutory GST Compliance Calendar
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Jurisdiction-aware statutory deadlines with staggered dates for Group A/B states and QRMP taxpayers.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Type Filter */}
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3.5 h-3.5 text-gray-400" />
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="ALL">All Return Types</option>
              {returnTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          {/* Category Filter */}
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="ALL">All Categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Statutory Guidance Callout */}
      <div className="flex items-start gap-3 p-4 rounded-xl bg-blue-50 border border-blue-200/70 text-xs text-blue-900">
        <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <span className="font-semibold text-blue-950">Statutory Rules & State Grouping:</span>
          <p className="text-blue-800 leading-relaxed">
            <strong>Group A States (22nd):</strong> Chhattisgarh, MP, Gujarat, Maharashtra, Karnataka, Goa, Kerala, TN, Telangana, AP, D&amp;NH/Daman, Puducherry, A&amp;N, Lakshadweep.
            <br />
            <strong>Group B States (24th):</strong> HP, Punjab, Uttarakhand, Haryana, Rajasthan, UP, Bihar, Sikkim, Arunachal, Nagaland, Manipur, Mizoram, Tripura, Meghalaya, Assam, WB, Jharkhand, Odisha, J&amp;K, Ladakh, Chandigarh, Delhi.
          </p>
        </div>
      </div>

      {/* Deadlines Grid */}
      {filtered.length === 0 ? (
        <div className="text-center py-12 rounded-xl bg-gray-50 border border-dashed border-gray-300">
          <Calendar className="w-10 h-10 text-gray-400 mx-auto mb-2" />
          <p className="text-sm font-medium text-gray-700">No statutory deadlines found for current filters</p>
          <p className="text-xs text-gray-500 mt-1">Try selecting a different return type or period</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((item, idx) => {
            const filingHref =
              item.return_type === "GSTR-1"
                ? "/filing/gstr-1"
                : item.return_type === "GSTR-3B"
                ? "/filing/gstr-3b"
                : item.return_type === "CMP-08"
                ? "/filing/gstr-4"
                : "/filing";

            return (
              <div
                key={`${item.period}-${item.return_type}-${item.category}-${idx}`}
                className={`relative flex flex-col justify-between p-5 rounded-xl border bg-white shadow-sm transition hover:shadow-md ${
                  item.is_overdue
                    ? "border-rose-200 bg-rose-50/20"
                    : item.urgency === "HIGH"
                    ? "border-amber-200 bg-amber-50/10"
                    : "border-gray-200"
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <span className="px-2.5 py-1 rounded-md text-xs font-bold tracking-wide uppercase bg-indigo-50 text-indigo-700 border border-indigo-200">
                      {item.return_type}
                    </span>
                    {getUrgencyBadge(item)}
                  </div>

                  <h3 className="text-sm font-bold text-gray-900 leading-snug">
                    {item.description}
                  </h3>

                  {/* Verification Status & Applicability */}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {item.is_extended ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-50 text-purple-700 border border-purple-200">
                        CBIC Extension {item.notification_ref ? `(${item.notification_ref})` : ""}
                      </span>
                    ) : item.is_verified === false || item.verification_status === "INFERRED" ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-600 border border-gray-200">
                        Inferred Applicability (State / Scheme Unconfirmed)
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                        Statutory Verified
                      </span>
                    )}
                  </div>

                  {item.taxpayer_applicability && (
                    <p className="mt-2 text-[11px] text-gray-600 leading-snug">
                      <strong>Applies to:</strong> {item.taxpayer_applicability}
                    </p>
                  )}
                  {item.note && (
                    <p className="mt-1 text-[10px] text-gray-500 italic">
                      Note: {item.note}
                    </p>
                  )}

                  <div className="mt-3 space-y-2 text-xs text-gray-600">
                    <div className="flex items-center justify-between py-1 border-b border-gray-100">
                      <span className="text-gray-500">Return Period:</span>
                      <span className="font-semibold text-gray-800 font-mono">{item.period}</span>
                    </div>
                    <div className="flex items-center justify-between py-1 border-b border-gray-100">
                      <span className="text-gray-500">Statutory Due Date:</span>
                      <span className="font-bold text-gray-900 font-mono">{item.due_date}</span>
                    </div>
                    <div className="flex items-center justify-between py-1">
                      <span className="text-gray-500">Category:</span>
                      <span className="font-medium text-gray-700 capitalize">
                        {item.category.toLowerCase().replace(/_/g, " ")}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="mt-5 pt-3 border-t border-gray-100 flex items-center justify-between">
                  <span className="text-xs text-gray-400">
                    {item.is_overdue
                      ? "Late fee & interest active"
                      : `${item.days_remaining} calendar days`}
                  </span>
                  <Link
                    href={filingHref}
                    className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition"
                  >
                    Open Return
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
