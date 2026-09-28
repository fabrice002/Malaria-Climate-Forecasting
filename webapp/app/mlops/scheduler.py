"""
Scheduler — the pipeline's autonomous trigger.

This module is what separates "a scriptable pipeline" from "an operational
platform": nobody has to launch anything.

Two triggers:

* **Monthly cron** — by default the 2nd of the month at 03:00, giving the ERA5
  reanalysis time to publish the month just ended.
* **New-data detection** — a light hourly-ish check that looks at whether the
  source exposes a month more recent than the last one already predicted, and
  runs the pipeline if so. Essential for the `csv` source (IoT drops), which has
  no publication calendar at all.

APScheduler is optional: without it the application starts normally, with
scheduling disabled and an explicit log message.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

_scheduler = None


def _job_scheduled_run() -> None:
    """Full monthly run."""
    from app.mlops.config import mlops_settings
    from app.mlops.service import run_pipeline

    districts = [d.strip() for d in mlops_settings.scheduled_districts.split(",")
                 if d.strip()] or None
    try:
        result = run_pipeline(districts=districts, trigger="scheduler")
        logger.info("scheduled run finished: %s — %s predictions",
                    result.get("status"), result.get("n_predictions"))
    except Exception:                                      # noqa: BLE001
        logger.exception("the scheduled run failed")


def _job_detect_new_data() -> None:
    """Light check: is new data available?

    Only triggers the full pipeline when the source exposes a month later than
    the most recent stored prediction. Avoids pointless re-scoring.
    """
    from app.db.base import SessionLocal
    from app.models.orm import Prediction
    from app.mlops.service import run_pipeline

    db = SessionLocal()
    try:
        last = (db.query(Prediction)
                .order_by(Prediction.year.desc(), Prediction.month.desc())
                .first())
    finally:
        db.close()

    today = date.today()
    # The most recent complete month one could reasonably expect.
    latest_available = (today.year, today.month - 1) if today.month > 1 \
        else (today.year - 1, 12)

    if last and (last.year, last.month) >= latest_available:
        logger.debug("no new data (last predicted month %s-%02d)",
                     last.year, last.month)
        return

    logger.info("new data detected -> starting the pipeline")
    try:
        run_pipeline(trigger="auto-detect")
    except Exception:                                      # noqa: BLE001
        logger.exception("the auto-triggered run failed")


def start_scheduler() -> bool:
    """Start the scheduler. Returns False when disabled or unavailable."""
    global _scheduler
    from app.mlops.config import mlops_settings

    if not mlops_settings.scheduler_enabled:
        logger.info("scheduler disabled (MEWS_SCHEDULER_ENABLED=false)")
        return False

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler missing — scheduling inactive. "
                       "Install with: pip install apscheduler")
        return False

    minute, hour, dom, month, dow = mlops_settings.schedule_cron.split()

    _scheduler = BackgroundScheduler(timezone="Africa/Douala")
    _scheduler.add_job(_job_scheduled_run,
                       CronTrigger(minute=minute, hour=hour, day=dom,
                                   month=month, day_of_week=dow),
                       id="monthly_run", replace_existing=True,
                       max_instances=1, coalesce=True)
    _scheduler.add_job(_job_detect_new_data, "interval", hours=6,
                       id="detect_new_data", replace_existing=True,
                       max_instances=1, coalesce=True)
    _scheduler.start()

    logger.info("scheduler started — cron '%s' plus a check every 6 h",
                mlops_settings.schedule_cron)
    return True


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict:
    from app.mlops.config import mlops_settings

    if _scheduler is None:
        return {"running": False, "enabled": mlops_settings.scheduler_enabled,
                "jobs": []}
    return {
        "running": True,
        "enabled": True,
        "jobs": [{"id": j.id,
                  "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
                 for j in _scheduler.get_jobs()],
    }
