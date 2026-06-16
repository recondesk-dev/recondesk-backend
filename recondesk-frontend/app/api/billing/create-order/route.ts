import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import Razorpay from "razorpay";

const PLANS: Record<string, { priceInr: number; runs: number }> = {
  starter: { priceInr: 499, runs: 1 },
  growth: { priceInr: 1699, runs: 5 },
  pro: { priceInr: 3699, runs: 12 },
  scale: { priceInr: 5699, runs: 30 },
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

    // Include 18% GST (if applicable, though prompt config was just the base numbers.
    // The prompt says "starter: ₹499, 1 run". I will use the exact amount for the Razorpay order.)
    // Wait, the frontend says "All prices exclude GST. 18% GST applicable."
    // Let's add 18% GST to the final amount if that's what's expected, but the prompt says:
    // "starter: ₹499, 1 run"
    // So amount is 499 + 18% GST.
    // Let's stick to base amount first, or I can add 18% GST. Let's add 18% GST because the frontend says it.
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

    // Create Razorpay order
    const orderOptions = {
      amount: totalAmountPaise,
      currency: "INR",
      receipt: `receipt_${user.id}_${Date.now()}`.substring(0, 40),
    };

    let razorpayOrder;
    try {
      razorpayOrder = await razorpay.orders.create(orderOptions);
    } catch (error: any) {
      console.error("Razorpay order creation error:", error);
      return NextResponse.json({ error: "Failed to create order with payment gateway" }, { status: 500 });
    }

    // Insert into payments table
    const { error: dbError } = await supabase.from("payments").insert({
      firm_owner_id: user.id,
      razorpay_order_id: razorpayOrder.id,
      plan: planNameLower,
      runs_purchased: planConfig.runs,
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
    });
  } catch (error: any) {
    console.error("Create order error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
