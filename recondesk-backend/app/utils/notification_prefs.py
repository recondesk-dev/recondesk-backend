import logging
from app.database import get_supabase

logger = logging.getLogger(__name__)


def should_send_notification(user_id: str, category: str) -> bool:
    """Check if email notifications for a specific category are enabled for a user.

    If the user has no preferences row, defaults to True.
    Categories: 'run_completed', 'runs_expiring_soon', 'payment_receipts',
    'rule37_alerts'.
    """
    if not user_id:
        return True

    allowed = {
        "run_completed",
        "runs_expiring_soon",
        "payment_receipts",
        "rule37_alerts",
    }
    if category not in allowed:
        logger.warning("Unknown notification category %s — defaulting to True", category)
        return True

    # 1. Primary: AWS Aurora PostgreSQL repository
    try:
        from app.repositories.portal_and_audit import get_portal_and_audit_repository
        repo = get_portal_and_audit_repository()
        pref = repo.get_notification_preferences(user_id)
        if pref is not None:
            return bool(pref.get(category, True))
    except Exception as aurora_exc:
        logger.warning(
            "Aurora fetch notification preferences failed user %s: %s; falling back to Supabase",
            user_id,
            aurora_exc,
        )

    # 2. Supabase Fallback (temporary, non-blocking)
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
