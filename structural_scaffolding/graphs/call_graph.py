from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, MutableMapping, Sequence, Set

import networkx as nx

from structural_scaffolding.models import Profile
from structural_scaffolding.parsing import sanitize_call_name


@dataclass(slots=True)
class CallGraph:
    """Container around a NetworkX directed graph representing intra-repository calls."""

    graph: nx.DiGraph
    """Directed graph whose nodes are profile identifiers and edges represent call sites."""
    unresolved_calls: Set[str] = field(default_factory=set)
    """Names of calls that could not be resolved to a known profile."""

    def to_edge_index(self) -> List[Dict[str, str]]:
        """Return a serialisable list of edges with core attributes."""
        return [
            {
                "source": source,
                "target": target,
                "call": data.get("call", ""),
                "resolved": bool(data.get("resolved", False)),
            }
            for source, target, data in self.graph.edges(data=True)
        ]


def build_call_graph(profiles: Sequence[Profile]) -> CallGraph:
    """Construct a directed call graph based on extracted profiles."""
    graph = nx.DiGraph()
    alias_index = _build_alias_index(profiles)
    unresolved: Set[str] = set()

    for profile in profiles:
        graph.add_node(
            profile.id,
            kind=profile.kind,
            file_path=profile.file_path,
            function_name=profile.function_name,
            class_name=profile.class_name,
            label=_profile_label(profile),
        )

    for profile in profiles:
        for call_expr in profile.calls:
            call = sanitize_call_name(call_expr)
            if not call:
                continue
            resolved = False
            target_candidates = alias_index.get(call, set())

            if target_candidates:
                resolved = True
                for target in target_candidates:
                    graph.add_edge(
                        profile.id,
                        target,
                        call=call,
                        resolved=True,
                    )
            else:
                unresolved.add(call)
                external_node = f"external::{call}"
                if external_node not in graph:
                    graph.add_node(
                        external_node,
                        kind="external_call",
                        label=call,
                    )
                graph.add_edge(
                    profile.id,
                    external_node,
                    call=call,
                    resolved=False,
                )

    return CallGraph(graph=graph, unresolved_calls=unresolved)


def _build_alias_index(profiles: Sequence[Profile]) -> MutableMapping[str, Set[str]]:
    aliases: Dict[str, Set[str]] = {}
    for profile in profiles:
        for alias in _profile_aliases(profile):
            aliases.setdefault(alias, set()).add(profile.id)
    return aliases


def _profile_aliases(profile: Profile) -> Iterable[str]:
    aliases: Set[str] = set()

    def add(value: str | None) -> None:
        if value:
            alias = sanitize_call_name(value)
            if alias:
                aliases.add(alias)

    add(profile.id)
    add(profile.file_path)
    add(profile.function_name)
    add(profile.class_name)
    if profile.function_name and profile.class_name:
        add(f"{profile.class_name}.{profile.function_name}")
        add(f"{profile.class_name}::{profile.function_name}")

    return aliases


def _profile_label(profile: Profile) -> str:
    if profile.function_name and profile.class_name:
        return f"{profile.class_name}.{profile.function_name}"
    if profile.function_name:
        return profile.function_name
    if profile.class_name:
        return profile.class_name
    return profile.file_path


__all__ = ["CallGraph", "build_call_graph"]
