from __future__ import annotations

import argparse
import logging
import os
from typing import Optional

from structural_scaffolding.database import create_session

from .celery_app import celery_app
from .data_access import fetch_profiles_pending_l1
from .tasks import generate_l1_summary

logger = logging.getLogger(__name__)
_DEFAULT_QUEUE = os.getenv("CELERY_DEFAULT_QUEUE", "l1_summary_queue")


def dispatch_l1_summary_tasks(
    *,
    limit: Optional[int] = None,
    database_url: str | None = None,
    queue: str | None = None,
    dry_run: bool = False,
) -> int:
    session = create_session(database_url)
    try:
        profiles = fetch_profiles_pending_l1(session, limit=limit)
    finally:
        session.close()

    if not profiles:
        logger.info("No profiles need L1 summaries")
        return 0

    target_queue = queue or _DEFAULT_QUEUE

    if dry_run:
        for record in profiles:
            logger.info("Dry run: would enqueue %s", record.id)
        return len(profiles)

    dispatched = 0
    for record in profiles:
        generate_l1_summary.apply_async(
            args=(record.id,),
            kwargs={"database_url": database_url},
            queue=target_queue,
        )
        dispatched += 1
        logger.info("Enqueued L1 summary task", extra={"profile_id": record.id, "queue": target_queue})

    logger.info("Dispatched %s tasks to %s", dispatched, target_queue)
    return dispatched


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
        )

    logger.info("Total tasks considered: %s", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["dispatch_l1_summary_tasks", "main"]
