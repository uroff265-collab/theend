#!/usr/bin/env python3
"""Evidence-based supervisor for TheEnd project tasks.

Audits work against acceptance criteria and evidence in supervisor/tasks.json.
It cannot inspect ChatGPT's private reasoning; it checks committed project facts.
"""
import json
import os
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
        claimed_done = task.get("status") == "done"
        results.append({
            "id": task.get("id", "unknown"),
            "title": task.get("title", ""),
            "declared_status": task.get("status", "blocked"),
            "verdict": "PASS" if criteria and not missing else "INCOMPLETE",
            "missing_evidence": missing,
            "done_claim_without_proof": claimed_done and bool(missing),
        })
    overall = "PASS" if results and all(r["verdict"] == "PASS" for r in results) else "INCOMPLETE"
    report = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "tasks": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"## TheEnd supervisor: {overall}\\n\\n")
            for item in results:
                summary.write(f"- **{item['id']} — {item['title']}**: {item['verdict']}\\n")
                if item["missing_evidence"]:
                    summary.write("  - Missing proof: " + "; ".join(item["missing_evidence"]) + "\\n")
    # Incomplete work is reported but does not fail the build. A false "done"
    # claim does fail, so the supervisor catches unsupported completion claims.
    return 1 if any(r["done_claim_without_proof"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(audit())
