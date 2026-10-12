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

  // Promotional Coupon State
  const [couponCodeInput, setCouponCodeInput] = useState("");
  const [couponLoading, setCouponLoading] = useState(false);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [appliedCoupon, setAppliedCoupon] = useState<{
    code: string;
    discountPercentage: number;
    originalBasePaise: number;
    discountAmountPaise: number;
    discountedBasePaise: number;
    gstPaise: number;
    totalPaise: number;
  } | null>(null);

  // Sync initial values when modal opens or initialData changes
  useEffect(() => {
    if (isOpen) {
      setFirmName(initialData?.firmName || "");
      setFirmGstin(initialData?.firmGstin || "");
      setCity(initialData?.firmCity || "");
      setFormError(null);
      setCouponCodeInput("");
      setCouponError(null);
      setAppliedCoupon(null);
    }
  }, [isOpen, initialData]);

  if (!isOpen || !plan) return null;

  // Base pricing
  const standardBasePrice = cycle === "yearly" ? plan.priceYearly : plan.priceMonthly;
  const originalBasePrice = standardBasePrice;
  const discountAmount = appliedCoupon ? appliedCoupon.discountAmountPaise / 100 : 0;
  const finalBasePrice = appliedCoupon ? appliedCoupon.discountedBasePaise / 100 : standardBasePrice;

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

  // Authoritative GST and Total amounts (matches backend paise rounding)
  const gstAmount = appliedCoupon
    ? appliedCoupon.gstPaise / 100
    : Math.round(standardBasePrice * 0.18);
  const totalAmount = appliedCoupon
    ? appliedCoupon.totalPaise / 100
    : standardBasePrice + gstAmount;

  const halfGst = Math.floor(gstAmount / 2);

  async function handleApplyCoupon() {
    const cleanCode = couponCodeInput.trim().toUpperCase();
    if (!cleanCode) {
      setCouponError("Please enter a coupon code");
      return;
    }
    if (cycle !== "yearly") {
      setCouponError("Promotional coupons are available only for annual subscription plans.");
      return;
    }
    setCouponLoading(true);
    setCouponError(null);
    try {
      const res = await fetch("/api/billing/validate-coupon", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: cleanCode,
          plan: plan?.id,
          billing_cycle: cycle,
          customer_gstin: cleanGstin || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setCouponError(data.detail || data.error || "Invalid or ineligible coupon code.");
        setAppliedCoupon(null);
        return;
      }
      setAppliedCoupon({
        code: data.code,
        discountPercentage: data.discount_percentage,
        originalBasePaise: data.original_base_paise,
        discountAmountPaise: data.discount_amount_paise,
        discountedBasePaise: data.discounted_base_paise,
        gstPaise: data.gst_paise,
        totalPaise: data.total_paise,
      });
      setCouponError(null);
    } catch {
      setCouponError("Unable to validate coupon. Please try again.");
    } finally {
      setCouponLoading(false);
    }
  }

  function handleRemoveCoupon() {
    setAppliedCoupon(null);
    setCouponCodeInput("");
    setCouponError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (couponLoading) return;
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
      couponCode: appliedCoupon?.code,
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

          {/* Coupon Code Section */}
          {cycle === "yearly" ? (
            <div className="rounded-xl border border-slate-200/90 bg-slate-50/70 p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-[#7B5CFA]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                  </svg>
                  Have a coupon code?
                </label>
                {appliedCoupon && (
                  <button
                    type="button"
                    onClick={handleRemoveCoupon}
                    className="text-xs font-semibold text-rose-600 hover:text-rose-700 hover:underline transition"
                  >
                    Remove Coupon
                  </button>
                )}
              </div>

              {!appliedCoupon ? (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={couponCodeInput}
                    onChange={(e) => {
                      setCouponCodeInput(e.target.value.toUpperCase());
                      if (couponError) setCouponError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void handleApplyCoupon();
                      }
                    }}
                    placeholder="Enter coupon code (e.g. CA25)"
                    disabled={couponLoading || loading}
                    className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono font-medium uppercase tracking-wider text-[var(--ink)] placeholder:text-gray-400 placeholder:normal-case focus:border-[#7B5CFA] focus:ring-1 focus:ring-[#7B5CFA] outline-none disabled:bg-slate-100"
                  />
                  <button
                    type="button"
                    onClick={() => void handleApplyCoupon()}
                    disabled={couponLoading || loading || !couponCodeInput.trim()}
                    className="px-4 py-2 text-xs font-bold text-white bg-slate-900 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition flex items-center gap-1.5 shadow-sm"
                  >
                    {couponLoading && (
                      <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    )}
                    <span>Apply</span>
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between rounded-lg bg-emerald-50 border border-emerald-200/80 px-3 py-2 text-xs text-emerald-800 font-medium">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 font-bold text-[11px]">
                      ✓
                    </span>
                    <span>
                      Coupon <strong className="font-mono tracking-wider font-bold text-emerald-900">{appliedCoupon.code}</strong> applied ({appliedCoupon.discountPercentage}% OFF)
                    </span>
                  </div>
                  <span className="font-bold text-emerald-700">
                    −₹{formatInr(discountAmount)}
                  </span>
                </div>
              )}

              {couponError && (
                <div className="rounded-lg bg-red-50 p-2.5 text-xs font-medium text-red-700 border border-red-200 flex items-start gap-1.5">
                  <svg className="w-4 h-4 shrink-0 text-red-500 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{couponError}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/70 bg-slate-50/80 p-3 text-xs text-slate-500 flex items-center gap-2">
              <svg className="w-4 h-4 text-slate-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Promotional coupons (20%–30%) are available only for annual subscription plans.</span>
            </div>
          )}

          {/* Order Summary & Tax Breakdown */}
          <div className="rounded-xl bg-slate-50 p-4 border border-slate-200/70 space-y-2.5">
            <div className="flex justify-between text-xs text-slate-600">
              <span>
                {plan.name} Plan ({cycle === "yearly" ? "Annual" : "Monthly"})
              </span>
              <span className={`font-semibold ${appliedCoupon ? "line-through text-slate-400" : "text-slate-800"}`}>
                ₹{formatInr(originalBasePrice)}
              </span>
            </div>

            {appliedCoupon && (
              <>
                <div className="flex justify-between text-xs text-emerald-700 font-medium">
                  <span className="flex items-center gap-1">
                    Coupon: {appliedCoupon.code} ({appliedCoupon.discountPercentage}% OFF)
                  </span>
                  <span className="font-semibold">−₹{formatInr(discountAmount)}</span>
                </div>
                <div className="flex justify-between text-xs text-slate-700 font-semibold border-t border-dashed border-slate-200 pt-1.5">
                  <span>Discounted Base (Taxable)</span>
                  <span>₹{formatInr(finalBasePrice)}</span>
                </div>
              </>
            )}

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
              disabled={loading || couponLoading}
              className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || couponLoading}
              className="px-5 py-2.5 text-xs font-bold text-white bg-[var(--ink)] hover:bg-slate-800 rounded-lg shadow-sm transition disabled:opacity-50 flex items-center gap-2"
            >
              {(loading || couponLoading) && (
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
