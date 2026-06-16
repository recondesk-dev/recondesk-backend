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

    // Fetch current balance so we can compute the new value.
    // Both this fetch and the subsequent update use adminDb (service-role),
    // bypassing RLS. The filter is .eq("id", user.id) — user_profiles.id
    // is the auth.uid() UUID, confirmed by the Row type in types.ts.
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

    // Create the run_credits batch so the backend's sync logic doesn't erase this balance
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + 30);

    const { error: runCreditError } = await adminDb
      .from("run_credits")
      .insert({
        firm_owner_id: user.id,
        payment_id: order.id,
        plan: order.plan || "starter",
        runs_purchased: runsToCredit,
        runs_remaining: runsToCredit,
        expires_at: expiresAt.toISOString(),
      });

    if (runCreditError) {
      console.error("Failed to create run_credits batch:", runCreditError);
      return NextResponse.json(
        { error: "Payment recorded but credit batch creation failed — contact support" },
        { status: 500 }
      );
    }

    // Chain .select() after .update() so Supabase returns the updated row.
    const { data: updatedProfile, error: updateProfileError } = await adminDb
      .from("user_profiles")
      .update({ runs_balance: newBalance })
      .eq("id", user.id)
      .select("id, runs_balance");

    if (updateProfileError) {
      console.error("Failed to credit runs_balance (DB error):", updateProfileError);
      return NextResponse.json(
        { error: "Payment recorded but run credit failed — contact support" },
        { status: 500 }
      );
    }

    if (!updatedProfile || updatedProfile.length === 0) {
      console.error(
        `[verify-payment] ZERO ROWS UPDATED on user_profiles. ` +
        `user.id=${user.id}, attempted newBalance=${newBalance}. ` +
        `Check that user_profiles.id matches auth.uid() for this user.`
      );
      return NextResponse.json(
        { error: "Payment recorded but run credit matched no profile row — contact support" },
        { status: 500 }
      );
    }

    const actualNewBalance = updatedProfile[0].runs_balance;

    // VERIFICATION STEP: fresh re-read of the balance immediately after update
    const { data: verifyRead, error: verifyError } = await adminDb
      .from("user_profiles")
      .select("runs_balance")
      .eq("id", user.id)
      .single();

    if (verifyError) {
      console.error("[verify-payment] Re-read verification failed:", verifyError);
    } else {
      console.log(`[verify-payment] Verification re-read: balance is genuinely ${verifyRead?.runs_balance} in DB`);
    }

    console.log(
      `[verify-payment] Credited ${runsToCredit} run(s) to user ${user.id}. ` +
      `Balance: ${currentBalance} → ${actualNewBalance}. Order: ${order.id}`
    );

    return NextResponse.json({
      success: true,
      message: "Payment verified and runs credited",
      runs_credited: runsToCredit,
      new_balance: actualNewBalance,
    });
  } catch (error: any) {
    console.error("Verify payment error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
