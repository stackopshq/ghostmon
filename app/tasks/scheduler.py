from apscheduler.schedulers.asyncio import AsyncIOScheduler


def build_scheduler() -> AsyncIOScheduler:
    """Placeholder scheduler factory. Background probe jobs will be added here."""
    return AsyncIOScheduler()
