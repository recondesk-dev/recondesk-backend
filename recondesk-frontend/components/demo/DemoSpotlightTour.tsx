"use client";

import React, { useEffect, useState } from "react";
import { X, ChevronRight, ChevronLeft, Sparkles, CheckCircle2 } from "lucide-react";
import { usersApi } from "@/lib/api";

export interface TourStop {
  id: string;
  targetSelector: string;
  title: string;
  content: string;
}

const TOUR_STOPS: TourStop[] = [
  {
    id: "dashboard-summary",
    targetSelector: '[data-tour="dashboard-summary"]',
    title: "Portfolio Summary",
    content: "₹4.8L total ITC analyzed across 3,500 invoices with zero manual effort.",
  },
  {
    id: "itc-at-risk",
    targetSelector: '[data-tour="itc-at-risk"]',
    title: "ITC-at-Risk Cards",
    content: "₹1.4L of ITC at risk from unfiled suppliers and date discrepancies.",
  },
  {
    id: "mismatch-drawer",
    targetSelector: '[data-tour="mismatch-drawer"]',
    title: "AI Discrepancy Rationale",
    content: "AI engine detects invoice number variants (e.g. INV/2024/003 vs INV2024003) and explains the exact discrepancy rationale.",
  },
  {
    id: "rule37-tracker",
    targetSelector: '[data-tour="rule37-tracker"]',
    title: "Rule 37 Tracker",
    content: "₹2.3L of ITC this client would've claimed wrongly under Rule 37 — ReconDesk caught it before the return was filed.",
  },
  {
    id: "ims-recommendations",
    targetSelector: '[data-tour="ims-recommendations"]',
    title: "IMS Recommendations",
    content: "Instant Accept/Reject recommendations based on vendor compliance state and risk level.",
  },
  {
    id: "vendor-followup",
    targetSelector: '[data-tour="vendor-followup"]',
    title: "Vendor Follow-up",
    content: "1-click automated vendor communications to recover missing invoices before monthly cutoff.",
  },
];

interface DemoSpotlightTourProps {
  token: string | null;
  onClose?: () => void;
}

export function DemoSpotlightTour({ token, onClose }: DemoSpotlightTourProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);

  const stop = TOUR_STOPS[currentStep];

  useEffect(() => {
    if (!stop) return;
    const el = document.querySelector(stop.targetSelector);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      const rect = el.getBoundingClientRect();
      setTargetRect(rect);
    } else {
      setTargetRect(null);
    }
  }, [currentStep, stop]);

  const handleFinish = async () => {
    if (token) {
      try {
        await usersApi.setDemoTourSeen(token);
      } catch {
        /* ignore */
      }
    }
    if (onClose) onClose();
  };

  const handleNext = () => {
    if (currentStep < TOUR_STOPS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      void handleFinish();
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  return (
    <div className="fixed inset-0 z-50 pointer-events-none">
      {/* Dark overlay backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px] transition-opacity duration-300 pointer-events-auto" />

      {/* Target element highlight ring */}
      {targetRect && (
        <div
          className="absolute rounded-xl ring-4 ring-brand shadow-[0_0_25px_rgba(79,70,229,0.5)] transition-all duration-300 pointer-events-none"
          style={{
            top: targetRect.top - 8 + window.scrollY,
            left: targetRect.left - 8,
            width: targetRect.width + 16,
            height: targetRect.height + 16,
          }}
        />
      )}

      {/* Tooltip Card */}
      <div className="fixed bottom-10 right-10 max-w-md w-full pointer-events-auto shadow-2xl rounded-2xl border border-gray-100 bg-white p-6 transition-all duration-300">
        <div className="flex items-center justify-between pb-3 border-b border-gray-100 mb-4">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-dim text-brand">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-brand">
              ReconDesk Tour ({currentStep + 1} of {TOUR_STOPS.length})
            </span>
          </div>

          <button
            onClick={() => void handleFinish()}
            className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <span>Skip tour</span>
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <h3 className="text-base font-semibold text-gray-900 mb-2">{stop.title}</h3>
        <p className="text-sm text-gray-600 leading-relaxed mb-6">{stop.content}</p>

        <div className="flex items-center justify-between pt-2">
          <button
            onClick={handlePrev}
            disabled={currentStep === 0}
            className="inline-flex items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </button>

          <button
            onClick={handleNext}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gray-900 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-black transition-colors"
          >
            {currentStep === TOUR_STOPS.length - 1 ? (
              <>
                <span>Got it!</span>
                <CheckCircle2 className="h-4 w-4 text-green-400" />
              </>
            ) : (
              <>
                <span>Next</span>
                <ChevronRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
