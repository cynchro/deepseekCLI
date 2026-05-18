import json
import subprocess
from pathlib import Path
from typing import Dict

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_REF_FILE = Path.home() / ".config" / "deep" / "balance_ref.json"


def fetch(api_key: str) -> Dict:
    try:
        if _HAS_REQUESTS:
            r = _requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
            r.raise_for_status()
            return r.json()
        result = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/user/balance",
             "-H", f"Authorization: Bearer {api_key}"],
            capture_output=True, text=True,
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}


def get_ref() -> Dict:
    if _REF_FILE.exists():
        try:
            return json.loads(_REF_FILE.read_text())
        except Exception:
            pass
    return {}


def save_ref(ref: Dict):
    _REF_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REF_FILE.write_text(json.dumps(ref, indent=2))
