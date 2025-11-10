from component_agent.graph import _parse_agent_payload


def test_parse_agent_payload_accepts_json_object():
    raw = """
    {
        "component_id": "demo",
        "notes": [],
        "next_layer": {"nodes": [{"node_key": "n1"}]}
    }
    """
    parsed = _parse_agent_payload(raw)
    assert parsed["component_id"] == "demo"


def test_parse_agent_payload_fallbacks_to_python_dict_literal():
    raw = """
    Here you go:
    {'component_id': 'demo', 'next_layer': {'nodes': [{'node_key': 'n2'}]}}
    """
    parsed = _parse_agent_payload(raw)
    assert parsed["next_layer"]["nodes"][0]["node_key"] == "n2"


def test_parse_agent_payload_raises_when_no_mapping_found():
    raw = "Thought: still working"
    try:
        _parse_agent_payload(raw)
    except ValueError as exc:
        assert "Agent response" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing JSON payload.")
