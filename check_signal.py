"""FIRE Signal Bot — QQQ 200-day SMA crossover detector."""

import json
import os

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

DEFAULT_STATE = {
    "signal": None,
    "last_check": None,
    "last_price": None,
    "last_sma": None,
    "diff_pct": None,
    "last_change": None,
}


def load_state(path: str = STATE_FILE) -> dict:
    """Load signal state from JSON file. Returns default state on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def save_state(path: str, state: dict) -> None:
    """Save signal state to JSON file."""
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
