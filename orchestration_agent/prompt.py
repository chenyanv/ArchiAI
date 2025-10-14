from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence


def _format_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def build_meta_prompt(
    landmarks: Sequence[Mapping[str, Any]],
    entry_points: Sequence[Mapping[str, Any] | str],
    core_model_summary: str,
    core_model_total: int,
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
You are a world-class Senior Systems Architect. Your speciality is translating raw static-analysis signals into actionable architecture briefings that can be handed directly to downstream agents—no conversational back-and-forth required.

# CONTEXT
You have successfully analysed a codebase and have gathered preliminary intelligence from three independent, high-level analysis tools. Your mission is to restructure this intelligence into modular “component cards” so that an orchestration backend can route each card to a focused sub-agent. Every card must tell engineers what happens, where to look, and what deeper investigation could produce.

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

## Report C: Core Data Models (Condensed Summary)
Total discovered models: {core_model_total}
Here is a condensed summary of the key data entities and notable relationships.
```json
{core_model_summary}
```

# YOUR TASK & HEURISTICS
1. Cross-validate the reports to find consensus and strong semantic correlations. High-value signals appear across multiple sources or form credible intelligence triads (landmark ↔ entry point ↔ core model).
2. Craft the system overview so that the headline and workflows narrate how the dominant data models collaborate to deliver value. Explicitly call out the interactions between people, APIs, and data entities that make the product work.
3. Identify every distinct business capability supported by strong evidence. Prefer more, smaller component cards over large blended ones; when signals point to separate workflows, split them instead of collapsing them.
4. Order the component cards to follow a logical customer journey or data lifecycle (e.g. ingest → enrich → serve). Use your judgement to align the sequence with how the system likely operates.
5. Make every component card feel “clickable”: surface the key files/functions, explain the business action in plain language, and propose sub-agent objectives that could drive deeper analysis.
6. Only add `recent_activity_hint` or `risk_flags` when the raw signals justify them (e.g. high centrality utilities, deprecated endpoints, duplicated model names). Otherwise omit those optional fields.
7. Keep the JSON concise and factual; when evidence is missing, give empty arrays instead of speculation.

# OUTPUT FORMAT
Return a single JSON object with this structure (strictly follow field order):
{{
  "system_overview": {{
    "headline": "Single sentence describing how the core entities collaborate to deliver value.",
    "key_workflows": ["Workflow / outcome 1", "Workflow / outcome 2"]
  }},
  "component_cards": [
    {{
      "component_id": "kebab-case identifier",
      "module_name": "Short name engineers will recognise",
      "business_signal": "1-2 sentences describing the concrete business action and who benefits.",
      "primary_entry_points": ["/api/..."],
      "leading_landmarks": ["python::path::symbol"],
      "core_models": ["ModelName"],
      "evidence": {{
        "landmarks": ["..."],
        "entry_points": ["..."],
        "models": ["..."]
      }},
      "subagent_payload": {{
        "objective": ["Follow-up question 1", "Follow-up question 2"],
        "starting_points": ["python::path::symbol"],
        "related_entry_points": ["/api/..."],
        "related_models": ["ModelName"]
      }},
      "confidence": "high|medium|low",
      "recent_activity_hint": "Optional: omit when no signal suggests recency.",
      "risk_flags": ["Optional: omit when no risk indicators appear."]
    }}
  ],
  "deprioritised_signals": [
    {{
      "signal": "ID or symbol",
      "reason": "Why it is not a core business component."
    }}
  ]
}}

Constraints:
- Let the number of component cards be dictated purely by evidence. When distinct, high-signal clusters appear, add another focused card instead of merging unrelated workflows—even if that means producing more than six cards.
- Keep lists present but empty when you have no supporting signals; remove optional fields when not applicable.
- Preserve identifiers exactly as they appear in the raw reports.
- Do not invent data; stay faithful to the raw intelligence.
"""
    return prompt
