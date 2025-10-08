from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from structural_scaffolding.database import create_session, WorkflowEntryPointRecord
from structural_scaffolding.pipeline.workflow_tasks import (
    PROMPT_TEMPLATE,
    _build_llm_context,
    _extract_json_block,
    _normalise_workflow_json,
    _validate_workflow_json,
    synthesize_workflow,
)
from structural_scaffolding.utils import db as db_utils
from structural_scaffolding.utils.tracer import trace_workflow
from structural_scaffolding.pipeline.llm import request_workflow_completion


def _resolve_entry_points(
    session,
    *,
    profile_id: str | None,
    limit: int | None,
) -> Iterable[WorkflowEntryPointRecord]:
    query = session.query(WorkflowEntryPointRecord).order_by(WorkflowEntryPointRecord.id)
    if profile_id:
        query = query.filter(WorkflowEntryPointRecord.profile_id == profile_id)
    if limit:
        query = query.limit(limit)
    return query.all()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate workflows for detected entry points and persist them to the database.",
    )
    parser.add_argument(
        "--profile-id",
        help="Only process the specified workflow entry profile ID.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit the number of entry points processed.",
    )
    parser.add_argument(
        "--database-url",
        help="Override STRUCTURAL_SCAFFOLD_DB_URL when connecting to Postgres.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the synthesized workflow JSON for successful entries.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="On failure, print detailed debugging information for the entry.",
    )

    args = parser.parse_args(argv)

    session = create_session(args.database_url)
    try:
        entry_points = _resolve_entry_points(
            session,
            profile_id=args.profile_id,
            limit=args.limit,
        )

        if not entry_points:
            print("No workflow entry points matched the provided filters.")
            return 0

        for entry in entry_points:
            print(f"Generating workflow for {entry.profile_id} …", flush=True)
            workflow = synthesize_workflow(entry.profile_id, database_url=args.database_url)

            if workflow is None:
                if args.debug:
                    _debug_entry(session, entry, database_url=args.database_url)
                print("  -> skipped", flush=True)
                continue

            print("  -> stored", flush=True)
            if args.print_json:
                print(json.dumps(workflow, indent=2, ensure_ascii=False))

        return 0
    finally:
        session.close()


def _debug_entry(session, entry: WorkflowEntryPointRecord, *, database_url: str | None) -> None:
    print("  [debug] running deep diagnostics…", flush=True)

    call_chain = trace_workflow(entry.profile_id, session=session)
    print("  [debug] call chain:", call_chain, flush=True)

    context = _build_llm_context(entry.profile_id, call_chain, session=session)
    prompt = PROMPT_TEMPLATE.format(context=context)
    print("  [debug] prompt preview:", prompt[:500].replace("\n", "\\n"), flush=True)

    try:
        response_text = request_workflow_completion(prompt, expect_json=True)
    except Exception as exc:
        print(f"  [debug] LLM request failed: {exc!r}", flush=True)
        return

    print("  [debug] raw LLM response:", response_text.strip(), flush=True)

    try:
        parsed_payload = json.loads(_extract_json_block(response_text))
    except json.JSONDecodeError as exc:
        print(f"  [debug] JSON decode error: {exc}", flush=True)
        return

    workflow = _normalise_workflow_json(parsed_payload)
    print("  [debug] normalised payload:", json.dumps(workflow, indent=2, ensure_ascii=False), flush=True)
    print("  [debug] validation:", _validate_workflow_json(workflow), flush=True)

    try:
        db_utils.save_workflow(entry.profile_id, workflow, session=session, database_url=database_url)
        print("  [debug] save_workflow succeeded.", flush=True)
    except Exception as exc:
        print(f"  [debug] save_workflow failed: {exc!r}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
