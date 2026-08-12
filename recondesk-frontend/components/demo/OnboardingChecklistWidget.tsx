"use client";

import React, { useState } from "react";
import { CheckCircle2, Circle, ChevronDown, ChevronUp, Plus, ShieldCheck, X } from "lucide-react";

interface OnboardingChecklistWidgetProps {
  hasRealClient: boolean;
  isGstinConnected: boolean;
  onAddRealClient?: () => void;
  onConnectGstin?: () => void;
}

export function OnboardingChecklistWidget({
  hasRealClient,
  isGstinConnected,
  onAddRealClient,
  onConnectGstin,
}: OnboardingChecklistWidgetProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const completedCount = 1 + (hasRealClient ? 1 : 0) + (isGstinConnected ? 1 : 0);
  const totalCount = 3;
  const progressPct = Math.round((completedCount / totalCount) * 100);

  return (
    <div className="fixed bottom-6 right-6 z-40 w-80 shadow-xl rounded-2xl border border-gray-200 bg-white/95 backdrop-blur-md transition-all duration-300">
      {/* Header bar */}
      <div className="flex items-center justify-between p-4 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-dim text-brand font-semibold text-xs">
            {completedCount}/{totalCount}
          </div>
          <div>
            <h4 className="text-xs font-semibold text-gray-900">Get Started Checklist</h4>
            <p className="text-[10px] text-gray-500">{progressPct}% completed</p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setCollapsed((prev) => !prev)}
            className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            {collapsed ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-1 w-full bg-gray-100 overflow-hidden">
        <div
          className="h-full bg-brand transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Checklist items */}
      {!collapsed && (
        <div className="p-3 space-y-2 text-xs">
          {/* Item 1: Explore demo data */}
          <div className="flex items-center gap-2.5 rounded-xl p-2 bg-emerald-50/50 text-emerald-800 font-medium">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
            <span>Explore demo data</span>
          </div>

          {/* Item 2: Add first real client */}
          <div
            onClick={!hasRealClient && onAddRealClient ? onAddRealClient : undefined}
            className={`flex items-center justify-between rounded-xl p-2 transition-all ${
              hasRealClient
                ? "bg-emerald-50/50 text-emerald-800 font-medium"
                : "bg-gray-50 text-gray-700 hover:bg-gray-100 cursor-pointer"
            }`}
          >
            <div className="flex items-center gap-2.5">
              {hasRealClient ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
              ) : (
                <Circle className="h-4 w-4 text-gray-400 shrink-0" />
              )}
              <span>Add your first real client</span>
            </div>
            {!hasRealClient && <Plus className="h-3.5 w-3.5 text-gray-400" />}
          </div>

          {/* Item 3: Connect GSTIN via OTP */}
          <div
            onClick={!isGstinConnected && onConnectGstin ? onConnectGstin : undefined}
            className={`flex items-center justify-between rounded-xl p-2 transition-all ${
              isGstinConnected
                ? "bg-emerald-50/50 text-emerald-800 font-medium"
                : "bg-gray-50 text-gray-700 hover:bg-gray-100 cursor-pointer"
            }`}
          >
            <div className="flex items-center gap-2.5">
              {isGstinConnected ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
              ) : (
                <Circle className="h-4 w-4 text-gray-400 shrink-0" />
              )}
              <span>Connect GSTIN (1-click OTP)</span>
            </div>
            {!isGstinConnected && <ShieldCheck className="h-3.5 w-3.5 text-gray-400" />}
          </div>
        </div>
      )}
    </div>
  );
}
