from __future__ import annotations

import json

from .graph import run_orchestration_agent


def main() -> None:
    plan = run_orchestration_agent()
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
