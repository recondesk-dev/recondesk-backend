/** Client-side Razorpay checkout for GSTIN subscription plans. */

export type CheckoutPlan = "monthly" | "starter" | "growth" | "pro";

type RazorpaySuccessResponse = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: (response: RazorpaySuccessResponse) => void;
  theme?: { color?: string };
  modal?: { ondismiss?: () => void };
};

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => { open: () => void };
  }
}

function loadRazorpayScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Razorpay requires a browser"));
  }
  if (window.Razorpay) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[src="https://checkout.razorpay.com/v1/checkout.js"]'
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Failed to load Razorpay")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay"));
    document.body.appendChild(script);
  });
}

export async function startPlanCheckout(
  plan: CheckoutPlan,
  opts?: { onSuccess?: () => void; onDismiss?: () => void }
): Promise<void> {
  const key = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID;
  if (!key) {
    throw new Error("Payment is not configured");
  }

  const orderRes = await fetch("/api/billing/create-order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_name: plan }),
  });
  const orderBody = (await orderRes.json().catch(() => ({}))) as {
    error?: string;
    order_id?: string;
    amount?: number;
    currency?: string;
  };
  if (!orderRes.ok || !orderBody.order_id || orderBody.amount == null) {
    throw new Error(orderBody.error || "Failed to create order");
  }

  await loadRazorpayScript();
  if (!window.Razorpay) {
    throw new Error("Razorpay failed to initialize");
  }

  const labels: Record<CheckoutPlan, string> = {
    monthly: "Monthly · 25 GSTINs / month",
    starter: "Starter · 50 GSTINs / year",
    growth: "Growth · 100 GSTINs / year",
    pro: "Pro · 100 GSTINs / year",
  };

  await new Promise<void>((resolve, reject) => {
    const rzp = new window.Razorpay!({
      key,
      amount: Number(orderBody.amount),
      currency: orderBody.currency || "INR",
      name: "ReconDesk",
      description: labels[plan],
      order_id: orderBody.order_id!,
      theme: { color: "#111111" },
      modal: {
        ondismiss: () => {
          opts?.onDismiss?.();
          resolve();
        },
      },
      handler: (response) => {
        void (async () => {
          try {
            const verifyRes = await fetch("/api/billing/verify-payment", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              }),
            });
            const verifyBody = (await verifyRes.json().catch(() => ({}))) as {
              error?: string;
            };
            if (!verifyRes.ok) {
              reject(new Error(verifyBody.error || "Payment verification failed"));
              return;
            }
            opts?.onSuccess?.();
            resolve();
          } catch (err) {
            reject(err instanceof Error ? err : new Error("Payment verification failed"));
          }
        })();
      },
    });
    rzp.open();
  });
}
