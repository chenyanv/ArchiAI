from component_agent.schemas import coerce_subagent_payload


def test_coerce_subagent_payload_infers_objectives():
    card = {
        "objective": [
            "Trace ingestion to chunking.",
            "  ",
            42,
        ]
    }
    payload = coerce_subagent_payload(card)
    assert payload is not None
    assert payload["objective"] == ["Trace ingestion to chunking."]


def test_coerce_subagent_payload_preserves_existing_directives():
    card = {
        "objective": ["fallback"],
        "subagent_payload": {"objective": ["primary"], "notes": ["keep me"]},
    }
    payload = coerce_subagent_payload(card)
    assert payload["objective"] == ["primary"]
    assert payload["notes"] == ["keep me"]
