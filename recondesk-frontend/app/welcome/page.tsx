"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import { usersApi } from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const TOTAL_SCREENS = 7;

export default function WelcomeShowcasePage() {
  const router = useRouter();
  const tokenState = useAccessToken();
  const authToken = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [currentScreen, setCurrentScreen] = useState(1);
  const [isFinishing, setIsFinishing] = useState(false);

  const markSeenAndRedirect = useCallback(
    async (targetUrl = "/clients?add=1") => {
      if (isFinishing) return;
      setIsFinishing(true);
      if (authToken) {
        try {
          await usersApi.setShowcaseSeen(authToken);
        } catch {
          /* ignore error, proceed to navigate */
        }
      }
      router.replace(targetUrl);
    },
    [authToken, isFinishing, router]
  );

  const handleNext = () => {
    if (currentScreen < TOTAL_SCREENS) {
      setCurrentScreen((prev) => prev + 1);
    } else {
      void markSeenAndRedirect("/clients?add=1");
    }
  };

  const handleBack = () => {
    if (currentScreen > 1) {
      setCurrentScreen((prev) => prev - 1);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "Space") {
        e.preventDefault();
        handleNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        handleBack();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentScreen]);

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-white flex flex-col justify-between p-6 sm:p-10 font-sans selection:bg-white selection:text-black">
      {/* Top Bar */}
      <header className="flex items-center justify-between max-w-5xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <Logo className="h-7 w-auto text-white" />
          <span className="text-xs font-semibold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/10 text-gray-300 border border-white/10">
            Showcase
          </span>
        </div>
        <button
          type="button"
          onClick={() => void markSeenAndRedirect("/clients")}
          className="text-xs font-medium text-gray-400 hover:text-white transition-colors cursor-pointer"
        >
          Skip showcase →
        </button>
      </header>

      {/* Main Content Area */}
      <main className="max-w-4xl mx-auto w-full my-auto py-8">
        {/* Screen 1: ITC-at-Risk */}
        {currentScreen === 1 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-amber-400 uppercase tracking-widest">
                01 / ITC Protection
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                ₹2.3L of invalid ITC caught before return filing
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                ReconDesk cross-verifies supplier GSTR-1 status, tax rates, and 180-day payment timelines automatically.
              </p>
            </div>

            {/* Mocked UI Card */}
            <div className="rounded-2xl bg-[#141416] border border-white/10 p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between pb-4 border-b border-white/10">
                <div>
                  <p className="text-xs text-gray-400 font-medium">Flagged ITC at Risk</p>
                  <p className="text-2xl font-bold font-mono text-amber-400">₹2,30,000</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 text-xs font-semibold border border-amber-500/20">
                  3 Critical Action Items
                </span>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5 text-sm">
                  <div>
                    <p className="font-semibold text-white">Apex Supplies Ltd</p>
                    <p className="text-xs text-gray-400 font-mono">27AAACA1234A1Z5 • Inv #APX-8801</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-bold text-white">₹1,20,000</p>
                    <span className="text-[11px] font-semibold text-red-400">Supplier GSTR-1 Unfiled</span>
                  </div>
                </div>
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5 text-sm">
                  <div>
                    <p className="font-semibold text-white">Zenith Logistics</p>
                    <p className="text-xs text-gray-400 font-mono">27BBBZZ9876B1Z2 • Inv #ZNT-402</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-bold text-white">₹75,000</p>
                    <span className="text-[11px] font-semibold text-amber-400">Tax Amount Mismatch</span>
                  </div>
                </div>
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5 text-sm">
                  <div>
                    <p className="font-semibold text-white">Metro Catering Services</p>
                    <p className="text-xs text-gray-400 font-mono">27CCCYY4321C1Z9 • HSN 9995</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-bold text-white">₹35,000</p>
                    <span className="text-[11px] font-semibold text-rose-400">Blocked Credit (Sec 17(5))</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Screen 2: AI Rationale */}
        {currentScreen === 2 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-emerald-400 uppercase tracking-widest">
                02 / AI Engine
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                Clear WHAT, WHY, and NEXT for every discrepancy
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                No black boxes. ReconDesk explains fuzzy matches, invoice number formatting variations, and exact resolution steps.
              </p>
            </div>

            {/* Mocked Rationale Drawer Card */}
            <div className="rounded-2xl bg-[#141416] border border-white/10 p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between border-b border-white/10 pb-3">
                <div className="flex items-center gap-3">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                  <span className="font-semibold text-white text-sm">Match Rationale Breakdown</span>
                </div>
                <span className="text-xs font-mono text-emerald-400 font-semibold">98% Match Confidence</span>
              </div>

              <div className="grid sm:grid-cols-3 gap-3 text-xs">
                <div className="p-3 rounded-xl bg-white/5 border border-white/5 space-y-1">
                  <p className="font-semibold uppercase text-gray-400 tracking-wider text-[10px]">WHAT</p>
                  <p className="text-gray-200 font-medium">Invoice number slash formatting variation detected (`INV/2024/089` vs `INV2024089`).</p>
                </div>
                <div className="p-3 rounded-xl bg-white/5 border border-white/5 space-y-1">
                  <p className="font-semibold uppercase text-gray-400 tracking-wider text-[10px]">WHY</p>
                  <p className="text-gray-200 font-medium">Taxable value (₹1,50,000) and GSTIN match 100%. Supplier omitted slashes in GSTR-1.</p>
                </div>
                <div className="p-3 rounded-xl bg-white/5 border border-white/5 space-y-1">
                  <p className="font-semibold uppercase text-emerald-400 tracking-wider text-[10px]">NEXT</p>
                  <p className="text-emerald-300 font-semibold">Approved for ITC claim — no tax adjustment required.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Screen 3: Rule 37 & Sec 17(5) */}
        {currentScreen === 3 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-sky-400 uppercase tracking-widest">
                03 / Compliance Automation
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                Rule 37 180-day tracker & Section 17(5) detection
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                Prevent audit notices by catching unpaid vendor bills beyond 180 days and blocked credit HSNs before return sign-off.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div className="rounded-2xl bg-[#141416] border border-sky-500/20 p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-sky-400 font-mono">RULE 37 TRACKER</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 font-medium">192 Days Unpaid</span>
                </div>
                <p className="text-sm font-semibold text-white">Star Traders • Inv #9914</p>
                <p className="text-xs text-gray-400">Payment past 180 days limit. Claiming now triggers forced reversal with 18% interest.</p>
                <div className="p-2.5 rounded-lg bg-sky-500/10 border border-sky-500/20 text-xs font-mono text-sky-300">
                  Reversal Warning: ₹1,50,000 Tax
                </div>
              </div>

              <div className="rounded-2xl bg-[#141416] border border-rose-500/20 p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-rose-400 font-mono">SEC 17(5) BLOCKED CREDIT</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-medium">Ineligible ITC</span>
                </div>
                <p className="text-sm font-semibold text-white">Rent-a-Cab Service • HSN 8703</p>
                <p className="text-xs text-gray-400">Motor vehicle lease credit blocked under Sec 17(5)(a) unless used for taxable passenger transport.</p>
                <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs font-mono text-rose-300">
                  Auto-Flagged: ₹45,000 Blocked
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Screen 4: IMS Recommendations */}
        {currentScreen === 4 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-indigo-400 uppercase tracking-widest">
                04 / IMS Management
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                1-Click ACCEPT, REJECT, or HOLD IMS hints
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                Instant decision recommendations for the Invoice Management System based on vendor compliance state.
              </p>
            </div>

            <div className="space-y-3">
              <div className="rounded-xl bg-[#141416] border border-white/10 p-4 flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">ACCEPT</span>
                    <span className="font-semibold text-white text-sm">Bharat Steel Pvt Ltd</span>
                  </div>
                  <p className="text-xs text-gray-400">GSTR-1 filed & Purchase Register values match 100%.</p>
                </div>
                <span className="text-xs font-mono text-gray-300">₹84,000 ITC</span>
              </div>

              <div className="rounded-xl bg-[#141416] border border-white/10 p-4 flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">REJECT</span>
                    <span className="font-semibold text-white text-sm">Delta Distributors</span>
                  </div>
                  <p className="text-xs text-gray-400">Invoice #DL-401 not found in client Purchase Register (ghost invoice risk).</p>
                </div>
                <span className="text-xs font-mono text-gray-300">₹62,500 ITC</span>
              </div>

              <div className="rounded-xl bg-[#141416] border border-white/10 p-4 flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">HOLD</span>
                    <span className="font-semibold text-white text-sm">Kiran Enterprises</span>
                  </div>
                  <p className="text-xs text-gray-400">Supplier filed return late; holding pending GSTR-3B verification.</p>
                </div>
                <span className="text-xs font-mono text-gray-300">₹29,000 ITC</span>
              </div>
            </div>
          </div>
        )}

        {/* Screen 5: Vendor Follow-up */}
        {currentScreen === 5 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-purple-400 uppercase tracking-widest">
                05 / Communication Audit
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                Automated vendor notices via WhatsApp & Email
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                Dispatch professional, pre-filled discrepancy notices directly to non-compliant suppliers with one click.
              </p>
            </div>

            <div className="rounded-2xl bg-[#141416] border border-white/10 p-6 space-y-4 shadow-2xl">
              <div className="flex items-center justify-between border-b border-white/10 pb-3 text-xs">
                <span className="font-semibold text-white">Dispatch Discrepancy Notice</span>
                <span className="text-purple-400 font-mono font-semibold">1-Click WhatsApp / Email</span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="flex gap-2 text-gray-400">
                  <span className="w-16 font-medium">To:</span>
                  <span className="text-white font-mono">accounts@apexsupplies.com</span>
                </div>
                <div className="flex gap-2 text-gray-400">
                  <span className="w-16 font-medium">Subject:</span>
                  <span className="text-white">Urgent: ReconDesk Notice — GSTR-1 Discrepancy for Inv #APX-8801</span>
                </div>
                <div className="mt-3 p-3.5 rounded-xl bg-white/5 border border-white/5 font-mono text-[11px] text-gray-300 leading-relaxed">
                  Dear Apex Supplies,<br /><br />
                  Our automated reconciliation detected a GSTR-1 tax mismatch of ₹3,600 for invoice APX-8801 (Period: April 2026).<br />
                  Please amend your GSTR-1 before the cutoff date so we can claim input tax credit without delay.
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Screen 6: Filing Inside ReconDesk */}
        {currentScreen === 6 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-mono font-semibold text-emerald-400 uppercase tracking-widest">
                06 / Direct Filing
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
                Complete GSTR-1 & GSTR-3B filing inside one desk
              </h1>
              <p className="text-base text-gray-400 max-w-2xl">
                Save data, offset cash/credit ledger balances automatically, and file directly with EVC OTP verification.
              </p>
            </div>

            <div className="rounded-2xl bg-[#141416] border border-white/10 p-6 space-y-6 shadow-2xl">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-center space-y-1">
                  <span className="text-xs font-bold text-emerald-400">1. SAVE DATA</span>
                  <p className="text-xs text-gray-300 font-semibold">Summary Prepared ✓</p>
                </div>
                <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-center space-y-1">
                  <span className="text-xs font-bold text-emerald-400">2. OFFSET LEDGER</span>
                  <p className="text-xs text-gray-300 font-semibold">Auto-Calculated ✓</p>
                </div>
                <div className="p-4 rounded-xl bg-white/10 border border-white/20 text-center space-y-1">
                  <span className="text-xs font-bold text-white">3. FILE RETURN</span>
                  <p className="text-xs text-gray-400">Ready for EVC OTP</p>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-white/5 border border-white/5 flex items-center justify-between text-xs">
                <span className="text-gray-300">GSTN Ledger Net Tax Payable:</span>
                <span className="font-mono font-bold text-emerald-400">₹0 Cash (Fully Offset by Matched ITC)</span>
              </div>
            </div>
          </div>
        )}

        {/* Screen 7: Closing Screen */}
        {currentScreen === 7 && (
          <div className="space-y-6 animate-fadeIn text-center max-w-2xl mx-auto py-4">
            <div className="space-y-3">
              <span className="text-xs font-mono font-semibold text-emerald-400 uppercase tracking-widest">
                Ready to Start
              </span>
              <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-white">
                That's ReconDesk.
              </h1>
              <p className="text-base sm:text-lg text-gray-300">
                Add your first client and see this on real data in under 2 minutes.
              </p>
            </div>

            <div className="pt-6 flex flex-col items-center gap-4">
              <button
                type="button"
                onClick={() => void markSeenAndRedirect("/clients?add=1")}
                className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-white px-8 text-base font-semibold text-black shadow-lg transition-transform hover:scale-105 cursor-pointer"
              >
                + Add First Client →
              </button>
              <button
                type="button"
                onClick={() => void markSeenAndRedirect("/clients")}
                className="text-xs text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                Or view empty client portfolio
              </button>
            </div>
          </div>
        )}
      </main>

      {/* Footer Controls & Progress */}
      <footer className="max-w-4xl mx-auto w-full flex items-center justify-between pt-6 border-t border-white/10">
        <button
          type="button"
          onClick={handleBack}
          disabled={currentScreen === 1}
          className="px-4 py-2 rounded-full border border-white/10 text-xs font-semibold text-gray-300 disabled:opacity-30 hover:bg-white/10 transition-colors cursor-pointer"
        >
          ← Back
        </button>

        {/* Progress Dots */}
        <div className="flex items-center gap-2">
          {Array.from({ length: TOTAL_SCREENS }).map((_, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setCurrentScreen(idx + 1)}
              className={`h-2 rounded-full transition-all duration-300 cursor-pointer ${
                currentScreen === idx + 1 ? "w-6 bg-white" : "w-2 bg-white/20 hover:bg-white/40"
              }`}
              aria-label={`Go to slide ${idx + 1}`}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={handleNext}
          className="px-6 py-2 rounded-full bg-white text-black text-xs font-semibold hover:bg-gray-200 transition-colors cursor-pointer"
        >
          {currentScreen === TOTAL_SCREENS ? "Finish →" : "Next →"}
        </button>
      </footer>
    </div>
  );
}
