from pathlib import Path
from typing import List


def load_rules(*paths: Path) -> List[str]:
    rules, seen = [], set()
    for path in paths:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and line not in seen:
                    rules.append(line)
                    seen.add(line)
    return rules
