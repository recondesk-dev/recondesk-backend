import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import Razorpay from "razorpay";

const PLANS: Record<
  string,
  { priceInr: number; gstinLimit: number; periodDays: number; billingPeriod: string }
> = {
  monthly: { priceInr: 999, gstinLimit: 25, periodDays: 30, billingPeriod: "monthly" },
  starter: { priceInr: 5999, gstinLimit: 50, periodDays: 365, billingPeriod: "yearly" },
  growth: { priceInr: 9999, gstinLimit: 100, periodDays: 365, billingPeriod: "yearly" },
  pro: { priceInr: 9999, gstinLimit: 100, periodDays: 365, billingPeriod: "yearly" },
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
    const { plan_name } = body;

    if (!plan_name || typeof plan_name !== "string") {
      return NextResponse.json({ error: "Invalid plan_name" }, { status: 400 });
    }

    const planNameLower = plan_name.toLowerCase();
    const planConfig = PLANS[planNameLower];

    if (!planConfig) {
      return NextResponse.json({ error: "Invalid plan selected" }, { status: 400 });
    }

    const baseAmountPaise = planConfig.priceInr * 100;
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
      receipt: `receipt_${user.id}_${Date.now()}`.substring(0, 40),
      notes: {
        plan: planNameLower,
        gstin_limit: String(planConfig.gstinLimit),
        period_days: String(planConfig.periodDays),
        billing_period: planConfig.billingPeriod,
      },
    };

    let razorpayOrder;
    try {
      razorpayOrder = await razorpay.orders.create(orderOptions);
    } catch (error: unknown) {
      console.error("Razorpay order creation error:", error);
      return NextResponse.json({ error: "Failed to create order with payment gateway" }, { status: 500 });
    }

    const { error: dbError } = await supabase.from("payments").insert({
      firm_owner_id: user.id,
      razorpay_order_id: razorpayOrder.id,
      plan: planNameLower,
      runs_purchased: 0,
      base_amount_paise: baseAmountPaise,
      gst_paise: gstPaise,
      total_amount_paise: totalAmountPaise,
      amount_paise: totalAmountPaise,
      status: "created",
    });

    if (dbError) {
      console.error("Database error while inserting order:", dbError);
      return NextResponse.json({ error: "Failed to record order" }, { status: 500 });
    }

    return NextResponse.json({
      order_id: razorpayOrder.id,
      amount: razorpayOrder.amount,
      currency: razorpayOrder.currency,
      plan: planNameLower,
      gstin_limit: planConfig.gstinLimit,
      billing_period: planConfig.billingPeriod,
    });
  } catch (error: unknown) {
    console.error("Create order error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
