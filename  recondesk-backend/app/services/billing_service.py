import razorpay

from app.config import settings

_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

# TODO: update Razorpay plan IDs — legacy subscription pricing, update when new plans are created in Razorpay dashboard
PLAN_PRICES = {
    "starter":    {"monthly": 99900,  "yearly": 999900},   # amounts in paise (INR)
    "growth":     {"monthly": 299900, "yearly": 2999900},
    "enterprise": {"monthly": 999900, "yearly": 9999900},
}


def create_order(plan: str, billing_period: str = "monthly") -> dict:
    """Create a Razorpay order for a subscription plan."""
    amount = PLAN_PRICES.get(plan, {}).get(billing_period, 99900)
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
