"use client";

import React, { useState, useEffect, useMemo } from "react";
import { PRICING_PLANS, formatInr, type BillingCycle, type PricingTierId } from "@/lib/pricing-data";
import type { BillingDetails } from "@/lib/billing-checkout";

const GST_STATE_MAP: Record<string, string> = {
  "01": "Jammu & Kashmir",
  "02": "Himachal Pradesh",
  "03": "Punjab",
  "04": "Chandigarh",
  "05": "Uttarakhand",
  "06": "Haryana",
  "07": "Delhi",
  "08": "Rajasthan",
  "09": "Uttar Pradesh",
  "10": "Bihar",
  "11": "Sikkim",
  "12": "Arunachal Pradesh",
  "13": "Nagaland",
  "14": "Manipur",
  "15": "Mizoram",
  "16": "Tripura",
  "17": "Meghalaya",
  "18": "Assam",
  "19": "West Bengal",
  "20": "Jharkhand",
  "21": "Odisha",
  "22": "Chhattisgarh",
  "23": "Madhya Pradesh",
  "24": "Gujarat",
  "26": "Dadra & Nagar Haveli and Daman & Diu",
  "27": "Maharashtra",
  "29": "Karnataka",
  "30": "Goa",
  "31": "Lakshadweep",
  "32": "Kerala",
  "33": "Tamil Nadu",
  "34": "Puducherry",
  "35": "Andaman & Nicobar Islands",
  "36": "Telangana",
  "37": "Andhra Pradesh",
  "38": "Ladakh",
  "97": "Other Territory",
};

const SELLER_STATE_CODE = "27"; // Maharashtra

type Props = {
  isOpen: boolean;
  planId: PricingTierId | null;
  cycle: BillingCycle;
  initialData?: {
    firmName?: string | null;
    firmGstin?: string | null;
    firmCity?: string | null;
  };
  loading?: boolean;
  onClose: () => void;
  onProceed: (details: BillingDetails) => Promise<void>;
};

export function CheckoutBillingModal({
  isOpen,
  planId,
  cycle,
  initialData,
  loading = false,
  onClose,
  onProceed,
}: Props) {
  const plan = useMemo(
    () => PRICING_PLANS.find((p) => p.id === planId) || null,
    [planId]
  );

  const [firmName, setFirmName] = useState("");
  const [firmGstin, setFirmGstin] = useState("");
  const [city, setCity] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  // Sync initial values when modal opens or initialData changes
  useEffect(() => {
    if (isOpen) {
      setFirmName(initialData?.firmName || "");
      setFirmGstin(initialData?.firmGstin || "");
      setCity(initialData?.firmCity || "");
      setFormError(null);
    }
  }, [isOpen, initialData]);

  if (!isOpen || !plan) return null;

  const basePrice = cycle === "yearly" ? plan.priceYearly : plan.priceMonthly;
  const gstAmount = Math.round(basePrice * 0.18);
  const totalAmount = basePrice + gstAmount;

  const cleanGstin = firmGstin.trim().toUpperCase();
  const stateCode =
    cleanGstin.length >= 2 && /^\d{2}$/.test(cleanGstin.slice(0, 2))
      ? cleanGstin.slice(0, 2)
      : SELLER_STATE_CODE;

  const stateName = GST_STATE_MAP[stateCode] || "Other";
  const isInterstate = stateCode !== SELLER_STATE_CODE;
  const isGstinEntered = cleanGstin.length > 0;
  const isGstinValid =
    !isGstinEntered ||
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(cleanGstin);

  const halfGst = Math.floor(gstAmount / 2);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!firmName.trim()) {
      setFormError("Please enter your Firm or Business Name");
      return;
    }
    if (isGstinEntered && !isGstinValid) {
      setFormError("Please enter a valid 15-character GSTIN format (e.g. 27AAAAA0000A1Z5)");
      return;
    }

    setFormError(null);
    await onProceed({
      firmName: firmName.trim(),
      firmGstin: cleanGstin || undefined,
      city: city.trim() || undefined,
      stateCode: stateCode,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-[var(--ink)]">Billing & GST Details</h2>
            <p className="text-xs text-gray-500">
              Tax invoice for {plan.name} Plan ({cycle === "yearly" ? "Annual" : "Monthly"})
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-slate-100 hover:text-gray-600 transition"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {formError && (
            <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-700 border border-red-200">
              {formError}
            </div>
          )}

          {/* Firm Name */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              Firm / Legal Trade Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={firmName}
              onChange={(e) => setFirmName(e.target.value)}
              placeholder="e.g. Kadam & Associates, Chartered Accountants"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm text-[var(--ink)] placeholder:text-gray-400 focus:border-[#7B5CFA] focus:ring-1 focus:ring-[#7B5CFA] outline-none"
            />
          </div>

          {/* GSTIN */}
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                Firm GSTIN <span className="text-xs font-normal text-gray-400 lowercase">(optional for B2C)</span>
              </label>
              <span className="text-[11px] font-medium text-[#7B5CFA]">Claim 100% ITC</span>
            </div>
            <input
              type="text"
              maxLength={15}
              value={firmGstin}
              onChange={(e) => setFirmGstin(e.target.value.toUpperCase())}
              placeholder="e.g. 27AAAAA0000A1Z5"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-mono tracking-wider text-[var(--ink)] placeholder:text-gray-400 focus:border-[#7B5CFA] focus:ring-1 focus:ring-[#7B5CFA] outline-none"
            />
            {isGstinEntered && !isGstinValid && (
              <p className="mt-1 text-xs text-amber-600">
                GSTIN should be 15 alphanumeric characters.
              </p>
            )}
            {isGstinEntered && isGstinValid && (
              <p className="mt-1 text-xs text-emerald-600 flex items-center gap-1 font-medium">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Place of Supply: {stateCode} - {stateName} ({isInterstate ? "Inter-State IGST" : "Intra-State CGST+SGST"})
              </p>
            )}
          </div>

          {/* City */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              City / State
            </label>
            <input
              type="text"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="e.g. Pune, Maharashtra"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm text-[var(--ink)] placeholder:text-gray-400 focus:border-[#7B5CFA] focus:ring-1 focus:ring-[#7B5CFA] outline-none"
            />
          </div>

          {/* Order Summary & Tax Breakdown */}
          <div className="rounded-xl bg-slate-50 p-4 border border-slate-200/70 space-y-2.5">
            <div className="flex justify-between text-xs text-slate-600">
              <span>
                {plan.name} Plan ({cycle === "yearly" ? "Annual" : "Monthly"})
              </span>
              <span className="font-semibold text-slate-800">₹{formatInr(basePrice)}</span>
            </div>

            {isInterstate ? (
              <div className="flex justify-between text-xs text-slate-600">
                <span>Integrated Tax (IGST 18%)</span>
                <span className="font-semibold text-slate-800">₹{formatInr(gstAmount)}</span>
              </div>
            ) : (
              <>
                <div className="flex justify-between text-xs text-slate-600">
                  <span>Central Tax (CGST 9%)</span>
                  <span className="font-semibold text-slate-800">₹{formatInr(halfGst)}</span>
                </div>
                <div className="flex justify-between text-xs text-slate-600">
                  <span>State Tax (SGST 9%)</span>
                  <span className="font-semibold text-slate-800">₹{formatInr(gstAmount - halfGst)}</span>
                </div>
              </>
            )}

            <div className="border-t border-slate-200 pt-2 flex justify-between items-baseline">
              <span className="text-sm font-bold text-[var(--ink)]">Total Payable</span>
              <span className="text-lg font-extrabold text-[var(--ink)]">
                ₹{formatInr(totalAmount)}
              </span>
            </div>

            {isGstinEntered && isGstinValid && (
              <div className="rounded-lg bg-emerald-50/80 p-2.5 text-[11px] text-emerald-800 border border-emerald-200/60 leading-relaxed flex items-start gap-1.5">
                <svg className="w-4 h-4 shrink-0 text-emerald-600 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>
                  <strong>₹{formatInr(gstAmount)}</strong> will be credited as Input Tax Credit (ITC) to your GST ledger and auto-populate in your firm’s GSTR-2B.
                </span>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-5 py-2.5 text-xs font-bold text-white bg-[var(--ink)] hover:bg-slate-800 rounded-lg shadow-sm transition disabled:opacity-50 flex items-center gap-2"
            >
              {loading && (
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
              )}
              <span>Proceed to Pay ₹{formatInr(totalAmount)}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
