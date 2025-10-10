from __future__ import annotations

import ast
import json
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from structural_scaffolding.database import ProfileRecord

from .models import ConfidenceLevel, EntryPointCandidate, EntryPointCategory


@dataclass(slots=True)
class _ProfileSignals:
    record: ProfileRecord
    decorators: List[str]
    name: str
    name_lower: str
    base_name: str
    file_path: str
    path_segments: List[str]
    docstring: Optional[str]


@dataclass(slots=True)
class EntryScanDiagnostics:
    root_path: Optional[str]
    include_tests: bool
    profile_count: int
    signals_count: int
    detected_profiles: int
    candidate_count: int
    skipped_test_path: int
    skipped_test_name: int
    skipped_missing_name: int
    sample_paths: List[str]


class EntryPointScanner:
    """Identify potential workflow entry points using stored AST profiles."""

    _TARGET_KINDS: Sequence[str] = ("function", "method", "class")
    _WEB_PATH_SEGMENTS: Sequence[str] = (
        "api",
        "apis",
        "routes",
        "controllers",
        "views",
        "endpoints",
        "http",
    )
    _WEB_NAME_KEYWORDS: Sequence[str] = (
        "route",
        "endpoint",
        "handler",
        "view",
        "api",
        "controller",
        "webhook",
    )
    _ASYNC_PATH_SEGMENTS: Sequence[str] = (
        "consumer",
        "consumers",
        "listener",
        "listeners",
        "queue",
        "queues",
        "worker",
        "workers",
        "tasks",
        "events",
        "event",
        "subscribers",
        "subscriber",
    )
    _ASYNC_NAME_KEYWORDS: Sequence[str] = (
        "listener",
        "consumer",
        "handler",
        "subscriber",
        "receiver",
        "worker",
        "processor",
        "callback",
        "event",
        "message",
    )
    _SCHEDULED_PATH_SEGMENTS: Sequence[str] = (
        "scheduler",
        "schedulers",
        "cron",
        "jobs",
        "job",
        "schedule",
        "schedules",
        "tasks",
        "maintenance",
    )
    _SCHEDULED_NAME_KEYWORDS: Sequence[str] = (
        "cron",
        "schedule",
        "scheduled",
        "job",
        "refresh",
        "sync",
        "cleanup",
        "task",
        "heartbeat",
        "poll",
        "update",
    )

    def __init__(
        self,
        session: Session,
        *,
        root_path: Optional[str] = None,
        include_tests: bool = False,
    ) -> None:
        self._session = session
        self._root_path = root_path
        self._include_tests = include_tests
        self._stats: Counter[str] = Counter()
        self._diagnostics: EntryScanDiagnostics | None = None

    def scan(self) -> List[EntryPointCandidate]:
        self._stats.clear()
        candidates: List[EntryPointCandidate] = []
        profile_count = 0
        signals_count = 0
        detected_profiles = 0
        sample_paths: List[str] = []

        query = self._session.query(ProfileRecord).filter(ProfileRecord.kind.in_(self._TARGET_KINDS))
        if self._root_path:
            query = query.filter(ProfileRecord.root_path == self._root_path)

        for record in query.yield_per(500):
            profile_count += 1
            signals = self._extract_signals(record)
            if signals is None:
                continue
            signals_count += 1
            if len(sample_paths) < 5:
                sample_paths.append(signals.file_path)
            detected = self._detect_categories(signals)
            if detected:
                detected_profiles += 1
            candidates.extend(detected)

        # Stable ordering by category, confidence, file path, line number.
        candidates.sort(
            key=lambda item: (
                item.category.value,
                _confidence_rank(item.confidence),
                item.file_path,
                item.start_line,
            )
        )

        self._diagnostics = EntryScanDiagnostics(
            root_path=self._root_path,
            include_tests=self._include_tests,
            profile_count=profile_count,
            signals_count=signals_count,
            detected_profiles=detected_profiles,
            candidate_count=len(candidates),
            skipped_test_path=self._stats.get("skipped_test_path", 0),
            skipped_test_name=self._stats.get("skipped_test_name", 0),
            skipped_missing_name=self._stats.get("skipped_missing_name", 0),
            sample_paths=sample_paths,
        )

        return candidates

    def export(self, candidates: Iterable[EntryPointCandidate], output_path: Path) -> None:
        candidate_list = list(candidates)
        payload = {
            "entry_points": [candidate.to_dict() for candidate in candidate_list],
            "total": len(candidate_list),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2))

    def scan_and_export(self, output_path: Path) -> List[EntryPointCandidate]:
        candidates = self.scan()
        self.export(candidates, output_path)
        return candidates

    def _extract_signals(self, record: ProfileRecord) -> _ProfileSignals | None:
        if record.kind not in self._TARGET_KINDS:
            return None

        file_path = (record.file_path or "").replace("\\", "/")
        if not self._include_tests and _is_test_path(file_path):
            self._stats["skipped_test_path"] += 1
            return None

        name = _derive_name(record)
        if not name:
            self._stats["skipped_missing_name"] += 1
            return None

        base_name = name.split(".")[-1].lower()
        if base_name.startswith("test") and not self._include_tests:
            self._stats["skipped_test_name"] += 1
            return None

        decorators = _extract_decorators(record.source_code or "")
        docstring = record.docstring.strip() if isinstance(record.docstring, str) else None

        return _ProfileSignals(
            record=record,
            decorators=decorators,
            name=name,
            name_lower=name.lower(),
            base_name=base_name,
            file_path=file_path,
            path_segments=[segment for segment in file_path.lower().split("/") if segment],
            docstring=docstring,
        )

    def _detect_categories(self, signals: _ProfileSignals) -> List[EntryPointCandidate]:
        detections: List[EntryPointCandidate] = []

        web_candidate = self._score_web_api(signals)
        if web_candidate is not None:
            detections.append(web_candidate)

        async_candidate = self._score_async_listener(signals)
        if async_candidate is not None:
            detections.append(async_candidate)

        scheduled_candidate = self._score_scheduled_job(signals)
        if scheduled_candidate is not None:
            detections.append(scheduled_candidate)

        return detections

    def _score_web_api(self, signals: _ProfileSignals) -> EntryPointCandidate | None:
        decorator_hits, decorator_reasons = _match_web_api_decorators(signals.decorators)
        path_hits = [segment for segment in signals.path_segments if segment in self._WEB_PATH_SEGMENTS]
        name_hits = [keyword for keyword in self._WEB_NAME_KEYWORDS if keyword in signals.name_lower]

        score = (2 if decorator_hits else 0) + (1 if path_hits else 0) + (1 if name_hits else 0)
        if score == 0:
            return None

        if signals.base_name.startswith("_") and not decorator_hits:
            return None

        reasons = [*decorator_reasons]
        reasons.extend(f"path:{segment}" for segment in path_hits[:2])
        reasons.extend(f"name:{keyword}" for keyword in name_hits[:2])

        detector = _choose_detector(
            category=EntryPointCategory.WEB_API,
            decorator_hits=bool(decorator_hits),
            name_hits=bool(name_hits),
            path_hits=bool(path_hits),
        )

        confidence = _score_to_confidence(score)
        return EntryPointCandidate(
            profile_id=signals.record.id,
            kind=signals.record.kind,
            name=signals.name,
            file_path=signals.file_path,
            start_line=signals.record.start_line,
            category=EntryPointCategory.WEB_API,
            detector=detector,
            confidence=confidence,
            reasons=reasons,
            decorators=signals.decorators,
            docstring=signals.docstring,
        )

    def _score_async_listener(self, signals: _ProfileSignals) -> EntryPointCandidate | None:
        decorator_hits, decorator_reasons = _match_async_decorators(signals.decorators)
        path_hits = [segment for segment in signals.path_segments if segment in self._ASYNC_PATH_SEGMENTS]
        name_hits = [keyword for keyword in self._ASYNC_NAME_KEYWORDS if keyword in signals.name_lower]

        score = (2 if decorator_hits else 0) + (1 if path_hits else 0) + (1 if name_hits else 0)
        if score == 0:
            return None

        if signals.base_name.startswith("_") and not decorator_hits:
            return None

        reasons = [*decorator_reasons]
        reasons.extend(f"path:{segment}" for segment in path_hits[:2])
        reasons.extend(f"name:{keyword}" for keyword in name_hits[:2])

        detector = _choose_detector(
            category=EntryPointCategory.ASYNC_LISTENER,
            decorator_hits=bool(decorator_hits),
            name_hits=bool(name_hits),
            path_hits=bool(path_hits),
        )

        confidence = _score_to_confidence(score)
        return EntryPointCandidate(
            profile_id=signals.record.id,
            kind=signals.record.kind,
            name=signals.name,
            file_path=signals.file_path,
            start_line=signals.record.start_line,
            category=EntryPointCategory.ASYNC_LISTENER,
            detector=detector,
            confidence=confidence,
            reasons=reasons,
            decorators=signals.decorators,
            docstring=signals.docstring,
        )

    def _score_scheduled_job(self, signals: _ProfileSignals) -> EntryPointCandidate | None:
        decorator_hits, decorator_reasons = _match_scheduled_decorators(signals.decorators, signals.record.source_code or "")
        path_hits = [segment for segment in signals.path_segments if segment in self._SCHEDULED_PATH_SEGMENTS]
        name_hits = [keyword for keyword in self._SCHEDULED_NAME_KEYWORDS if keyword in signals.name_lower]

        docstring_hits = []
        if signals.docstring:
            doc_lower = signals.docstring.lower()
            docstring_hits = [keyword for keyword in ("cron", "schedule", "daily", "nightly", "periodic") if keyword in doc_lower]

        score = (
            (2 if decorator_hits else 0)
            + (1 if path_hits else 0)
            + (1 if name_hits else 0)
            + (1 if docstring_hits else 0)
        )
        if score == 0:
            return None

        reasons = [*decorator_reasons]
        reasons.extend(f"path:{segment}" for segment in path_hits[:2])
        reasons.extend(f"name:{keyword}" for keyword in name_hits[:2])
        reasons.extend(f"doc:{keyword}" for keyword in docstring_hits[:2])

        detector = _choose_detector(
            category=EntryPointCategory.SCHEDULED_JOB,
            decorator_hits=bool(decorator_hits),
            name_hits=bool(name_hits),
            path_hits=bool(path_hits or docstring_hits),
        )

        confidence = _score_to_confidence(score)
        return EntryPointCandidate(
            profile_id=signals.record.id,
            kind=signals.record.kind,
            name=signals.name,
            file_path=signals.file_path,
            start_line=signals.record.start_line,
            category=EntryPointCategory.SCHEDULED_JOB,
            detector=detector,
            confidence=confidence,
            reasons=reasons,
            decorators=signals.decorators,
            docstring=signals.docstring,
        )

    @property
    def diagnostics(self) -> EntryScanDiagnostics | None:
        return self._diagnostics


def _extract_decorators(source_code: str) -> List[str]:
    if not source_code:
        return []

    try:
        module = ast.parse(textwrap.dedent(source_code))
    except SyntaxError:
        return []

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators = [_normalise_decorator(decorator) for decorator in node.decorator_list]
            return [decorator for decorator in decorators if decorator]
    return []


def _normalise_decorator(node: ast.AST) -> str | None:
    target = node
    if isinstance(node, ast.Call):
        target = node.func

    if isinstance(target, ast.Name):
        return target.id

    if isinstance(target, ast.Attribute):
        parts: List[str] = []
        current: Optional[ast.AST] = target
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        elif isinstance(current, ast.Call):
            inner = _normalise_decorator(current)
            if inner:
                parts.append(inner)
        else:
            return None
        return ".".join(reversed(parts))

    if isinstance(target, ast.Subscript):
        return _normalise_decorator(target.value)

    try:
        # ast.unparse is available on Python 3.9+
        return ast.unparse(target)
    except Exception:  # pragma: no cover - unparse fallback
        return None


def _derive_name(record: ProfileRecord) -> str:
    if record.kind == "class":
        if record.class_name:
            return record.class_name
        if record.function_name:
            return record.function_name
    elif record.kind in {"function", "method"}:
        if record.function_name:
            if record.class_name:
                return f"{record.class_name}.{record.function_name}"
            return record.function_name
        if record.class_name:
            return record.class_name
    return record.id


def _match_web_api_decorators(decorators: Sequence[str]) -> tuple[List[str], List[str]]:
    if not decorators:
        return [], []

    hits: List[str] = []
    reasons: List[str] = []
    for decorator in decorators:
        lower = decorator.lower()
        if lower.endswith(".route") or lower in {"route", "router", "router.route"}:
            hits.append(decorator)
        elif any(lower.endswith(suffix) for suffix in (".get", ".post", ".put", ".delete", ".patch", ".options", ".head")):
            hits.append(decorator)
        elif lower in {"api_view", "view_config", "blueprint.route"}:
            hits.append(decorator)

    if hits:
        reasons.extend(f"decorator:{value}" for value in hits[:3])
    return hits, reasons


def _match_async_decorators(decorators: Sequence[str]) -> tuple[List[str], List[str]]:
    if not decorators:
        return [], []

    async_keywords = (
        "task",
        "shared_task",
        "celery.task",
        "celery_app.task",
        "app.task",
        "receiver",
        "consumer",
        "listener",
        "subscriber",
        "on_event",
        "on_message",
        "signal",
        "websocket",
    )

    hits: List[str] = []
    reasons: List[str] = []
    for decorator in decorators:
        lower = decorator.lower()
        if any(lower.endswith(keyword) or lower == keyword for keyword in async_keywords):
            hits.append(decorator)

    if hits:
        reasons.extend(f"decorator:{value}" for value in hits[:3])
    return hits, reasons


def _match_scheduled_decorators(decorators: Sequence[str], source_code: str) -> tuple[List[str], List[str]]:
    if not decorators and not source_code:
        return [], []

    scheduled_keywords = (
        "schedule",
        "scheduled",
        "scheduler",
        "cron",
        "cron_job",
        "cronjob",
        "interval",
        "repeat_every",
        "repeat",
        "timer",
        "periodic_task",
        "periodic",
        "job",
        "daily",
        "hourly",
    )

    hits: List[str] = []
    reasons: List[str] = []
    for decorator in decorators:
        lower = decorator.lower()
        if any(lower.endswith(keyword) or lower == keyword for keyword in scheduled_keywords):
            hits.append(decorator)

    if not hits and source_code:
        lowered = source_code.lower()
        if any(keyword in lowered for keyword in ("@schedule", "@scheduler.", "@periodic_task", "@cron")):
            snippet = "schedule"
            hits.append(snippet)

    if hits:
        reasons.extend(f"decorator:{value}" for value in hits[:3])
    return hits, reasons


def _choose_detector(
    *,
    category: EntryPointCategory,
    decorator_hits: bool,
    name_hits: bool,
    path_hits: bool,
) -> str:
    if decorator_hits:
        return f"{category.value}_decorator"
    if name_hits:
        return f"{category.value}_name"
    if path_hits:
        return f"{category.value}_path"
    return f"{category.value}_heuristic"


def _score_to_confidence(score: int) -> ConfidenceLevel:
    if score >= 3:
        return ConfidenceLevel.HIGH
    if score == 2:
        return ConfidenceLevel.MEDIUM
    if score == 1:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNKNOWN


def _confidence_rank(confidence: ConfidenceLevel) -> int:
    order = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
        ConfidenceLevel.UNKNOWN: 3,
    }
    return order.get(confidence, 4)


def _is_test_path(file_path: str) -> bool:
    lowered = file_path.lower()
    return any(segment in lowered for segment in ("test/", "/test_", "_test.py", "tests/"))


__all__ = ["EntryPointScanner"]
