import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import crypto from "crypto";

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
    const { razorpay_order_id, razorpay_payment_id, razorpay_signature } = body;

    if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const secret = process.env.RAZORPAY_KEY_SECRET;
    if (!secret) {
      return NextResponse.json({ error: "Razorpay secret not configured" }, { status: 500 });
    }

    // Verify signature
    const generatedSignature = crypto
      .createHmac("sha256", secret)
      .update(`${razorpay_order_id}|${razorpay_payment_id}`)
      .digest("hex");

    if (generatedSignature !== razorpay_signature) {
      return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
    }

    // Idempotent check
    const { data: orderData, error: orderError } = await supabase
      .from("payments")
      .select("*")
      .eq("razorpay_order_id", razorpay_order_id)
      .single();

    const order = orderData as any;

    if (orderError) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    if (!order) {
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    if (order.status === "paid") {
      // Idempotency: return success if already paid
      return NextResponse.json({ success: true, message: "Order already processed" });
    }

    // Mark order as paid
    const { error: updateOrderError } = await supabase
      .from("payments")
      .update({ status: "paid", razorpay_payment_id: razorpay_payment_id } as any)
      .eq("id", order.id);

    if (updateOrderError) {
      console.error("Failed to update order status:", updateOrderError);
      return NextResponse.json({ error: "Failed to update order status" }, { status: 500 });
    }

    // Credit runs to user
    // Fetch current profile to get current runs_balance
    const { data: profile, error: profileError } = await supabase
      .from("user_profiles")
      .select("runs_balance")
      .eq("id", user.id)
      .single();

    if (profileError) {
      console.error("Failed to fetch user profile:", profileError);
      return NextResponse.json({ error: "Failed to credit runs" }, { status: 500 });
    }

    const currentBalance = profile?.runs_balance || 0;
    const newBalance = currentBalance + (order.runs_purchased || 0);

    const { error: updateProfileError } = await supabase
      .from("user_profiles")
      .update({ runs_balance: newBalance } as any)
      .eq("id", user.id);

    if (updateProfileError) {
      console.error("Failed to update user profile runs:", updateProfileError);
      return NextResponse.json({ error: "Failed to credit runs to profile" }, { status: 500 });
    }

    return NextResponse.json({ success: true, message: "Payment verified and runs credited" });
  } catch (error: any) {
    console.error("Verify payment error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
