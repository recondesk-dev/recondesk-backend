import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import crypto from "crypto";

const PLAN_ENTITLEMENTS: Record<
  string,
  { gstinLimit: number; periodDays: number }
> = {
  starter: { gstinLimit: 25, periodDays: 30 },
  growth: { gstinLimit: 50, periodDays: 365 },
  pro: { gstinLimit: 75, periodDays: 365 },
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

    const plan = String(order.plan || "starter").toLowerCase();
    const entitlement = PLAN_ENTITLEMENTS[plan];
    if (!entitlement) {
      return NextResponse.json({ error: "Invalid plan on order" }, { status: 400 });
    }

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
    endsAt.setDate(endsAt.getDate() + entitlement.periodDays);

    const { data: updatedProfile, error: updateProfileError } = await adminDb
      .from("user_profiles")
      .update({
        plan,
        gstin_limit: entitlement.gstinLimit,
        subscription_ends_at: endsAt.toISOString(),
      })
      .eq("id", user.id)
      .select("id, plan, gstin_limit, subscription_ends_at");

    if (updateProfileError) {
      console.error("Failed to activate subscription (DB error):", updateProfileError);
      return NextResponse.json(
        { error: "Payment recorded but subscription activation failed — contact support" },
        { status: 500 }
      );
    }

    if (!updatedProfile || updatedProfile.length === 0) {
      console.error(
        `[verify-payment] ZERO ROWS UPDATED on user_profiles. user.id=${user.id}`
      );
      return NextResponse.json(
        { error: "Payment recorded but subscription matched no profile row — contact support" },
        { status: 500 }
      );
    }

    console.log(
      `[verify-payment] Activated ${plan} for user ${user.id}. ` +
        `GSTIN limit ${entitlement.gstinLimit}, ends ${endsAt.toISOString()}. Order: ${order.id}`
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
      gstin_limit: entitlement.gstinLimit,
      subscription_ends_at: endsAt.toISOString(),
    });
  } catch (error: unknown) {
    console.error("Verify payment error:", error);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}
