import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import Razorpay from "razorpay";

type PlanPricing = {
  monthly: { priceInr: number; gstinLimit: number; periodDays: number; overagePerGstin?: number };
  yearly: { priceInr: number; gstinLimit: number; periodDays: number; overagePerGstin?: number };
};

const PLAN_CATALOG: Record<string, PlanPricing> = {
  starter: {
    monthly: { priceInr: 1199, gstinLimit: 25, periodDays: 30 },
    yearly: { priceInr: 9999, gstinLimit: 25, periodDays: 365 },
  },
  growth: {
    monthly: { priceInr: 1799, gstinLimit: 50, periodDays: 30 },
    yearly: { priceInr: 14999, gstinLimit: 50, periodDays: 365 },
  },
  pro: {
    monthly: { priceInr: 2399, gstinLimit: 100, periodDays: 30 },
    yearly: { priceInr: 19999, gstinLimit: 100, periodDays: 365 },
  },
  firm: {
    monthly: { priceInr: 2399, gstinLimit: 100, periodDays: 30, overagePerGstin: 25 },
    yearly: { priceInr: 19999, gstinLimit: 100, periodDays: 365, overagePerGstin: 200 },
  },
  monthly: {
    monthly: { priceInr: 1199, gstinLimit: 25, periodDays: 30 },
    yearly: { priceInr: 9999, gstinLimit: 25, periodDays: 365 },
  },
};

export async function POST(request: Request) {
  try {
    const supabase = createClient();
    if (!supabase) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const {
      data: { user },
      error: userError,
    } = await supabase.auth.getUser();

    if (userError || !user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const { plan_name, billing_cycle = "yearly", custom_gstin_limit } = body;

    if (!plan_name || typeof plan_name !== "string") {
      return NextResponse.json({ error: "Invalid plan_name" }, { status: 400 });
    }

    const planNameLower = plan_name.toLowerCase();
    const tierConfig = PLAN_CATALOG[planNameLower];

    if (!tierConfig) {
      return NextResponse.json({ error: "Invalid plan selected" }, { status: 400 });
    }

    const cycleKey = billing_cycle === "monthly" ? "monthly" : "yearly";
    const cycleConfig = tierConfig[cycleKey];

    let baseAmountInr = cycleConfig.priceInr;
    let gstinLimit = cycleConfig.gstinLimit;
    let overageGstins = 0;
    const overageRateInr = cycleConfig.overagePerGstin || 0;

    if (planNameLower === "firm") {
      const requestedLimit = parseInt(String(custom_gstin_limit), 10);
      if (!Number.isNaN(requestedLimit) && requestedLimit > 100) {
        overageGstins = requestedLimit - 100;
        gstinLimit = requestedLimit;
        baseAmountInr += overageGstins * overageRateInr;
      }
    }

    const baseAmountPaise = baseAmountInr * 100;
    const gstPaise = Math.round(baseAmountPaise * 0.18);
    const totalAmountPaise = baseAmountPaise + gstPaise;

    if (totalAmountPaise < 100) {
      return NextResponse.json({ error: "Amount must be at least 100 paise" }, { status: 400 });
    }

    if (!process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID || !process.env.RAZORPAY_KEY_SECRET) {
      return NextResponse.json({ error: "Razorpay keys not configured" }, { status: 500 });
    }

    const razorpay = new Razorpay({
      key_id: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
      key_secret: process.env.RAZORPAY_KEY_SECRET,
    });

    const orderOptions = {
      amount: totalAmountPaise,
      currency: "INR",
      receipt: `rcpt_${user.id.replace(/-/g, "").slice(0, 8)}_${Date.now()}`.substring(0, 40),
      notes: {
        plan: planNameLower,
        plan_version: "2",
        billing_cycle: cycleKey,
        gstin_limit: String(gstinLimit),
        period_days: String(cycleConfig.periodDays),
        overage_gstins: String(overageGstins),
      },
    };

    let razorpayOrder;
    try {
      razorpayOrder = await razorpay.orders.create(orderOptions);
    } catch (error: unknown) {
      console.error("Razorpay order creation error:", error);
      return NextResponse.json({ error: "Failed to create order with payment gateway" }, { status: 500 });
    }

    const paymentRow = {
      firm_owner_id: user.id,
      razorpay_order_id: razorpayOrder.id,
      plan: planNameLower,
      plan_version: 2,
      billing_cycle: cycleKey,
      gstin_limit: gstinLimit,
      overage_gstins: overageGstins,
      overage_rate_paise: overageRateInr * 100,
      runs_purchased: 0,
      base_amount_paise: baseAmountPaise,
      gst_paise: gstPaise,
      total_amount_paise: totalAmountPaise,
      amount_paise: totalAmountPaise,
      status: "created" as const,
    };

    const { error: dbError } = await (supabase.from("payments") as any).insert(paymentRow);

    if (dbError) {
      console.warn("Database insert with v2 fields failed, falling back to core columns:", dbError);
      const fallbackRow = {
        firm_owner_id: user.id,
        razorpay_order_id: razorpayOrder.id,
        plan: planNameLower,
        runs_purchased: 0,
        base_amount_paise: baseAmountPaise,
        gst_paise: gstPaise,
        total_amount_paise: totalAmountPaise,
        amount_paise: totalAmountPaise,
        status: "created" as const,
      };
      await (supabase.from("payments") as any).insert(fallbackRow);
    }

    return NextResponse.json({
      order_id: razorpayOrder.id,
      amount: razorpayOrder.amount,
      currency: razorpayOrder.currency,
      plan: planNameLower,
      billing_cycle: cycleKey,
      gstin_limit: gstinLimit,
      period_days: cycleConfig.periodDays,
      base_paise: baseAmountPaise,
      gst_paise: gstPaise,
      overage_gstins: overageGstins,
    });
  } catch (error: unknown) {
    console.error("Create order error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
