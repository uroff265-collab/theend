#!/usr/bin/env python3
"""Free, offline TheEnd Supervisor checks. No network calls or API key required."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {".py", ".js", ".mjs", ".cjs", ".json", ".yml", ".yaml", ".sh", ".toml"}
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
RULES = [
    ("HIGH", "Possible hard-coded credential",
     re.compile(r"""(?i)\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|password|passwd)\b\s*[:=]\s*['"][^'"]{8,}['"]"""),
     "Move the value to a managed secret/environment variable; rotate it if it was real."),
    ("HIGH", "Private key material",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
     "Remove the key from the repository and rotate/revoke it."),
    ("HIGH", "Embedded provider token",
     re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
     "Revoke and rotate the credential; load it from a secret store."),
    ("MEDIUM", "TLS certificate verification disabled",
     re.compile(r"(?i)\bverify\s*=\s*False\b"),
     "Keep TLS certificate verification enabled unless a narrowly scoped test requires otherwise."),
    ("MEDIUM", "Dynamic code execution",
     re.compile(r"\b(?:eval|exec)\s*\("),
     "Avoid evaluating untrusted strings; use a constrained parser or explicit dispatch."),
    ("MEDIUM", "Unsafe subprocess shell execution",
     re.compile(r"\bsubprocess\.(?:run|Popen|call|check_call|check_output)\s*\([^)]*shell\s*=\s*True", re.S),
     "Prefer argument arrays with shell=False and validate external inputs."),
    ("MEDIUM", "Unsafe pickle deserialization",
     re.compile(r"\bpickle\.(?:load|loads)\s*\("),
     "Never deserialize pickle data from untrusted sources; use a safe data format."),
]

def tracked_files():
    try:
        names = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        names = []
        for path in ROOT.rglob("*"):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.is_file():
                names.append(path.relative_to(ROOT).as_posix())
    for name in names:
        path = Path(name)
        if path.suffix.lower() in ALLOWED and not any(part in SKIP_PARTS for part in path.parts):
            if any(part in name.lower() for part in (".env", "secret", "credential", "cookie", "token", "id_rsa")):
                continue
            yield path

def main():
    findings = []
    scanned = 0
    for rel in tracked_files():
        try:
            content = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        scanned += 1
        for number, line in enumerate(content.splitlines(), 1):
            if len(line) > 4000:
                continue
            for severity, title, pattern, fix in RULES:
                if pattern.search(line):
                    # Never print the matching source line: it may contain a real secret.
                    findings.append((severity, str(rel), number, title, fix))
    findings.sort(key=lambda item: ({"HIGH": 0, "MEDIUM": 1}.get(item[0], 2), item[1], item[2]))
    lines = [
        "## TheEnd Supervisor — free static audit",
        "",
        f"Scanned **{scanned}** tracked source/configuration files.",
        "This check runs in GitHub Actions and makes **no external API calls**.",
        "",
    ]
    if findings:
        lines.append(f"Found **{len(findings)}** possible issue(s). Review manually; pattern matches can be false positives.")
        for severity, filename, line, title, fix in findings[:100]:
            lines.extend([f"- **{severity} — {title}**: {filename}:{line}", f"  - Suggested action: {fix}"])
    else:
        lines.append("No matches were found by the configured static rules. This does not prove the application is secure.")
    report = "\n".join(lines) + "\n"
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(report)
    print(f"Static audit complete: {len(findings)} possible finding(s).")

if __name__ == "__main__":
    main()
