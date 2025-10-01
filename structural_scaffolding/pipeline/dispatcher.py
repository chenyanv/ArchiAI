from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Optional

from structural_scaffolding.database import create_session
from structural_scaffolding.models import SummaryLevel

from .celery_app import celery_app
from .data_access import fetch_profiles_pending_l1, load_profiles_by_ids
from .tasks import generate_l1_summary

logger = logging.getLogger(__name__)
_DEFAULT_QUEUE = os.getenv("CELERY_DEFAULT_QUEUE", "l1_summary_queue")


def dispatch_l1_summary_tasks(
    *,
    limit: Optional[int] = None,
    database_url: str | None = None,
    queue: str | None = None,
    dry_run: bool = False,
    watch: bool = False,
    poll_interval: float = 30.0,
) -> int:
    if watch and dry_run:
        logger.warning("Watch mode is ignored when --dry-run is enabled")
        watch = False

    total_dispatched = 0
    target_queue = queue or _DEFAULT_QUEUE

    while True:
        session = create_session(database_url)
        try:
            profiles = fetch_profiles_pending_l1(session, limit=limit)

            if not profiles:
                logger.info("No profiles need L1 summaries")
                if not watch:
                    return total_dispatched
                logger.debug("Sleeping for %.1f seconds before next poll", poll_interval)
                time.sleep(max(poll_interval, 1.0))
                continue

            if dry_run:
                for record in profiles:
                    logger.info("Dry run: would enqueue %s", record.id)
                return len(profiles)

            queued_ids: list[str] = []
            for record in profiles:
                record.summary_level = SummaryLevel.LEVEL_1_IN_PROGRESS.value
                queued_ids.append(record.id)
            session.commit()

        except Exception:
            session.rollback()
            logger.exception("Failed while preparing L1 dispatch batch")
            raise
        finally:
            session.close()

        dispatched = 0
        failed_ids: list[str] = []

        for profile_id in queued_ids:
            try:
                generate_l1_summary.apply_async(
                    args=(profile_id,),
                    kwargs={"database_url": database_url},
                    queue=target_queue,
                )
            except Exception:
                failed_ids.append(profile_id)
                logger.exception(
                    "Failed to enqueue L1 summary task",
                    extra={"profile_id": profile_id, "queue": target_queue},
                )
                continue

            dispatched += 1
            logger.info(
                "Enqueued L1 summary task",
                extra={"profile_id": profile_id, "queue": target_queue},
            )

        if failed_ids:
            logger.warning("Resetting %s profiles to NONE after enqueue failure", len(failed_ids))
            reset_session = create_session(database_url)
            try:
                for record in load_profiles_by_ids(reset_session, failed_ids):
                    record.summary_level = SummaryLevel.NONE.value
                reset_session.commit()
            except Exception:
                reset_session.rollback()
                logger.exception("Failed to reset summary state for %s", failed_ids)
            finally:
                reset_session.close()

        total_dispatched += dispatched
        logger.info("Dispatched %s tasks to %s", dispatched, target_queue)

        if not watch:
            return total_dispatched

        logger.debug("Sleeping for %.1f seconds before next poll", poll_interval)
        time.sleep(max(poll_interval, 1.0))



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch L1 summary generation tasks")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on number of profiles to dispatch")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override STRUCTURAL_SCAFFOLD_DB_URL if needed",
    )
    parser.add_argument("--queue", type=str, default=None, help="Celery queue name (defaults to CELERY_DEFAULT_QUEUE)")
    parser.add_argument("--dry-run", action="store_true", help="List tasks without enqueuing them")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling for new profiles and dispatch them as they appear",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Polling interval in seconds when --watch is enabled (default: 30)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with celery_app.connection_or_acquire():
        count = dispatch_l1_summary_tasks(
            limit=args.limit,
            database_url=args.database_url,
            queue=args.queue,
            dry_run=args.dry_run,
            watch=args.watch,
            poll_interval=args.interval,
        )

    logger.info("Total tasks considered: %s", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["dispatch_l1_summary_tasks", "main"]
