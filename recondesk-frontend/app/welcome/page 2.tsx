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

  const markSeenAndRedirect = useCallback(
    (targetUrl = "/clients?add=1") => {
      if (authToken) {
        void usersApi.setShowcaseSeen(authToken).catch(() => {});
      }
      if (typeof window !== "undefined") {
        window.location.href = targetUrl;
      } else {
        router.push(targetUrl);
      }
    },
    [authToken, router]
  );

  const handleNext = () => {
    if (currentScreen < TOTAL_SCREENS) {
      setCurrentScreen((prev) => prev + 1);
    } else {
      markSeenAndRedirect("/clients?add=1");
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
    <div className="min-h-screen bg-[#F8F9FA] text-gray-900 flex flex-col justify-between p-6 sm:p-10 font-sans selection:bg-gray-900 selection:text-white">
      {/* Top Bar Header */}
      <header className="flex items-center justify-between max-w-5xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <Logo className="h-7 w-auto" />
          <span className="text-xs font-semibold uppercase px-2.5 py-0.5 rounded-full bg-gray-200/80 text-gray-700 border border-gray-300/50">
            Showcase
          </span>
        </div>
        <button
          type="button"
          onClick={() => markSeenAndRedirect("/clients")}
          className="text-xs font-semibold text-gray-500 hover:text-gray-900 transition-colors cursor-pointer"
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
              <span className="text-xs font-semibold text-amber-700 uppercase tracking-wider">
                01 / ITC Protection
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                ₹2.3L of invalid ITC caught before return filing
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                ReconDesk cross-verifies supplier GSTR-1 status, tax rates, and 180-day payment timelines automatically.
              </p>
            </div>

            {/* Mocked UI Card */}
            <div className="rounded-2xl bg-white border border-gray-200/80 p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between pb-4 border-b border-gray-100">
                <div>
                  <p className="text-xs text-gray-500 font-medium">Flagged ITC at Risk</p>
                  <p className="text-2xl font-bold text-gray-900">₹2,30,000</p>
                </div>
                <span className="px-3 py-1 rounded-full bg-amber-50 text-amber-800 text-xs font-semibold border border-amber-200">
                  3 Critical Action Items
                </span>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3.5 rounded-xl bg-gray-50/80 border border-gray-200/60 text-sm">
                  <div>
                    <p className="font-semibold text-gray-900">Apex Supplies Ltd</p>
                    <p className="text-xs text-gray-500">27AAACA1234A1Z5 • Inv #APX-8801</p>
                  </div>
                  <div className="text-right">
                    <p className="font-bold text-gray-900">₹1,20,000</p>
                    <span className="text-xs font-semibold text-red-600">Supplier GSTR-1 Unfiled</span>
                  </div>
                </div>
                <div className="flex items-center justify-between p-3.5 rounded-xl bg-gray-50/80 border border-gray-200/60 text-sm">
                  <div>
                    <p className="font-semibold text-gray-900">Zenith Logistics</p>
                    <p className="text-xs text-gray-500">27BBBZZ9876B1Z2 • Inv #ZNT-402</p>
                  </div>
                  <div className="text-right">
                    <p className="font-bold text-gray-900">₹75,000</p>
                    <span className="text-xs font-semibold text-amber-700">Tax Amount Mismatch</span>
                  </div>
                </div>
                <div className="flex items-center justify-between p-3.5 rounded-xl bg-gray-50/80 border border-gray-200/60 text-sm">
                  <div>
                    <p className="font-semibold text-gray-900">Metro Catering Services</p>
                    <p className="text-xs text-gray-500">27CCCYY4321C1Z9 • HSN 9995</p>
                  </div>
                  <div className="text-right">
                    <p className="font-bold text-gray-900">₹35,000</p>
                    <span className="text-xs font-semibold text-rose-700">Blocked Credit (Sec 17(5))</span>
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
              <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">
                02 / AI Engine
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                Clear WHAT, WHY, and NEXT for every discrepancy
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                No black boxes. ReconDesk explains fuzzy matches, invoice number formatting variations, and exact resolution steps.
              </p>
            </div>

            {/* Mocked Rationale Drawer Card */}
            <div className="rounded-2xl bg-white border border-gray-200/80 p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                <div className="flex items-center gap-2.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                  <span className="font-semibold text-gray-900 text-sm">Match Rationale Breakdown</span>
                </div>
                <span className="text-xs text-emerald-800 bg-emerald-50 px-2.5 py-0.5 rounded-full font-semibold border border-emerald-200">
                  98% Match Confidence
                </span>
              </div>

              <div className="grid sm:grid-cols-3 gap-3 text-xs">
                <div className="p-3.5 rounded-xl bg-gray-50/80 border border-gray-200/60 space-y-1">
                  <p className="font-semibold uppercase text-gray-500 tracking-wider text-[10px]">WHAT</p>
                  <p className="text-gray-800 font-medium">Invoice number slash formatting variation detected (`INV/2024/089` vs `INV2024089`).</p>
                </div>
                <div className="p-3.5 rounded-xl bg-gray-50/80 border border-gray-200/60 space-y-1">
                  <p className="font-semibold uppercase text-gray-500 tracking-wider text-[10px]">WHY</p>
                  <p className="text-gray-800 font-medium">Taxable value (₹1,50,000) and GSTIN match 100%. Supplier omitted slashes in GSTR-1.</p>
                </div>
                <div className="p-3.5 rounded-xl bg-emerald-50/70 border border-emerald-200/80 space-y-1">
                  <p className="font-semibold uppercase text-emerald-800 tracking-wider text-[10px]">NEXT</p>
                  <p className="text-emerald-900 font-semibold">Approved for ITC claim — no tax adjustment required.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Screen 3: Rule 37 & Sec 17(5) */}
        {currentScreen === 3 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-semibold text-sky-700 uppercase tracking-wider">
                03 / Compliance Automation
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                Rule 37 180-day tracker & Section 17(5) detection
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                Prevent audit notices by catching unpaid vendor bills beyond 180 days and blocked credit HSNs before return sign-off.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div className="rounded-2xl bg-white border border-sky-200 p-5 space-y-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-sky-800">RULE 37 TRACKER</span>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-50 text-sky-800 font-semibold border border-sky-200">
                    192 Days Unpaid
                  </span>
                </div>
                <p className="text-sm font-semibold text-gray-900">Star Traders • Inv #9914</p>
                <p className="text-xs text-gray-600">Payment past 180 days limit. Claiming now triggers forced reversal with 18% interest.</p>
                <div className="p-3 rounded-xl bg-sky-50/80 border border-sky-200/80 text-xs font-semibold text-sky-900">
                  Reversal Warning: ₹1,50,000 Tax
                </div>
              </div>

              <div className="rounded-2xl bg-white border border-rose-200 p-5 space-y-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-rose-800">SEC 17(5) BLOCKED CREDIT</span>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-800 font-semibold border border-rose-200">
                    Ineligible ITC
                  </span>
                </div>
                <p className="text-sm font-semibold text-gray-900">Rent-a-Cab Service • HSN 8703</p>
                <p className="text-xs text-gray-600">Motor vehicle lease credit blocked under Sec 17(5)(a) unless used for taxable passenger transport.</p>
                <div className="p-3 rounded-xl bg-rose-50/80 border border-rose-200/80 text-xs font-semibold text-rose-900">
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
              <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wider">
                04 / IMS Management
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                1-Click ACCEPT, REJECT, or HOLD IMS hints
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                Instant decision recommendations for the Invoice Management System based on vendor compliance state.
              </p>
            </div>

            <div className="space-y-3">
              <div className="rounded-2xl bg-white border border-gray-200/80 p-4 flex items-center justify-between gap-4 shadow-sm">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-200">ACCEPT</span>
                    <span className="font-semibold text-gray-900 text-sm">Bharat Steel Pvt Ltd</span>
                  </div>
                  <p className="text-xs text-gray-600">GSTR-1 filed & Purchase Register values match 100%.</p>
                </div>
                <span className="text-xs font-bold text-gray-900">₹84,000 ITC</span>
              </div>

              <div className="rounded-2xl bg-white border border-gray-200/80 p-4 flex items-center justify-between gap-4 shadow-sm">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-50 text-rose-800 border border-rose-200">REJECT</span>
                    <span className="font-semibold text-gray-900 text-sm">Delta Distributors</span>
                  </div>
                  <p className="text-xs text-gray-600">Invoice #DL-401 not found in client Purchase Register (ghost invoice risk).</p>
                </div>
                <span className="text-xs font-bold text-gray-900">₹62,500 ITC</span>
              </div>

              <div className="rounded-2xl bg-white border border-gray-200/80 p-4 flex items-center justify-between gap-4 shadow-sm">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-800 border border-slate-200">HOLD</span>
                    <span className="font-semibold text-gray-900 text-sm">Kiran Enterprises</span>
                  </div>
                  <p className="text-xs text-gray-600">Supplier filed return late; holding pending GSTR-3B verification.</p>
                </div>
                <span className="text-xs font-bold text-gray-900">₹29,000 ITC</span>
              </div>
            </div>
          </div>
        )}

        {/* Screen 5: Vendor Follow-up */}
        {currentScreen === 5 && (
          <div className="space-y-6 animate-fadeIn">
            <div className="space-y-2">
              <span className="text-xs font-semibold text-purple-700 uppercase tracking-wider">
                05 / Communication Audit
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                Automated vendor notices via WhatsApp & Email
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                Dispatch professional, pre-filled discrepancy notices directly to non-compliant suppliers with one click.
              </p>
            </div>

            <div className="rounded-2xl bg-white border border-gray-200/80 p-6 space-y-4 shadow-sm">
              <div className="flex items-center justify-between border-b border-gray-100 pb-3 text-xs">
                <span className="font-semibold text-gray-900">Dispatch Discrepancy Notice</span>
                <span className="text-purple-700 font-semibold">1-Click WhatsApp / Email</span>
              </div>

              <div className="space-y-2 text-xs">
                <div className="flex gap-2 text-gray-500">
                  <span className="w-16 font-medium">To:</span>
                  <span className="text-gray-900 font-medium">accounts@apexsupplies.com</span>
                </div>
                <div className="flex gap-2 text-gray-500">
                  <span className="w-16 font-medium">Subject:</span>
                  <span className="text-gray-900 font-medium">Urgent: ReconDesk Notice — GSTR-1 Discrepancy for Inv #APX-8801</span>
                </div>
                <div className="mt-3 p-4 rounded-xl bg-gray-50 border border-gray-200/60 text-xs text-gray-800 leading-relaxed font-sans">
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
              <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">
                06 / Direct Filing
              </span>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
                Complete GSTR-1 & GSTR-3B filing inside one desk
              </h1>
              <p className="text-base text-gray-600 max-w-2xl">
                Save data, offset cash/credit ledger balances automatically, and file directly with EVC OTP verification.
              </p>
            </div>

            <div className="rounded-2xl bg-white border border-gray-200/80 p-6 space-y-6 shadow-sm">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-center space-y-1">
                  <span className="text-xs font-bold text-emerald-800">1. SAVE DATA</span>
                  <p className="text-xs text-emerald-900 font-semibold">Summary Prepared ✓</p>
                </div>
                <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-center space-y-1">
                  <span className="text-xs font-bold text-emerald-800">2. OFFSET LEDGER</span>
                  <p className="text-xs text-emerald-900 font-semibold">Auto-Calculated ✓</p>
                </div>
                <div className="p-4 rounded-xl bg-gray-50 border border-gray-200 text-center space-y-1">
                  <span className="text-xs font-bold text-gray-900">3. FILE RETURN</span>
                  <p className="text-xs text-gray-600">Ready for EVC OTP</p>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-gray-50 border border-gray-200/60 flex items-center justify-between text-xs">
                <span className="text-gray-600 font-medium">GSTN Ledger Net Tax Payable:</span>
                <span className="font-bold text-emerald-700">₹0 Cash (Fully Offset by Matched ITC)</span>
              </div>
            </div>
          </div>
        )}

        {/* Screen 7: Closing Screen */}
        {currentScreen === 7 && (
          <div className="space-y-6 animate-fadeIn text-center max-w-2xl mx-auto py-4">
            <div className="space-y-3">
              <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">
                Ready to Start
              </span>
              <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900">
                That's ReconDesk.
              </h1>
              <p className="text-base sm:text-lg text-gray-600">
                Add your first client and see this on real data in under 2 minutes.
              </p>
            </div>

            <div className="pt-6 flex flex-col items-center gap-4">
              <button
                type="button"
                onClick={() => markSeenAndRedirect("/clients?add=1")}
                className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-gray-900 hover:bg-black px-8 text-base font-semibold text-white shadow-md transition-all hover:scale-105 cursor-pointer"
              >
                + Add First Client →
              </button>
              <button
                type="button"
                onClick={() => markSeenAndRedirect("/clients")}
                className="text-xs font-semibold text-gray-500 hover:text-gray-900 transition-colors cursor-pointer"
              >
                Or view empty client portfolio
              </button>
            </div>
          </div>
        )}
      </main>

      {/* Footer Controls & Progress */}
      <footer className="max-w-4xl mx-auto w-full flex items-center justify-between pt-6 border-t border-gray-200">
        <button
          type="button"
          onClick={handleBack}
          disabled={currentScreen === 1}
          className="px-4 py-2 rounded-full border border-gray-300 bg-white text-xs font-semibold text-gray-700 disabled:opacity-30 hover:bg-gray-100 transition-colors cursor-pointer"
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
                currentScreen === idx + 1 ? "w-6 bg-gray-900" : "w-2 bg-gray-300 hover:bg-gray-400"
              }`}
              aria-label={`Go to slide ${idx + 1}`}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={handleNext}
          className="px-6 py-2 rounded-full bg-gray-900 hover:bg-black text-white text-xs font-semibold transition-colors cursor-pointer shadow-sm"
        >
          {currentScreen === TOTAL_SCREENS ? "Finish →" : "Next →"}
        </button>
      </footer>
    </div>
  );
}
