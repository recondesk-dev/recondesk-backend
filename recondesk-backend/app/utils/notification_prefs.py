import logging
from app.database import get_supabase

logger = logging.getLogger(__name__)


def should_send_notification(user_id: str, category: str) -> bool:
    """Check if email notifications for a specific category are enabled for a user.

    If the user has no preferences row, defaults to True.
    Categories: 'run_completed', 'runs_expiring_soon', 'payment_receipts'.
    """
    if not user_id:
        return True

    try:
        client = get_supabase()
        res = (
            client.table("notification_preferences")
            .select(category)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return bool(res.data[0].get(category, True))
    except Exception as exc:
        logger.warning(
            "Failed to fetch notification preferences for user %s: %s",
            user_id,
            exc,
        )

    return True


async def should_send_notification_async(user_id: str, category: str) -> bool:
    """Async wrapper for should_send_notification."""
    return should_send_notification(user_id, category)
