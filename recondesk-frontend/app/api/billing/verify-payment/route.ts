import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import crypto from "crypto";

export async function POST(request: Request) {
  try {
    // Use the regular (anon) client only for auth — it reads the user's session
    // from the cookie store, which is what establishes who is calling this route.
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

    // Verify HMAC signature — confirms the request genuinely came from Razorpay
    const generatedSignature = crypto
      .createHmac("sha256", secret)
      .update(`${razorpay_order_id}|${razorpay_payment_id}`)
      .digest("hex");

    if (generatedSignature !== razorpay_signature) {
      return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
    }

    // All DB writes from here use the admin (service-role) client, which bypasses
    // RLS. This is intentional: crediting runs is a trusted server-side action
    // that must succeed regardless of the user's RLS policies.
    const adminDb = createAdminClient();

    // Idempotency check — look up the pending payments row
    const { data: order, error: orderError } = await adminDb
      .from("payments")
      .select("*")
      .eq("razorpay_order_id", razorpay_order_id)
      .single();

    if (orderError || !order) {
      console.error("Order lookup failed:", orderError);
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    // Ownership check — the authenticated user must own this payment row
    if (order.firm_owner_id !== user.id) {
      console.error(`User ${user.id} tried to verify order owned by ${order.firm_owner_id}`);
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    if (order.status === "paid") {
      // Idempotency: payment was already credited, return success
      return NextResponse.json({ success: true, message: "Order already processed" });
    }

    // Mark the payment row as paid
    const { error: updateOrderError } = await adminDb
      .from("payments")
      .update({ status: "paid", razorpay_payment_id: razorpay_payment_id })
      .eq("id", order.id);

    if (updateOrderError) {
      console.error("Failed to update payment status:", updateOrderError);
      return NextResponse.json({ error: "Failed to update payment status" }, { status: 500 });
    }

    // Credit the runs — fetch current balance and increment atomically
    const { data: profile, error: profileFetchError } = await adminDb
      .from("user_profiles")
      .select("runs_balance")
      .eq("id", user.id)
      .single();

    if (profileFetchError || !profile) {
      console.error("Failed to fetch user profile for crediting:", profileFetchError);
      return NextResponse.json({ error: "Failed to fetch profile for crediting" }, { status: 500 });
    }

    const currentBalance = profile.runs_balance ?? 0;
    const runsToCredit = order.runs_purchased ?? 0;
    const newBalance = currentBalance + runsToCredit;

    const { error: updateProfileError } = await adminDb
      .from("user_profiles")
      .update({ runs_balance: newBalance })
      .eq("id", user.id);

    if (updateProfileError) {
      console.error("Failed to credit runs_balance:", updateProfileError);
      // Payment is already marked paid — log this for manual reconciliation
      return NextResponse.json(
        { error: "Payment recorded but run credit failed — contact support" },
        { status: 500 }
      );
    }

    console.log(
      `[verify-payment] Credited ${runsToCredit} run(s) to user ${user.id}. ` +
      `Balance: ${currentBalance} → ${newBalance}. Order: ${order.id}`
    );

    return NextResponse.json({
      success: true,
      message: "Payment verified and runs credited",
      runs_credited: runsToCredit,
      new_balance: newBalance,
    });
  } catch (error: any) {
    console.error("Verify payment error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
