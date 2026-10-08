"use client";

import React, { useState, useEffect } from "react";
import { ReconciliationLoadingExperience } from "@/components/reconcile/ReconciliationLoadingExperience";
import { Play, RotateCcw } from "lucide-react";

export default function LoadingExperiencePreviewPage() {
  const [selectedSnapshot, setSelectedSnapshot] = useState<
    "snapshot_1" | "snapshot_2" | "snapshot_3" | "live_sim"
  >("snapshot_1");

  // Live simulation states
  const [simProgress, setSimProgress] = useState(42);
  const [simElapsed, setSimElapsed] = useState(28);
  const [isSimRunning, setIsSimRunning] = useState(false);

  useEffect(() => {
    if (!isSimRunning || selectedSnapshot !== "live_sim") return;
    const interval = setInterval(() => {
      setSimElapsed((prev) => prev + 1);
      setSimProgress((prev) => {
        if (prev >= 100) {
          setIsSimRunning(false);
          return 100;
        }
        return Math.min(100, prev + 1.2);
      });
    }, 800);
    return () => clearInterval(interval);
  }, [isSimRunning, selectedSnapshot]);

  const handleResetSim = () => {
    setSimProgress(15);
    setSimElapsed(8);
    setIsSimRunning(true);
  };

  return (
    <div className="min-h-screen bg-[#F7F5FB] py-8 px-4 sm:px-6">
      {/* Top Banner / Snapshot Switcher Control */}
      <div className="max-w-[620px] mx-auto mb-6 bg-white rounded-2xl p-4 border border-[#E8E2EE] shadow-xs flex items-center justify-between gap-4">
        <div>
          <h1 className="text-sm font-semibold text-[#342B40]">
            Reconciliation Loading Experience
          </h1>
          <p className="text-xs text-[#777083]">
            Refined layout with zero repetition
          </p>
        </div>

        {/* Snapshot Toggles */}
        <div className="flex items-center gap-1 bg-[#F6F4FA] p-1 rounded-xl text-xs font-medium border border-[#EAE3F4]">
          <button
            type="button"
            onClick={() => setSelectedSnapshot("snapshot_1")}
            className={`px-2.5 py-1.5 rounded-lg transition-all ${
              selectedSnapshot === "snapshot_1"
                ? "bg-[#342B40] text-white shadow-xs"
                : "text-[#655778] hover:text-[#342B40]"
            }`}
          >
            1. Matching
          </button>
          <button
            type="button"
            onClick={() => setSelectedSnapshot("snapshot_2")}
            className={`px-2.5 py-1.5 rounded-lg transition-all ${
              selectedSnapshot === "snapshot_2"
                ? "bg-[#342B40] text-white shadow-xs"
                : "text-[#655778] hover:text-[#342B40]"
            }`}
          >
            2. Longer wait
          </button>
          <button
            type="button"
            onClick={() => setSelectedSnapshot("snapshot_3")}
            className={`px-2.5 py-1.5 rounded-lg transition-all ${
              selectedSnapshot === "snapshot_3"
                ? "bg-[#342B40] text-white shadow-xs"
                : "text-[#655778] hover:text-[#342B40]"
            }`}
          >
            3. Completed
          </button>
          <button
            type="button"
            onClick={() => {
              setSelectedSnapshot("live_sim");
              handleResetSim();
            }}
            className={`px-2.5 py-1.5 rounded-lg transition-all flex items-center gap-1 ${
              selectedSnapshot === "live_sim"
                ? "bg-[#8054ED] text-white shadow-xs"
                : "text-[#655778] hover:text-[#342B40]"
            }`}
          >
            <Play className="w-3 h-3 fill-current" />
            Live
          </button>
        </div>
      </div>

      {/* Render the Component */}
      <main className="w-full">
        {selectedSnapshot === "snapshot_1" && (
          <ReconciliationLoadingExperience
            previewState="in_progress"
            progressPct={42}
            elapsedSeconds={28}
            matchedCount={142}
            reviewCount={3}
            clientName="Acme Industrial Ltd"
            periodLabel="October 2024"
          />
        )}

        {selectedSnapshot === "snapshot_2" && (
          <ReconciliationLoadingExperience
            previewState="longer_wait"
            progressPct={78}
            elapsedSeconds={64}
            matchedCount={1385}
            reviewCount={16}
            clientName="Acme Industrial Ltd"
            periodLabel="October 2024"
          />
        )}

        {selectedSnapshot === "snapshot_3" && (
          <ReconciliationLoadingExperience
            previewState="completed"
            progressPct={100}
            elapsedSeconds={84}
            matchedCount={1420}
            reviewCount={18}
            missingCount={4}
            totalProcessedCount={1442}
            clientName="Acme Industrial Ltd"
            periodLabel="October 2024"
          />
        )}

        {selectedSnapshot === "live_sim" && (
          <ReconciliationLoadingExperience
            progressPct={simProgress}
            elapsedSeconds={simElapsed}
            matchedCount={Math.round((simProgress / 100) * 1420)}
            reviewCount={Math.min(18, Math.round((simProgress / 100) * 20))}
            missingCount={Math.min(4, Math.round((simProgress / 100) * 5))}
            totalProcessedCount={1442}
            clientName="Acme Industrial Ltd"
            periodLabel="October 2024"
          />
        )}
      </main>
    </div>
  );
}
