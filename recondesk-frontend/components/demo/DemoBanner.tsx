"use client";

import React from "react";
import { Sparkles, PlusCircle } from "lucide-react";

interface DemoBannerProps {
  onAddRealClient?: () => void;
}

export function DemoBanner({ onAddRealClient }: DemoBannerProps) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-amber-500/10 via-brand-dim to-indigo-500/10 border border-amber-500/20 p-4 shadow-sm backdrop-blur-md mb-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/20 text-amber-600 dark:text-amber-400">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-gray-900 dark:text-gray-100 text-sm">
                Exploring Demo Enterprises
              </span>
              <span className="inline-flex items-center rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:text-amber-300">
                Sample Data
              </span>
            </div>
            <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
              👋 This is real ReconDesk output on pre-computed realistic data. Explore all features freely!
            </p>
          </div>
        </div>

        {onAddRealClient && (
          <button
            onClick={onAddRealClient}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-gray-900 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-black focus:outline-none focus:ring-2 focus:ring-gray-900/20 transition-all"
          >
            <PlusCircle className="h-4 w-4" />
            Add your own client
          </button>
        )}
      </div>
    </div>
  );
}
