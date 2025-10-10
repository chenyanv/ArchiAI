"""Top-down workflow tracing entry points."""

from .graph import build_top_down_graph
from .state import TopDownAgentConfig, TopDownAgentState


def parse_args(argv=None):
    from .cli import parse_args as _parse_args

    return _parse_args(argv)


def run(argv=None):
    from .cli import run as _run

    return _run(argv)


def main():
    from .cli import main as _main

    return _main()


__all__ = [
    "build_top_down_graph",
    "main",
    "parse_args",
    "run",
    "TopDownAgentConfig",
    "TopDownAgentState",
]
