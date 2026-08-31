import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scrapers.orchestrator import OpportunityOrchestrator
from cache_engine import newsletter_store
from notifier import LeadAlertDispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("IngestionDaemon")

async def run_scheduled_job():
    logger.info("⏰ Starting scheduled multi-source intelligence ingestion...")
    try:
        orchestrator = OpportunityOrchestrator()
        result = await orchestrator.run_pipeline()
        leads = result.get("leads", [])
        newsletter_store.save(leads)
        for lead in leads:
            # dispatch_high_priority_alert applies HIGH_PRIORITY_SCORE (7.0)
            # itself. The duplicate literal 9.2 that used to gate this call
            # was stricter than that, so it silently suppressed every alert
            # scoring 7.0-9.19 — the same bug already fixed in api.py's
            # background_scraping_job, which this loop was copied from.
            await LeadAlertDispatcher.dispatch_high_priority_alert(lead)
        logger.info(f"✅ Ingestion cycle complete. Ingested: {len(leads)} signals.")
    except Exception as e:
        logger.error(f"❌ Scheduled scraping job encountered an error: {e}")

async def main():
    scheduler = AsyncIOScheduler()
    # Runs immediately on start, then every 6 hours
    scheduler.add_job(run_scheduled_job, "interval", hours=6)
    scheduler.start()
    logger.info("🚀 RO-INTEL Ingestion Daemon initialized. Scheduled every 6 hours.")

    await run_scheduled_job()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Daemon stopped.")

if __name__ == "__main__":
    asyncio.run(main())
