import razorpay

from app.config import settings

_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

# Amounts in paise (INR). Matches billing_gate.PLAN_CONFIG base amounts.
PLAN_PRICES = {
    "monthly": {"monthly": 999_00},
    "starter": {"yearly": 599_900},
    "growth": {"yearly": 999_900},
    "pro": {"yearly": 999_900},
}


def create_order(plan: str, billing_period: str = "yearly") -> dict:
    """Create a Razorpay order for a subscription plan."""
    amount = PLAN_PRICES.get(plan, {}).get(billing_period)
    if amount is None:
        # Fallback: first available period for the plan, else starter yearly
        periods = PLAN_PRICES.get(plan) or PLAN_PRICES["starter"]
        amount = next(iter(periods.values()), 599_900)
    order_data = {
        "amount": amount,
        "currency": "INR",
        "payment_capture": 1,
        "notes": {"plan": plan, "billing_period": billing_period},
    }
    return _client.order.create(data=order_data)


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature to confirm successful payment."""
    params = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }
    try:
        _client.utility.verify_payment_signature(params)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def fetch_payment(payment_id: str) -> dict:
    return _client.payment.fetch(payment_id)
