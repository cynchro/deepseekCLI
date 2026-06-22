"""Estado global y memoria intra-build durante un `deep build`."""

import threading
from typing import Dict, List, Optional


class BuildState:
    """Rastrea decisiones, patrones y errores dentro de una sola ejecución."""

    def __init__(self):
        self.decisions: List[str] = []
        self.patterns: List[str] = []
        self.constraints: List[str] = []
        self.mistakes: List[Dict] = []
        self._lock = threading.Lock()

    @property
    def state(self) -> Dict:
        return {
            "decisions": self.decisions,
            "patterns": self.patterns,
            "constraints": self.constraints,
        }

    @property
    def memory(self) -> Dict:
        return {"mistakes": self.mistakes}

    def absorb_plan(self, plan: Dict) -> None:
        with self._lock:
            arch = (plan.get("architecture") or "").strip()
            if arch:
                self._add_unique(self.decisions, f"architecture: {arch[:300]}")
            for f in plan.get("files", []):
                desc = (f.get("description") or "").strip()
                if desc and any(kw in desc.lower() for kw in ("hexagonal", "layered", "mvc", "repository")):
                    self._add_unique(self.patterns, desc[:200])

    def absorb_rules(self, rules: List[str]) -> None:
        with self._lock:
            for r in rules:
                self._add_unique(self.constraints, r)

    def absorb_review(self, path: str, review: Dict) -> None:
        with self._lock:
            for issue in review.get("issues", []):
                entry = dict(issue) if isinstance(issue, dict) else {"problem": str(issue)}
                entry["file"] = path
                entry["severity"] = review.get("severity", "low")
                self.mistakes.append(entry)

    def absorb_decision(self, text: str) -> None:
        with self._lock:
            if text:
                self._add_unique(self.decisions, text)

    def format_state_block(self) -> str:
        with self._lock:
            decisions = list(self.decisions)
            patterns = list(self.patterns)
            constraints = list(self.constraints)
        lines = []
        if decisions:
            lines.append("Global decisions:")
            lines.extend(f"  - {d}" for d in decisions[-12:])
        if patterns:
            lines.append("Patterns:")
            lines.extend(f"  - {p}" for p in patterns[-8:])
        if constraints:
            lines.append("Constraints:")
            lines.extend(f"  - {c}" for c in constraints[-10:])
        return "\n".join(lines) if lines else ""

    def format_mistakes_block(self, max_items: int = 15) -> str:
        with self._lock:
            mistakes = list(self.mistakes)
        if not mistakes:
            return ""
        lines = ["Common mistakes to avoid:"]
        for m in mistakes[-max_items:]:
            prob = m.get("problem", m.get("fix", str(m)))
            loc = m.get("file", "?")
            lines.append(f"  - [{loc}] {prob}")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        with self._lock:
            return {
                "state": {
                    "decisions": list(self.decisions),
                    "patterns": list(self.patterns),
                    "constraints": list(self.constraints),
                },
                "memory": {"mistakes": list(self.mistakes)},
            }

    @staticmethod
    def _add_unique(target: List[str], value: str) -> None:
        if value not in target:
            target.append(value)
