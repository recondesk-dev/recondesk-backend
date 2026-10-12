"use client";

import React, { useState } from "react";
import useSWR from "swr";
import { Sparkles, Copy, Check, ArrowRight, ShieldCheck, Clock, Tag } from "lucide-react";
import { customerCouponsApi, type CustomerExclusiveOffer } from "@/lib/api";
import { formatInr, type PricingTierId } from "@/lib/pricing-data";

type Props = {
  accessToken: string | null;
  onApplyOffer: (planId: PricingTierId, couponCode: string) => void;
};

const PLAN_DISPLAY_NAMES: Record<string, string> = {
  solo: "Solo Annual Plan",
  firm: "Firm Annual Plan",
  large_firm: "Large Firm Annual Plan",
};

export function ExclusiveOffersSection({ accessToken, onApplyOffer }: Props) {
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const { data: offers, isLoading } = useSWR(
    accessToken ? ["customer-exclusive-offers", accessToken] : null,
    ([, t]) => customerCouponsApi.getMyOffers(t),
    { revalidateOnFocus: true }
  );

  if (isLoading || !offers || offers.length === 0) {
    return null;
  }

  function handleCopy(code: string) {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2500);
  }

  return (
    <section className="space-y-4 animate-in fade-in duration-300">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-sm">
          <Sparkles className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            Your Exclusive Offers
            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-semibold text-purple-700">
              Account Specific
            </span>
          </h2>
          <p className="text-xs text-slate-500">
            Private negotiated discounts assigned directly to your CA account for annual subscriptions.
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {offers.map((offer) => {
          const planKey = (offer.eligible_plan || "firm").toLowerCase() as PricingTierId;
          const planTitle = PLAN_DISPLAY_NAMES[planKey] || `${offer.eligible_plan.toUpperCase()} Annual Plan`;
          const isCopied = copiedCode === offer.code;

          const daysLeft = offer.expires_at
            ? Math.ceil((new Date(offer.expires_at).getTime() - Date.now()) / (1000 * 3600 * 24))
            : null;

          return (
            <div
              key={offer.id}
              className="relative overflow-hidden rounded-2xl border-2 border-purple-200/90 bg-gradient-to-br from-white via-purple-50/30 to-indigo-50/40 p-5 shadow-sm hover:shadow-md transition"
            >
              <div className="absolute top-0 right-0 rounded-bl-xl bg-purple-600 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-white shadow-sm">
                {offer.discount_percentage}% Discount
              </div>

              <div className="space-y-4">
                {/* Header */}
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-purple-600">
                    Negotiated CA Rate
                  </div>
                  <h3 className="text-base font-bold text-slate-900 mt-0.5">{planTitle}</h3>
                </div>

                {/* Coupon Code Pill */}
                <div className="flex items-center justify-between rounded-xl border border-purple-200 bg-white/90 p-2.5 px-3">
                  <div className="flex items-center gap-2">
                    <Tag className="h-4 w-4 text-purple-500" />
                    <div>
                      <div className="text-[10px] font-medium uppercase text-slate-400">Coupon Code</div>
                      <div className="font-mono text-sm font-bold tracking-wider text-slate-800">
                        {offer.code}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleCopy(offer.code)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition"
                  >
                    {isCopied ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-emerald-600" />
                        <span className="text-emerald-700">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5 text-slate-500" />
                        <span>Copy Code</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Price Breakdown */}
                <div className="rounded-xl bg-white/80 p-3.5 border border-purple-100 space-y-1.5 text-xs">
                  <div className="flex justify-between text-slate-500">
                    <span>Standard Annual Base:</span>
                    <span className="line-through">₹{formatInr(offer.original_base_paise / 100)}</span>
                  </div>
                  <div className="flex justify-between font-semibold text-purple-700">
                    <span>Exclusive Discount ({offer.discount_percentage}%):</span>
                    <span>-₹{formatInr(offer.discount_amount_paise / 100)}</span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>Discounted Base:</span>
                    <span>₹{formatInr(offer.discounted_base_paise / 100)}</span>
                  </div>
                  <div className="flex justify-between text-slate-500">
                    <span>GST (18%):</span>
                    <span>+₹{formatInr(offer.gst_paise / 100)}</span>
                  </div>
                  <div className="pt-1.5 border-t border-purple-100 flex justify-between items-baseline">
                    <span className="font-bold text-slate-900">Total Payable:</span>
                    <span className="text-base font-extrabold text-emerald-700">
                      ₹{formatInr(offer.total_paise / 100)}
                      <span className="text-[11px] font-normal text-slate-500"> / year</span>
                    </span>
                  </div>
                </div>

                {/* Expiry and Validity Note */}
                <div className="flex items-center justify-between text-[11px] text-slate-500">
                  <div className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5 text-slate-400" />
                    <span>
                      {offer.expires_at ? (
                        daysLeft != null && daysLeft > 0 ? (
                          `Expires in ${daysLeft} day${daysLeft === 1 ? "" : "s"}`
                        ) : (
                          `Valid until ${new Date(offer.expires_at).toLocaleDateString()}`
                        )
                      ) : (
                        "No expiration set"
                      )}
                    </span>
                  </div>
                  <span className="flex items-center gap-1 text-slate-400">
                    <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" /> Verified 1-Year Rate
                  </span>
                </div>

                {/* CTA Button */}
                <button
                  type="button"
                  onClick={() => onApplyOffer(planKey, offer.code)}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-purple-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-purple-700 transition"
                >
                  <span>Apply Coupon &amp; Subscribe</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
