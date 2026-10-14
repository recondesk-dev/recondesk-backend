"use client";

import React, { useState, useEffect } from "react";
import {
  Tag,
  Search,
  Building2,
  Mail,
  User,
  ShieldCheck,
  CheckCircle2,
  Calendar,
  FileText,
  Percent,
  Sparkles,
  X,
  AlertCircle,
  Loader2,
} from "lucide-react";
import {
  couponsAdminApi,
  type TenantSearchResult,
  type PrivateCouponAssignInput,
} from "@/lib/api";
import { formatInr } from "@/lib/pricing-data";

type Props = {
  isOpen: boolean;
  authToken: string;
  onClose: () => void;
  onSuccess: () => void;
};

const PLAN_RATES: Record<string, { name: string; base: number; gstins: number }> = {
  solo: { name: "Solo Annual Plan", base: 8999, gstins: 25 },
  firm: { name: "Firm Annual Plan", base: 14999, gstins: 75 },
  large_firm: { name: "Large Firm Annual Plan", base: 18999, gstins: 150 },
};

export function AssignPrivateOfferModal({
  isOpen,
  authToken,
  onClose,
  onSuccess,
}: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<TenantSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedTenant, setSelectedTenant] = useState<TenantSearchResult | null>(null);

  const [selectedPlan, setSelectedPlan] = useState<"solo" | "firm" | "large_firm">("firm");
  const [discountTier, setDiscountTier] = useState<20 | 25 | 40>(25);
  const [expiresAt, setExpiresAt] = useState("");
  const [salesNotes, setSalesNotes] = useState("");
  const [customCode, setCustomCode] = useState("");
  const [founderNotes, setFounderNotes] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Search debounced
  useEffect(() => {
    if (!isOpen) return;
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const results = await couponsAdminApi.searchTenants(authToken, q, 10);
        setSearchResults(results);
      } catch (err: any) {
        console.error("Failed to search tenants:", err);
      } finally {
        setIsSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, authToken, isOpen]);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setSearchQuery("");
      setSearchResults([]);
      setSelectedTenant(null);
      setSelectedPlan("firm");
      setDiscountTier(25);
      setExpiresAt("");
      setSalesNotes("");
      setCustomCode("");
      setFounderNotes("");
      setErrorMessage(null);
      setIsSubmitting(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  // Real-time authoritative price calculations
  const planInfo = PLAN_RATES[selectedPlan];
  const originalBase = planInfo.base;
  const discountAmount = Math.round(originalBase * (discountTier / 100));
  const discountedBase = originalBase - discountAmount;
  const gstAmount = Math.round(discountedBase * 0.18);
  const totalAmount = discountedBase + gstAmount;

  async function handleAssign(activateNow: boolean) {
    if (!selectedTenant) {
      setErrorMessage("Please select a target CA customer from the tenant search.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    const payload: PrivateCouponAssignInput = {
      tenant_id: selectedTenant.id,
      plan: selectedPlan,
      discount_percentage: discountTier,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      sales_notes: salesNotes.trim() || null,
      custom_code: customCode.trim() || null,
      activate_now: activateNow,
      founder_approval_notes: discountTier === 40 ? founderNotes.trim() || null : null,
    };

    try {
      await couponsAdminApi.assignOffer(authToken, payload);
      onSuccess();
      onClose();
    } catch (err: any) {
      setErrorMessage(err.detail || err.error || "Failed to assign offer to customer.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-purple-600" />
              Assign Private CA Offer
            </h2>
            <p className="text-xs text-slate-500">
              Create an exclusive, account-restricted discount negotiated with a CA customer.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-slate-100 hover:text-gray-600 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {errorMessage && (
            <div className="rounded-xl bg-red-50 p-3.5 text-xs font-medium text-red-700 border border-red-200 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 text-red-600 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Step 1: Customer Account Selection */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              1. Select Target CA Customer <span className="text-red-500">*</span>
            </label>

            {selectedTenant ? (
              <div className="rounded-xl border-2 border-purple-300 bg-purple-50/50 p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-200 text-purple-700">
                    <Building2 className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="font-bold text-slate-900 flex items-center gap-2">
                      <span>{selectedTenant.firm_name || selectedTenant.full_name || "CA Account"}</span>
                      {selectedTenant.subscription_tier && (
                        <span className="rounded bg-purple-200 px-1.5 py-0.5 text-[10px] font-semibold text-purple-800 uppercase">
                          {selectedTenant.subscription_tier}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-600 flex items-center gap-2 mt-0.5">
                      <span>{selectedTenant.email}</span>
                      {selectedTenant.full_name && selectedTenant.firm_name && (
                        <>
                          <span>•</span>
                          <span>Contact: {selectedTenant.full_name}</span>
                        </>
                      )}
                    </div>
                    <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                      ID: {selectedTenant.id}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setSelectedTenant(null)}
                  className="rounded-lg border border-purple-200 bg-white px-3 py-1.5 text-xs font-semibold text-purple-700 hover:bg-purple-100 transition"
                >
                  Change
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="relative">
                  <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search by firm name, CA name, or email..."
                    className="w-full rounded-xl border border-slate-300 pl-10 pr-4 py-2 text-xs text-slate-900 placeholder:text-slate-400 outline-none focus:border-purple-600 focus:ring-1 focus:ring-purple-600"
                  />
                  {isSearching && (
                    <Loader2 className="absolute right-3.5 top-2.5 h-4 w-4 animate-spin text-purple-600" />
                  )}
                </div>

                {searchResults.length > 0 && (
                  <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-sm divide-y divide-slate-100">
                    {searchResults.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => {
                          setSelectedTenant(t);
                          setSearchQuery("");
                          setSearchResults([]);
                        }}
                        className="w-full text-left p-3 hover:bg-purple-50/50 transition flex items-center justify-between group"
                      >
                        <div>
                          <div className="font-semibold text-xs text-slate-900 group-hover:text-purple-700">
                            {t.firm_name || t.full_name || t.email}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            {t.email} {t.full_name && t.firm_name ? `• ${t.full_name}` : ""}
                          </div>
                        </div>
                        <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600 group-hover:bg-purple-600 group-hover:text-white transition">
                          Select
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {searchQuery.trim().length >= 2 && !isSearching && searchResults.length === 0 && (
                  <div className="p-3 text-center text-xs text-slate-400 rounded-xl border border-dashed border-slate-200">
                    No matching CA customer accounts found.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Step 2: Eligible Annual Plan */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              2. Eligible Annual Plan <span className="text-red-500">*</span>
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {(["solo", "firm", "large_firm"] as const).map((planKey) => {
                const info = PLAN_RATES[planKey];
                const isSelected = selectedPlan === planKey;
                return (
                  <button
                    key={planKey}
                    type="button"
                    onClick={() => setSelectedPlan(planKey)}
                    className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition ${
                      isSelected
                        ? "border-purple-600 bg-purple-50/60 text-purple-900 ring-2 ring-purple-600/20"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span className="font-bold text-xs capitalize">{planKey.replace("_", " ")}</span>
                    <span className="text-[10px] text-slate-500 mt-0.5">{info.gstins} GSTINs</span>
                    <span className="text-xs font-extrabold text-slate-900 mt-1">
                      {formatInr(info.base)}/yr
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Step 3: Discount Percentage Tier */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              3. Negotiated Discount Tier <span className="text-red-500">*</span>
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {[20, 25, 40].map((tier) => (
                <button
                  key={tier}
                  type="button"
                  onClick={() => setDiscountTier(tier as 20 | 25 | 40)}
                  className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition ${
                    discountTier === tier
                      ? "border-purple-600 bg-purple-50/60 text-purple-900 ring-2 ring-purple-600/20"
                      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="text-base font-extrabold">{tier}% OFF</span>
                  <span className="text-[10px] text-slate-500">
                    {tier === 20 ? "Standard CA" : tier === 25 ? "High-Intent" : "Founder Approval"}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Founder Warning for 40% */}
          {discountTier === 40 && (
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-3.5 space-y-2">
              <div className="flex items-center gap-2 text-xs font-bold text-amber-900">
                <ShieldCheck className="h-4 w-4 text-amber-700" />
                <span>Founder Authorization Strictly Required for 40%</span>
              </div>
              <p className="text-[11px] text-amber-800">
                The server will verify that your authenticated staff account belongs to the authorized founder team.
              </p>
              <div>
                <label className="block text-[11px] font-semibold text-amber-900 uppercase">
                  Founder Approval Notes / Justification
                </label>
                <input
                  type="text"
                  value={founderNotes}
                  onChange={(e) => setFounderNotes(e.target.value)}
                  placeholder="e.g. Approved for annual strategic partnership with large Mumbai CA firm"
                  className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-1.5 text-xs text-slate-900 outline-none focus:border-amber-600 bg-white"
                />
              </div>
            </div>
          )}

          {/* Step 4: Expiry & Notes */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                Offer Expiry Date (Optional)
              </label>
              <input
                type="date"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-900 outline-none focus:border-purple-600 focus:ring-1 focus:ring-purple-600"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                Custom Code (Optional)
              </label>
              <input
                type="text"
                value={customCode}
                onChange={(e) => setCustomCode(e.target.value.toUpperCase())}
                placeholder="Auto-generated if empty"
                className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 text-xs font-mono uppercase text-slate-900 placeholder:text-slate-400 outline-none focus:border-purple-600 focus:ring-1 focus:ring-purple-600"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              Internal Sales Notes
            </label>
            <textarea
              rows={2}
              value={salesNotes}
              onChange={(e) => setSalesNotes(e.target.value)}
              placeholder="e.g. Negotiated on call with partner CA Sharma for firm plan with 50+ clients."
              className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-900 placeholder:text-slate-400 outline-none focus:border-purple-600 focus:ring-1 focus:ring-purple-600"
            />
          </div>

          {/* Authoritative Live Price Breakdown Preview */}
          <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-4 space-y-2">
            <div className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center justify-between">
              <span>Customer Price Preview</span>
              <span className="text-[11px] font-normal text-slate-500">18% GST Computed</span>
            </div>
            <div className="space-y-1.5 text-xs text-slate-600">
              <div className="flex justify-between">
                <span>Standard Annual Base:</span>
                <span>{formatInr(originalBase)}</span>
              </div>
              <div className="flex justify-between text-purple-700 font-semibold">
                <span>Discount ({discountTier}%):</span>
                <span>-{formatInr(discountAmount)}</span>
              </div>
              <div className="flex justify-between">
                <span>Discounted Base:</span>
                <span>{formatInr(discountedBase)}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>GST (18%):</span>
                <span>+{formatInr(gstAmount)}</span>
              </div>
              <div className="pt-2 border-t border-slate-200 flex justify-between items-baseline font-bold text-slate-900">
                <span>Total Annual Payable:</span>
                <span className="text-base font-extrabold text-emerald-700">
                  {formatInr(totalAmount)}
                  <span className="text-xs font-normal text-slate-500"> / year</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="border-t border-slate-100 bg-slate-50/70 px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-[11px] text-slate-500">
            Codes are unique, high-entropy, and single-use for the selected CA.
          </p>

          <div className="flex items-center gap-2.5 w-full sm:w-auto">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleAssign(false)}
              className="flex-1 sm:flex-none rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition disabled:opacity-50"
            >
              Save as Draft
            </button>
            <button
              type="button"
              disabled={isSubmitting || !selectedTenant}
              onClick={() => handleAssign(true)}
              className="flex-1 sm:flex-none inline-flex items-center justify-center gap-1.5 rounded-xl bg-purple-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-purple-700 transition disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Assigning...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Assign &amp; Activate</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
