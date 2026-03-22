import logging

logger = logging.getLogger(__name__)

_ph = None


def init_app(app):
    global _ph
    api_key = app.config.get("POSTHOG_API_KEY")
    if not api_key:
        logger.warning("POSTHOG_API_KEY not set — PostHog analytics disabled")
        return
    try:
        import posthog

        posthog.api_key = api_key
        posthog.host = "https://us.i.posthog.com"
        posthog.on_error = lambda e, items: logger.error("PostHog error: %s", e)
        _ph = posthog
        logger.info("PostHog analytics initialized")
    except ImportError:
        logger.warning("posthog package not installed — analytics disabled")


def capture(distinct_id, event, properties=None):
    if _ph is None:
        return
    try:
        _ph.capture(str(distinct_id), event, properties or {})
    except Exception:
        logger.warning("PostHog capture failed for %s", event, exc_info=True)
