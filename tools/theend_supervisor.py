#!/usr/bin/env python3
"""Evidence-based supervisor for TheEnd project tasks.

This tool does not monitor ChatGPT's internal reasoning. It audits project work
against explicit acceptance criteria and refuses to mark tasks complete without
evidence recorded in supervisor/tasks.json.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "supervisor" / "tasks.json"
REPORT = ROOT / "supervisor" / "latest-audit.json"


def audit():
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    results = []
    for task in data.get("tasks", []):
        criteria = task.get("acceptance_criteria", [])
        evidence = task.get("evidence", [])
        missing = [c for c in criteria if not any(
            e.get("criterion") == c and e.get("proof") for e in evidence
        )]
        declared_done = task.get("status") == "done"
        results.append({
            "id": task.get("id", "unknown"),
            "title": task.get("title", ""),
            "declared_status": task.get("status", "blocked"),
            "verdict": "PASS" if criteria and not missing else "INCOMPLETE",
            "missing_evidence": missing,
            "done_claim_without_proof": declared_done and bool(missing),
        })
    report = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "overall": "PASS" if results and all(r["verdict"] == "PASS" for r in results) else "INCOMPLETE",
        "tasks": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(audit())
