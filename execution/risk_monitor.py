"""
Drawdown kill-switch (PLAN.md §6).

Tracks the account's high-water-mark equity in a small persisted state file and
trips when the peak-to-current drawdown breaches `max_drawdown_killswitch`. On a
breach the orchestrator flattens the book to cash. State survives restarts so a
single crash run can't reset the high-water mark and hide a real drawdown.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

STATE_PATH = Path(__file__).resolve().parent.parent / "logs" / "state.json"


@dataclass(frozen=True)
class DrawdownStatus:
    equity: float
    high_water_mark: float
    drawdown: float          # negative fraction, e.g. -0.18
    breached: bool


class RiskMonitor:
    def __init__(self, max_drawdown: float, state_path: Optional[Path] = None):
        self.max_drawdown = abs(max_drawdown)
        self.state_path = Path(state_path) if state_path else STATE_PATH

    def _load_hwm(self) -> Optional[float]:
        if self.state_path.exists():
            try:
                return float(json.loads(self.state_path.read_text())["high_water_mark"])
            except (KeyError, ValueError, json.JSONDecodeError):
                return None
        return None

    def _save_hwm(self, hwm: float) -> None:
        self.state_path.parent.mkdir(exist_ok=True)
        self.state_path.write_text(json.dumps({"high_water_mark": round(hwm, 2)}))

    def update(self, equity: float) -> DrawdownStatus:
        """
        Fold today's equity into the high-water mark and report drawdown status.

        Raises the HWM when equity makes a new peak; otherwise measures the
        drawdown from that peak and flags a breach if it exceeds the limit.
        """
        hwm = self._load_hwm()
        if hwm is None or equity > hwm:
            hwm = equity
        self._save_hwm(hwm)

        drawdown = equity / hwm - 1.0 if hwm > 0 else 0.0
        return DrawdownStatus(
            equity=equity,
            high_water_mark=hwm,
            drawdown=drawdown,
            breached=drawdown <= -self.max_drawdown,
        )
