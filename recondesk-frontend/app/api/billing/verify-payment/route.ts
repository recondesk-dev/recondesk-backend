import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import crypto from "crypto";

const DEFAULT_TIER_LIMITS: Record<string, number> = {
  free: 2,
  solo: 25,
  firm: 75,
  large_firm: 150,
  "large-firm": 150,
  starter: 25,
  growth: 60,
  pro: 100,
  monthly: 25,
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
    const { razorpay_order_id, razorpay_payment_id, razorpay_signature } = body;

    if (!razorpay_order_id || !razorpay_payment_id || !razorpay_signature) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const secret = process.env.RAZORPAY_KEY_SECRET;
    if (!secret) {
      return NextResponse.json({ error: "Razorpay secret not configured" }, { status: 500 });
    }

    const generatedSignature = crypto
      .createHmac("sha256", secret)
      .update(`${razorpay_order_id}|${razorpay_payment_id}`)
      .digest("hex");

    if (generatedSignature !== razorpay_signature) {
      return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
    }

    const adminDb = createAdminClient();

    const { data: order, error: orderError } = await adminDb
      .from("payments")
      .select("*")
      .eq("razorpay_order_id", razorpay_order_id)
      .single();

    if (orderError || !order) {
      console.error("Order lookup failed:", orderError);
      return NextResponse.json({ error: "Order not found" }, { status: 404 });
    }

    if (order.firm_owner_id !== user.id) {
      console.error(`User ${user.id} tried to verify order owned by ${order.firm_owner_id}`);
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }

    if (order.status === "paid") {
      return NextResponse.json({ success: true, message: "Order already processed" });
    }

    const orderRec = order as any;
    const plan = String(orderRec.plan || "starter").toLowerCase();
    const cycle = String(orderRec.billing_cycle || (plan === "monthly" ? "monthly" : "yearly")).toLowerCase();
    const periodDays = cycle === "monthly" ? 30 : 365;
    const gstinLimit = orderRec.gstin_limit || DEFAULT_TIER_LIMITS[plan] || 25;

    const { error: updateOrderError } = await adminDb
      .from("payments")
      .update({ status: "paid", razorpay_payment_id: razorpay_payment_id })
      .eq("id", order.id);

    if (updateOrderError) {
      console.error("Failed to update payment status:", updateOrderError);
      return NextResponse.json({ error: "Failed to update payment status" }, { status: 500 });
    }

    const { data: profile, error: profileFetchError } = await adminDb
      .from("user_profiles")
      .select("subscription_ends_at")
      .eq("id", user.id)
      .single();

    if (profileFetchError || !profile) {
      console.error("Failed to fetch user profile for subscription:", profileFetchError);
      return NextResponse.json({ error: "Failed to fetch profile for subscription" }, { status: 500 });
    }

    const now = new Date();
    let base = now;
    if (profile.subscription_ends_at) {
      const existing = new Date(profile.subscription_ends_at);
      if (!Number.isNaN(existing.getTime()) && existing > now) {
        base = existing;
      }
    }
    const endsAt = new Date(base.getTime());
    endsAt.setDate(endsAt.getDate() + periodDays);

    const updateProfilePayload: Record<string, unknown> = {
      plan,
      plan_version: orderRec.plan_version || 2,
      billing_cycle: cycle,
      gstin_limit: gstinLimit,
      subscription_ends_at: endsAt.toISOString(),
    };
    if (orderRec.overage_gstins && orderRec.overage_gstins > 0) {
      updateProfilePayload.overage_gstin_count = orderRec.overage_gstins;
    }

    let { data: updatedProfile, error: updateProfileError } = await (adminDb
      .from("user_profiles") as any)
      .update(updateProfilePayload)
      .eq("id", user.id)
      .select("id, plan, gstin_limit, subscription_ends_at");

    if (updateProfileError) {
      console.warn("Update profile with v2 columns failed, falling back to core columns:", updateProfileError);
      const fallbackPayload = {
        plan,
        gstin_limit: gstinLimit,
        subscription_ends_at: endsAt.toISOString(),
      };
      const res = await (adminDb
        .from("user_profiles") as any)
        .update(fallbackPayload)
        .eq("id", user.id)
        .select("id, plan, gstin_limit, subscription_ends_at");
      updatedProfile = res.data;
      updateProfileError = res.error;
    }

    if (updateProfileError) {
      console.error("Failed to activate subscription (DB error):", updateProfileError);
      return NextResponse.json(
        { error: "Payment recorded but subscription activation failed — contact support" },
        { status: 500 }
      );
    }

    if (!updatedProfile || updatedProfile.length === 0) {
      console.error(`[verify-payment] ZERO ROWS UPDATED on user_profiles. user.id=${user.id}`);
      return NextResponse.json(
        { error: "Payment recorded but subscription matched no profile row — contact support" },
        { status: 500 }
      );
    }

    console.log(
      `[verify-payment] Activated ${plan} (${cycle}) for user ${user.id}. ` +
        `GSTIN limit ${gstinLimit}, ends ${endsAt.toISOString()}. Order: ${order.id}`
    );

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const token = session?.access_token;
      if (token) {
        const backendUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
          /\/$/,
          ""
        );
        fetch(`${backendUrl}/api/payments/send-receipt`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ payment_id: order.id }),
        })
          .then((res) => {
            if (!res.ok)
              console.error(`[verify-payment] send-receipt API returned status ${res.status}`);
          })
          .catch((err) => console.error("[verify-payment] Failed to call send-receipt API:", err));
      } else {
        console.warn("[verify-payment] No active session token found; skipped triggering receipt email");
      }
    } catch (emailErr) {
      console.error("[verify-payment] Failed to fetch session/trigger receipt email:", emailErr);
    }

    return NextResponse.json({
      success: true,
      message: "Payment verified and subscription activated",
      plan,
      billing_cycle: cycle,
      gstin_limit: gstinLimit,
      subscription_ends_at: endsAt.toISOString(),
    });
  } catch (error: unknown) {
    console.error("Verify payment error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
