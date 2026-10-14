"use client";

import React, { useState, useEffect } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Tag,
  Plus,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Users,
  Copy,
  Check,
  Percent,
  TrendingUp,
  Receipt,
  Sparkles,
  ArrowLeft,
  RefreshCw,
  Building2,
} from "lucide-react";

import {
  couponsAdminApi,
  type CouponRecord,
  type CouponCreateInput,
  type CouponRedemptionRecord,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  isFounderAccount,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { formatInr } from "@/lib/pricing-data";
import { AssignPrivateOfferModal } from "@/components/billing/AssignPrivateOfferModal";

export default function AdminCouponsPage() {
  const token = useAccessToken();
  const authToken = typeof token === "string" && token.length > 0 ? token : null;

  const { data: me, isLoading: meLoading } = useSWR(
    authToken ? ["settings-coupons-me", authToken] : null,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const [activeTab, setActiveTab] = useState<"coupons" | "redemptions">("coupons");
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Form State
  const [formCode, setFormCode] = useState("");
  const [formDiscount, setFormDiscount] = useState<20 | 25 | 40>(25);
  const [formPlans, setFormPlans] = useState<string[]>(["solo", "firm", "large_firm"]);
  const [formExpiresAt, setFormExpiresAt] = useState("");
  const [formMaxRedemptions, setFormMaxRedemptions] = useState<string>("");
  const [formMaxPerCustomer, setFormMaxPerCustomer] = useState<number>(1);
  const [formTenantId, setFormTenantId] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formIsAcquisitionOnly, setFormIsAcquisitionOnly] = useState(true);
  const [formFounderApproved, setFormFounderApproved] = useState(false);
  const [formFounderApprovedBy, setFormFounderApprovedBy] = useState("");
  const [formFounderNotes, setFormFounderNotes] = useState("");
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Fetch Coupons
  const {
    data: coupons,
    error: couponsError,
    isLoading: couponsLoading,
    mutate: mutateCoupons,
  } = useSWR(
    authToken ? ["admin-coupons-list", authToken] : null,
    ([, t]) => couponsAdminApi.list(t),
    { revalidateOnFocus: false }
  );

  // Fetch Analytics
  const { data: analytics, mutate: mutateAnalytics } = useSWR(
    authToken ? ["admin-coupons-analytics", authToken] : null,
    ([, t]) => couponsAdminApi.getAnalytics(t),
    { revalidateOnFocus: false }
  );

  // Fetch Redemptions
  const {
    data: redemptions,
    isLoading: redemptionsLoading,
    mutate: mutateRedemptions,
  } = useSWR(
    authToken && activeTab === "redemptions"
      ? ["admin-coupons-redemptions", authToken]
      : null,
    ([, t]) => couponsAdminApi.listRedemptions(t),
    { revalidateOnFocus: false }
  );

  const isForbidden =
    (!meLoading && me && !isFounderAccount(me)) ||
    (couponsError && (couponsError.status === 403 || couponsError.status === 401));

  function generateRandomCode(prefix = "CA", pct = 25) {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    let rand = "";
    for (let i = 0; i < 4; i++) {
      rand += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return `${prefix}${pct}_${rand}`;
  }

  function handleCopy(code: string) {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  }

  async function handleToggleStatus(coupon: CouponRecord) {
    if (!authToken) return;
    try {
      await couponsAdminApi.toggleStatus(authToken, coupon.id, !coupon.is_active);
      void mutateCoupons();
      void mutateAnalytics();
    } catch (err: any) {
      alert(err.detail || "Failed to update coupon status");
    }
  }

  async function handleActivateOffer(coupon: CouponRecord) {
    if (!authToken) return;
    try {
      await couponsAdminApi.activateOffer(authToken, coupon.id);
      void mutateCoupons();
      void mutateAnalytics();
    } catch (err: any) {
      alert(err.detail || "Failed to activate offer");
    }
  }

  async function handleRevokeOffer(coupon: CouponRecord) {
    if (!authToken) return;
    const reason = window.prompt("Reason for revoking this private offer (optional):");
    if (reason === null) return;
    try {
      await couponsAdminApi.revokeOffer(authToken, coupon.id, reason);
      void mutateCoupons();
      void mutateAnalytics();
    } catch (err: any) {
      alert(err.detail || "Failed to revoke offer");
    }
  }

  async function handleCreateSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!authToken) return;
    if (!formCode.trim()) {
      setFormError("Please enter a valid coupon code");
      return;
    }
    if (formPlans.length === 0) {
      setFormError("Please select at least one eligible annual plan");
      return;
    }

    setFormSubmitting(true);
    setFormError(null);

    const payload: CouponCreateInput = {
      code: formCode.trim().toUpperCase(),
      discount_percentage: formDiscount,
      eligible_plans: formPlans,
      expires_at: formExpiresAt ? new Date(formExpiresAt).toISOString() : null,
      max_redemptions: formMaxRedemptions ? parseInt(formMaxRedemptions, 10) : null,
      max_per_customer: formMaxPerCustomer,
      restricted_to_tenant_id: formTenantId.trim() || null,
      restricted_to_email: formEmail.trim() || null,
      is_acquisition_only: formIsAcquisitionOnly,
      founder_approved: true,
      founder_approved_by: me?.email || formFounderApprovedBy.trim() || "kadamomkar9988@gmail.com",
      founder_approval_notes: formFounderNotes.trim() || (formDiscount === 40 ? "Direct founder authorization" : null),
    };

    try {
      await couponsAdminApi.create(authToken, payload);
      setIsCreateModalOpen(false);
      setFormCode("");
      setFormExpiresAt("");
      setFormMaxRedemptions("");
      setFormTenantId("");
      setFormEmail("");
      setFormIsAcquisitionOnly(true);
      setFormFounderApproved(false);
      setFormFounderApprovedBy("");
      setFormFounderNotes("");
      void mutateCoupons();
      void mutateAnalytics();
    } catch (err: any) {
      setFormError(err.detail || err.error || "Failed to create coupon");
    } finally {
      setFormSubmitting(false);
    }
  }

  if (isForbidden) {
    return (
      <div className="mx-auto max-w-4xl p-8">
        <div className="rounded-2xl border border-red-200 bg-red-50/70 p-8 text-center space-y-4">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-100 text-red-600">
            <ShieldCheck className="h-8 w-8 text-red-600" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Founder Authorization Required</h2>
          <p className="text-sm text-slate-600 max-w-md mx-auto">
            Annual subscription coupon administration is strictly restricted to the authenticated ReconDesk founder account (kadamomkar9988@gmail.com).
            CA tenant administrators, sales staff, management staff, and ordinary platform administrators cannot access promotional coupon management.
          </p>
          <div className="pt-2">
            <Link
              href="/settings"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700 bg-white px-4 py-2 rounded-lg border border-slate-200 shadow-sm hover:bg-slate-50 transition"
            >
              <ArrowLeft className="h-4 w-4" /> Back to Settings
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-6">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#7B5CFA]">
            <Link href="/settings" className="hover:underline flex items-center gap-1">
              <ArrowLeft className="h-3.5 w-3.5" /> Settings
            </Link>
            <span>/</span>
            <span>Platform Administration</span>
          </div>
          <h1 className="mt-1 text-2xl font-bold text-slate-900 flex items-center gap-2.5">
            <Tag className="h-6 w-6 text-[#7B5CFA]" />
            Annual Subscription Coupons
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Manage high-intent promotional discount campaigns (20%, 25%, 40%) applied during GSTIN billing.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void mutateCoupons();
              void mutateAnalytics();
              if (activeTab === "redemptions") void mutateRedemptions();
            }}
            className="rounded-lg border border-slate-200 bg-white p-2.5 text-slate-600 shadow-sm hover:bg-slate-50 transition"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setIsAssignModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-purple-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-purple-700 transition"
          >
            <Sparkles className="h-4 w-4" />
            <span>Assign Private Offer</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setFormCode(generateRandomCode("CA", 25));
              setFormDiscount(25);
              setFormError(null);
              setIsCreateModalOpen(true);
            }}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-slate-800 transition"
          >
            <Plus className="h-4 w-4" />
            <span>Create Coupon</span>
          </button>
        </div>
      </div>

      {/* Metrics Banner */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
            <span>Total Coupons</span>
            <Tag className="h-4 w-4 text-purple-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {analytics?.total_coupons ?? coupons?.length ?? 0}
          </div>
          <div className="text-[11px] text-emerald-600 font-medium">
            {analytics?.active_coupons ?? coupons?.filter((c) => c.is_active).length ?? 0} Active Campaigns
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
            <span>Total Redemptions</span>
            <Users className="h-4 w-4 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {analytics?.total_redemptions ?? 0}
          </div>
          <div className="text-[11px] text-slate-500 font-medium">
            First-year subscriptions claimed
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
            <span>Total Discounts Given</span>
            <TrendingUp className="h-4 w-4 text-amber-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {formatInr((analytics?.total_discount_given_paise ?? 0) / 100)}
          </div>
          <div className="text-[11px] text-slate-500 font-medium">
            Base value savings credited
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm space-y-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
            <span>Revenue Realized</span>
            <Receipt className="h-4 w-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-bold text-emerald-700">
            {formatInr((analytics?.total_revenue_realized_paise ?? 0) / 100)}
          </div>
          <div className="text-[11px] text-emerald-600 font-medium">
            Net collected via Razorpay
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-3 border-b border-slate-200">
        <button
          type="button"
          onClick={() => setActiveTab("coupons")}
          className={`pb-3 text-xs font-bold transition border-b-2 flex items-center gap-1.5 ${
            activeTab === "coupons"
              ? "border-[#7B5CFA] text-[#7B5CFA]"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Tag className="h-4 w-4" />
          <span>Active Coupons ({coupons?.length ?? 0})</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("redemptions")}
          className={`pb-3 text-xs font-bold transition border-b-2 flex items-center gap-1.5 ${
            activeTab === "redemptions"
              ? "border-[#7B5CFA] text-[#7B5CFA]"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Receipt className="h-4 w-4" />
          <span>Redemption Logs</span>
        </button>
      </div>

      {/* Tab: Coupons List */}
      {activeTab === "coupons" && (
        <div className="rounded-2xl border border-slate-200/90 bg-white shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-100 bg-slate-50/70 text-slate-500 uppercase font-semibold tracking-wider">
                <tr>
                  <th className="px-6 py-3.5">Code</th>
                  <th className="px-6 py-3.5">Discount</th>
                  <th className="px-6 py-3.5">Eligible Plans</th>
                  <th className="px-6 py-3.5">Usage / Limit</th>
                  <th className="px-6 py-3.5">Restrictions</th>
                  <th className="px-6 py-3.5">Expires</th>
                  <th className="px-6 py-3.5">Status</th>
                  <th className="px-6 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {couponsLoading ? (
                  <tr>
                    <td colSpan={8} className="p-8 text-center text-slate-400">
                      Loading coupons...
                    </td>
                  </tr>
                ) : !coupons || coupons.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-8 text-center text-slate-400">
                      No coupons created yet. Click "Create Coupon" to launch your first promotional discount.
                    </td>
                  </tr>
                ) : (
                  coupons.map((c) => {
                    const isExpired = c.expires_at && new Date(c.expires_at) < new Date();
                    return (
                      <tr key={c.id} className="hover:bg-slate-50/50 transition">
                        {/* Code */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold tracking-wider text-slate-900 bg-slate-100 px-2.5 py-1 rounded-md border border-slate-200">
                              {c.code}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleCopy(c.code)}
                              className="text-slate-400 hover:text-slate-600 transition"
                              title="Copy code"
                            >
                              {copiedCode === c.code ? (
                                <Check className="h-3.5 w-3.5 text-emerald-600" />
                              ) : (
                                <Copy className="h-3.5 w-3.5" />
                              )}
                            </button>
                            {c.founder_approved && (
                              <span
                                className="inline-flex items-center gap-0.5 rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-bold text-purple-700"
                                title={`Founder Approved by: ${c.founder_approved_by || "Founder"}`}
                              >
                                <Sparkles className="h-3 w-3" /> Founder
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Discount */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-bold ${
                              c.discount_percentage >= 30
                                ? "bg-amber-100 text-amber-800"
                                : c.discount_percentage === 25
                                  ? "bg-purple-100 text-purple-800"
                                  : "bg-blue-100 text-blue-800"
                            }`}
                          >
                            <Percent className="h-3 w-3" />
                            {c.discount_percentage}% OFF
                          </span>
                        </td>

                        {/* Eligible Plans */}
                        <td className="px-6 py-4 text-slate-600">
                          <div className="flex flex-wrap gap-1">
                            {c.eligible_plans.map((p) => (
                              <span
                                key={p}
                                className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700 uppercase"
                              >
                                {p.replace("_", " ")}
                              </span>
                            ))}
                          </div>
                        </td>

                        {/* Usage / Limit */}
                        <td className="px-6 py-4 text-slate-700 font-medium">
                          <span>{c.redemptions_count}</span>
                          <span className="text-slate-400">
                            {" "}
                            / {c.max_redemptions != null ? c.max_redemptions : "∞"}
                          </span>
                        </td>

                        {/* Restrictions */}
                        <td className="px-6 py-4 text-[11px] text-slate-500">
                          {c.assigned_to_tenant_id ? (
                            <div className="space-y-0.5">
                              <span className="inline-flex items-center gap-1 rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold text-purple-700">
                                <Sparkles className="h-2.5 w-2.5" /> Private Offer
                              </span>
                              <div className="font-semibold text-slate-900 truncate max-w-[130px]">
                                {c.assigned_to_firm_name || c.assigned_to_name || "CA Account"}
                              </div>
                              <div className="text-[10px] text-slate-500 truncate max-w-[130px]" title={c.assigned_to_email || ""}>
                                {c.assigned_to_email || c.assigned_to_tenant_id.slice(0, 8)}
                              </div>
                              {c.sales_notes && (
                                <div className="text-[10px] text-slate-400 italic truncate max-w-[130px]" title={c.sales_notes}>
                                  Note: {c.sales_notes}
                                </div>
                              )}
                            </div>
                          ) : c.restricted_to_email ? (
                            <span className="truncate max-w-[120px] block" title={c.restricted_to_email}>
                              Email: {c.restricted_to_email}
                            </span>
                          ) : c.restricted_to_tenant_id ? (
                            <span className="truncate max-w-[120px] block" title={c.restricted_to_tenant_id}>
                              Tenant: {c.restricted_to_tenant_id.slice(0, 8)}...
                            </span>
                          ) : (
                            <span className="text-slate-400">Global</span>
                          )}
                        </td>

                        {/* Expires */}
                        <td className="px-6 py-4 text-[11px]">
                          {c.expires_at ? (
                            <span className={isExpired ? "text-rose-600 font-bold" : "text-slate-600"}>
                              {new Date(c.expires_at).toLocaleDateString()}
                              {isExpired && " (Expired)"}
                            </span>
                          ) : (
                            <span className="text-slate-400">Never</span>
                          )}
                        </td>

                        {/* Status */}
                        <td className="px-6 py-4">
                          {c.offer_status === "draft" ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                              <Clock className="h-3 w-3" /> Draft
                            </span>
                          ) : c.offer_status === "revoked" ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-bold text-rose-800" title={c.revoked_reason || "Revoked"}>
                              <XCircle className="h-3 w-3" /> Revoked
                            </span>
                          ) : c.redemptions_count >= (c.max_redemptions || 1) || c.offer_status === "redeemed" ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-blue-800">
                              <CheckCircle2 className="h-3 w-3" /> Redeemed
                            </span>
                          ) : c.is_active ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
                              <CheckCircle2 className="h-3 w-3" /> Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">
                              <XCircle className="h-3 w-3" /> Inactive
                            </span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {c.offer_status === "draft" && (
                              <button
                                type="button"
                                onClick={() => void handleActivateOffer(c)}
                                className="text-xs font-semibold px-2.5 py-1 rounded-lg border border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100 transition"
                              >
                                Activate
                              </button>
                            )}
                            {c.assigned_to_tenant_id && c.redemptions_count === 0 && c.offer_status !== "revoked" && (
                              <button
                                type="button"
                                onClick={() => void handleRevokeOffer(c)}
                                className="text-xs font-semibold px-2.5 py-1 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 transition"
                              >
                                Revoke
                              </button>
                            )}
                            {!c.assigned_to_tenant_id && (
                              <button
                                type="button"
                                onClick={() => void handleToggleStatus(c)}
                                className={`text-xs font-semibold px-3 py-1 rounded-lg border transition ${
                                  c.is_active
                                    ? "border-slate-200 text-slate-600 hover:bg-slate-50"
                                    : "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                                }`}
                              >
                                {c.is_active ? "Deactivate" : "Activate"}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Redemption History */}
      {activeTab === "redemptions" && (
        <div className="rounded-2xl border border-slate-200/90 bg-white shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-100 bg-slate-50/70 text-slate-500 uppercase font-semibold tracking-wider">
                <tr>
                  <th className="px-6 py-3.5">Order / Payment ID</th>
                  <th className="px-6 py-3.5">Plan</th>
                  <th className="px-6 py-3.5">Original</th>
                  <th className="px-6 py-3.5">Discount</th>
                  <th className="px-6 py-3.5">Final Paid</th>
                  <th className="px-6 py-3.5">Status</th>
                  <th className="px-6 py-3.5">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {redemptionsLoading ? (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-slate-400">
                      Loading redemption logs...
                    </td>
                  </tr>
                ) : !redemptions || redemptions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-slate-400">
                      No redemptions recorded yet.
                    </td>
                  </tr>
                ) : (
                  redemptions.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50/50 transition">
                      <td className="px-6 py-4">
                        <div className="font-mono text-[11px] font-bold text-slate-900">
                          {r.razorpay_payment_id || r.razorpay_order_id}
                        </div>
                        <div className="text-[10px] text-slate-400">Order: {r.razorpay_order_id}</div>
                      </td>
                      <td className="px-6 py-4 uppercase font-semibold text-slate-700">
                        {r.plan.replace("_", " ")}
                      </td>
                      <td className="px-6 py-4 text-slate-500">
                        {formatInr(r.original_base_amount_paise / 100)}
                      </td>
                      <td className="px-6 py-4 font-semibold text-emerald-600">
                        −{formatInr(r.discount_amount_paise / 100)}
                      </td>
                      <td className="px-6 py-4 font-bold text-slate-900">
                        {formatInr(r.total_amount_paise / 100)}
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${
                            r.status === "fulfilled"
                              ? "bg-emerald-100 text-emerald-800"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-500 text-[11px]">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Create Coupon Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="relative w-full max-w-lg rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-6 py-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                  <Tag className="h-5 w-5 text-[#7B5CFA]" /> Create Promotional Coupon
                </h2>
                <p className="text-xs text-slate-500">
                  Annual subscription discounts (strictly 20%, 25%, or 40%)
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-slate-100 hover:text-gray-600 transition"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
              {formError && (
                <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-700 border border-red-200">
                  {formError}
                </div>
              )}

              {/* Coupon Code */}
              <div>
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                    Coupon Code <span className="text-red-500">*</span>
                  </label>
                  <button
                    type="button"
                    onClick={() => setFormCode(generateRandomCode("CA", formDiscount))}
                    className="text-[11px] font-semibold text-[#7B5CFA] hover:underline"
                  >
                    Generate Random
                  </button>
                </div>
                <input
                  type="text"
                  required
                  value={formCode}
                  onChange={(e) => setFormCode(e.target.value.toUpperCase())}
                  placeholder="e.g. CA25, FIRM20, SPECIAL40"
                  className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-mono tracking-wider uppercase text-slate-900 placeholder:text-gray-400 focus:border-[#7B5CFA] focus:ring-1 focus:ring-[#7B5CFA] outline-none"
                />
              </div>

              {/* Discount Percentage Tiers */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                  Discount Tier <span className="text-red-500">*</span>
                </label>
                <div className="grid grid-cols-3 gap-2.5 mt-1.5">
                  {[20, 25, 40].map((tier) => (
                    <button
                      key={tier}
                      type="button"
                      onClick={() => {
                        setFormDiscount(tier as 20 | 25 | 40);
                        if (tier !== 40) setFormFounderApproved(false);
                      }}
                      className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition ${
                        formDiscount === tier
                          ? "border-[#7B5CFA] bg-purple-50/50 text-[#7B5CFA] ring-2 ring-[#7B5CFA]/20"
                          : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    >
                      <span className="text-base font-extrabold">{tier}%</span>
                      <span className="text-[10px] font-medium text-slate-500">
                        {tier === 20 ? "Standard CA" : tier === 25 ? "High-Intent" : "Strategic (Founder)"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Founder Approval Section (Required for 40%) */}
              {formDiscount === 40 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3.5 space-y-3">
                  <div className="flex items-center gap-2 text-xs font-bold text-amber-900">
                    <ShieldCheck className="h-4 w-4 text-amber-700" />
                    <span>Founder-Level Approval Mandatory for 40% Discount</span>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-amber-900 font-medium cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formFounderApproved}
                      onChange={(e) => setFormFounderApproved(e.target.checked)}
                      className="rounded text-amber-600 focus:ring-amber-500 h-4 w-4"
                    />
                    <span>I confirm founder approval has been granted for this code</span>
                  </label>
                  <div>
                    <label className="block text-[11px] font-semibold text-amber-900 uppercase">
                      Approved By (Founder Name) <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      required={formDiscount === 40}
                      value={formFounderApprovedBy}
                      onChange={(e) => setFormFounderApprovedBy(e.target.value)}
                      placeholder="e.g. Omkar Kadam (Founder)"
                      className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-1.5 text-xs text-slate-900 outline-none focus:border-amber-500 bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-amber-900 uppercase">
                      Approval Justification / Notes
                    </label>
                    <input
                      type="text"
                      value={formFounderNotes}
                      onChange={(e) => setFormFounderNotes(e.target.value)}
                      placeholder="e.g. Strategic annual CA partnership commitment"
                      className="mt-1 w-full rounded-lg border border-amber-300 px-3 py-1.5 text-xs text-slate-900 outline-none focus:border-amber-500 bg-white"
                    />
                  </div>
                </div>
              )}

              {/* Eligible Annual Plans */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                  Eligible Annual Plans
                </label>
                <div className="flex gap-4 mt-1.5">
                  {[
                    { id: "solo", name: "Solo (25 GSTINs)" },
                    { id: "firm", name: "Firm (75 GSTINs)" },
                    { id: "large_firm", name: "Large Firm (150 GSTINs)" },
                  ].map((p) => {
                    const isChecked = formPlans.includes(p.id);
                    return (
                      <label key={p.id} className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setFormPlans([...formPlans, p.id]);
                            } else {
                              setFormPlans(formPlans.filter((x) => x !== p.id));
                            }
                          }}
                          className="rounded text-[#7B5CFA] focus:ring-[#7B5CFA]"
                        />
                        <span>{p.name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Expiry Date */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                    Expiration Date (Optional)
                  </label>
                  <input
                    type="date"
                    value={formExpiresAt}
                    onChange={(e) => setFormExpiresAt(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 outline-none focus:border-[#7B5CFA]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                    Max Redemptions
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={formMaxRedemptions}
                    onChange={(e) => setFormMaxRedemptions(e.target.value)}
                    placeholder="Unlimited"
                    className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 outline-none focus:border-[#7B5CFA]"
                  />
                </div>
              </div>

              {/* Customer / Email Restrictions */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                  Restrict to Customer Email (Optional)
                </label>
                <input
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  placeholder="e.g. ca.sharma@example.com"
                  className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2 text-xs text-slate-900 outline-none focus:border-[#7B5CFA]"
                />
              </div>

              {/* Acquisition Only Setting */}
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formIsAcquisitionOnly}
                    onChange={(e) => setFormIsAcquisitionOnly(e.target.checked)}
                    className="mt-0.5 rounded text-[#7B5CFA] focus:ring-[#7B5CFA] h-4 w-4"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-900 block">First-Year Acquisition Only (Recommended)</span>
                    <span className="text-[11px] text-slate-500 block leading-relaxed mt-0.5">
                      Restricts redemption strictly to new subscribers. Existing subscribers and renewals cannot redeem this coupon.
                    </span>
                  </div>
                </label>
              </div>

              {/* Modal Actions */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  disabled={formSubmitting}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={formSubmitting}
                  className="px-5 py-2.5 text-xs font-bold text-white bg-slate-900 hover:bg-slate-800 rounded-lg shadow-sm transition disabled:opacity-50 flex items-center gap-2"
                >
                  {formSubmitting && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                  <span>Save & Activate Coupon</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Assign Private CA Offer Modal */}
      <AssignPrivateOfferModal
        isOpen={isAssignModalOpen}
        authToken={authToken || ""}
        onClose={() => setIsAssignModalOpen(false)}
        onSuccess={() => {
          void mutateCoupons();
          void mutateAnalytics();
        }}
      />
    </div>
  );
}
