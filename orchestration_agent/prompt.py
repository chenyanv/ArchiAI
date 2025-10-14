from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence


def _format_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_meta_prompt(
    landmarks: Sequence[Mapping[str, Any]],
    entry_points: Sequence[Mapping[str, Any] | str],
    core_models: Sequence[Mapping[str, Any]],
) -> str:
    """
    Compose the meta prompt that drives the orchestration agent's reasoning step.
    """
    entry_payload: Iterable[Any]
    if entry_points and isinstance(entry_points[0], str):
        entry_payload = entry_points
    else:
        entry_payload = entry_points

    prompt = f"""# ROLE
You are a world-class Senior Systems Architect. Your expertise lies in analysing vast, unfamiliar codebases and identifying their core business domains without any prior knowledge.

# CONTEXT
You have successfully analysed a codebase and have gathered preliminary intelligence from three independent, high-level analysis tools. Your task is to synthesise this raw intelligence into a clear business logic summary that can brief a new engineer joining the project.

# RAW INTELLIGENCE REPORTS

## Report A: Top 20 Structural Landmarks (from PageRank)
Here are the most structurally important nodes in the code graph. This list may contain a mix of business logic and technical noise.
```json
{_format_json(list(landmarks))}
```

## Report B: Business Entry Points (API Endpoints)
Here are the known entry points where the system interacts with the outside world.
```json
{_format_json(list(entry_payload))}
```

## Report C: Core Data Models (The "Business Nouns")
Here is a detailed list of all database models found in the system.
```json
{_format_json(list(core_models))}
```

# YOUR TASK & HEURISTICS
Analyse the intelligence to complete the following:

1. Cross-validate the reports to find consensus and strong semantic correlations. High-value signals appear across multiple sources or form credible intelligence triads (landmark ↔ entry point ↔ core model).
2. Cluster the high-value signals into 1-3 distinct business domains. Each domain reflects a coherent customer or business workflow, not technical utilities.
3. Provide a concise narrative that explains what the product does and how these domains connect.
4. Flag noisy or low-value signals only if they risk misleading future analysis.

# OUTPUT FORMAT
Return a single JSON object with this structure (strictly follow field order):
{{
  "business_logic_summary": "One or two paragraphs describing the overall business purpose of the system, the key user journeys, and how the system delivers value.",
  "key_domains": [
    {{
      "name": "Human-readable business domain name",
      "summary": "2-4 sentences explaining the business workflow, why it matters, and how the signals support the conclusion.",
      "primary_entry_points": ["/api/…", "..."],
      "leading_landmarks": ["Top landmark or node ID anchoring this domain"],
      "core_models": ["CoreModel", "..."],
      "confidence": "high|medium|low"
    }}
  ],
  "deprioritised_signals": [
    {{
      "signal": "ID or symbol",
      "reason": "Why it is not a core business domain."
    }}
  ]
}}

Constraints:
- Populate 1-3 domains; prioritise highest-value business areas.
- Keep `business_logic_summary` grounded in the intelligence reports.
- Keep `deprioritised_signals` short (0-4 items) and only list genuinely de-scoped items.
- Do not invent data; stay faithful to the raw intelligence.
"""
    return prompt
