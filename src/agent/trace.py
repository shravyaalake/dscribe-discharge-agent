import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class TraceLogger:
    """
    Writes readable JSONL traces for every agent/tool step.

    Each line is one event:
    reasoning -> action/tool -> inputs -> result -> next decision
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trace_file = self.output_dir / "trace.jsonl"

        # Reset trace on each run
        self.trace_file.write_text("", encoding="utf-8")

    def log(
        self,
        step: int,
        reasoning: str,
        action: str,
        inputs: Dict[str, Any],
        result: Dict[str, Any],
        next_decision: str,
    ) -> None:
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "step": step,
            "reasoning": reasoning,
            "action": action,
            "inputs": inputs,
            "result": result,
            "next_decision": next_decision,
        }

        with self.trace_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")