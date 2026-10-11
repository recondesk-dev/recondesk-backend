"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  type PracticeDashboardGridRow,
} from "@/lib/api";
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  FileCheck,
  Send,
  Eye,
  Filter,
  Building2,
} from "lucide-react";

interface Props {
  rows: PracticeDashboardGridRow[];
  period: string;
  onRefresh?: () => void;
}

export function UnifiedFilingGrid({ rows, period, onRefresh }: Props) {
  const [filterStage, setFilterStage] = useState<string>("ALL");
  const [search, setSearch] = useState<string>("");

  const filtered = rows.filter((r) => {
    if (filterStage !== "ALL" && r.actionable_stage !== filterStage) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      return (
        r.gstin.toLowerCase().includes(q) ||
        r.trade_name.toLowerCase().includes(q) ||
        r.pan.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const getStageBadge = (stage: string) => {
    switch (stage) {
      case "FILED":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3 h-3" /> Filed
          </span>
        );
      case "READY_TO_FILE":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
            <FileCheck className="w-3 h-3" /> Ready to File
          </span>
        );
      case "UNDER_REVIEW":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <Clock className="w-3 h-3" /> Under Review
          </span>
        );
      case "AWAITING_CLIENT_CONSENT":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
            <Send className="w-3 h-3" /> Client Consent Pending
          </span>
        );
      case "CLIENT_REJECTED":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
            <AlertTriangle className="w-3 h-3" /> Client Rejected
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/30">
            Draft
          </span>
        );
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
      <div className="p-4 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <Building2 className="w-4 h-4 text-cyan-400" />
            Unified Return Filing Fleet ({period})
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Authoritative filing progress, maker-checker states, and client consent gates across client GSTINs.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search GSTIN, trade name, PAN..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 w-52"
          />

          <select
            value={filterStage}
            onChange={(e) => setFilterStage(e.target.value)}
            className="px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-lg text-slate-200 focus:outline-none focus:border-cyan-500"
          >
            <option value="ALL">All Stages ({rows.length})</option>
            <option value="READY_TO_FILE">Ready to File</option>
            <option value="UNDER_REVIEW">Under Review</option>
            <option value="AWAITING_CLIENT_CONSENT">Awaiting Client Consent</option>
            <option value="FILED">Filed</option>
            <option value="CLIENT_REJECTED">Client Rejected</option>
            <option value="DRAFT">Draft</option>
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-slate-800/60 text-slate-400 border-b border-slate-800 font-medium">
              <th className="py-3 px-4">Client & PAN</th>
              <th className="py-3 px-4">GSTIN & State</th>
              <th className="py-3 px-4">Actionable Stage</th>
              <th className="py-3 px-4">Maker-Checker</th>
              <th className="py-3 px-4">Client Consent</th>
              <th className="py-3 px-4">Blockers / Next Action</th>
              <th className="py-3 px-4 text-right">Filing Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-500">
                  No return records match the active criteria.
                </td>
              </tr>
            ) : (
              filtered.map((r) => (
                <tr key={r.client_gstin_id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-slate-200">{r.trade_name}</div>
                    <div className="text-[11px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                      <span className="font-mono bg-slate-800 px-1 py-0.5 rounded text-slate-300">
                        {r.pan}
                      </span>
                      {r.legal_name && r.legal_name !== r.trade_name ? (
                        <span className="truncate max-w-[150px]">{r.legal_name}</span>
                      ) : null}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span className="font-mono text-cyan-300 font-medium">{r.gstin}</span>
                    <div className="text-[11px] text-slate-400">State: {r.gstin.slice(0, 2)}</div>
                  </td>
                  <td className="py-3 px-4">{getStageBadge(r.actionable_stage)}</td>
                  <td className="py-3 px-4">
                    <span className="font-mono text-[11px] text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700">
                      {r.maker_checker_status}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    <span className="font-mono text-[11px] text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700">
                      {r.client_auth_status}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    {r.blocker ? (
                      <span className="text-amber-400 text-xs flex items-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        {r.blocker}
                      </span>
                    ) : r.actionable_stage === "FILED" ? (
                      <span className="text-emerald-400 text-xs flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Compliant
                      </span>
                    ) : r.actionable_stage === "READY_TO_FILE" ? (
                      <span className="text-cyan-400 text-xs flex items-center gap-1">
                        <FileCheck className="w-3.5 h-3.5" />
                        All Gates Cleared
                      </span>
                    ) : (
                      <span className="text-slate-400 text-xs">In Progress</span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Link
                        href={`/filing/gstr-1/${period}?client_gstin_id=${r.client_gstin_id}`}
                        className="px-2.5 py-1 text-xs font-medium text-cyan-300 hover:text-cyan-200 bg-cyan-950/60 hover:bg-cyan-900/60 border border-cyan-800 rounded transition-colors"
                      >
                        GSTR-1
                      </Link>
                      <Link
                        href={`/filing/gstr-3b/${period}?client_gstin_id=${r.client_gstin_id}`}
                        className="px-2.5 py-1 text-xs font-medium text-indigo-300 hover:text-indigo-200 bg-indigo-950/60 hover:bg-indigo-900/60 border border-indigo-800 rounded transition-colors"
                      >
                        GSTR-3B
                      </Link>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
