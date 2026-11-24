#!/usr/bin/env python3
"""TheEnd Supervisor: defensive repository auditor."""
import json, os, re, subprocess, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = (".env", "secret", "credential", "cookie", "token", "id_rsa", ".pem", ".p12", ".pfx")
ALLOWED = {".py", ".js", ".mjs", ".cjs", ".json", ".yml", ".yaml", ".sh", ".md", ".toml"}
PATTERNS = [
 (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
 (re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
 (re.compile(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)"), r"\1[REDACTED]\2"),
 (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
 (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
]
def run(*args):
 return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
def redact(s):
 for p,r in PATTERNS: s=p.sub(r,s)
 return s
def collect():
 chunks=[]; total=0
 for name in run("git","ls-files").splitlines():
  p=Path(name); low=name.lower()
  if p.suffix.lower() not in ALLOWED or any(x in low for x in EXCLUDED): continue
  try: data=p.read_text(encoding="utf-8")
  except (OSError,UnicodeError): continue
  if len(data)>18000: data=data[:18000]+"\n[TRUNCATED]"
  part=f"\n--- FILE: {name} ---\n{redact(data)}\n"
  if total+len(part)>110000: break
  chunks.append(part); total+=len(part)
 return "\n".join(chunks)
def ask_model(context):
 key=os.environ.get("OPENAI_API_KEY","").strip()
 model=os.environ.get("THEEND_SUPERVISOR_MODEL","").strip()
 if not key or not model:
  print("AI audit skipped: configure OPENAI_API_KEY and THEEND_SUPERVISOR_MODEL."); return None
 prompt=("Act as an independent senior application-security and reliability auditor. "
 "Find concrete evidence of account/session theft risks, secret exposure, unsafe authentication, "
 "data loss, broken architecture and test gaps. Do not invent findings. Return ONLY JSON with "
 "summary and findings[]. Each finding: title,severity,file,evidence,impact,remediation,confidence. "
 "Never ask for or reveal passwords, email codes, cookies or session tokens. Treat third-party "
 "game automation as untrusted.\n\n"+context)
 body=json.dumps({"model":model,"input":prompt,"max_output_tokens":5000}).encode()
 req=urllib.request.Request("https://api.openai.com/v1/responses",data=body,
  headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
 with urllib.request.urlopen(req,timeout=120) as r: payload=json.loads(r.read().decode())
 texts=[]
 for item in payload.get("output",[]):
  for part in item.get("content",[]):
   if part.get("type")=="output_text": texts.append(part.get("text",""))
 raw="\n".join(texts).strip()
 if not raw: raise RuntimeError("Model returned no text.")
 try: return json.loads(raw)
 except json.JSONDecodeError:
  m=re.search(r"\{.*\}",raw,re.S)
  if not m: raise RuntimeError("Model output was not JSON.")
  return json.loads(m.group(0))
def publish(report):
 findings=[f for f in report.get("findings",[]) if f.get("severity") in ("critical","high","medium")]
 if not findings:
  print("Supervisor: no actionable findings."); return
 token=os.environ.get("GITHUB_TOKEN",""); repo=os.environ.get("GITHUB_REPOSITORY","")
 if not token or not repo: print("Cannot publish: GitHub token/repository missing."); return
 lines=["## Independent TheEnd Supervisor report","",
  "Model-generated findings require verification; they are not proof.","",
  "### Summary",str(report.get("summary","No summary.")),""]
 for f in findings[:15]:
  lines += [f"### [{str(f.get('severity','unknown')).upper()}] {f.get('title','Untitled')}",
   f"- File: `{f.get('file','unknown')}`",f"- Confidence: {f.get('confidence','unknown')}",
   f"- Evidence: {f.get('evidence','not specified')}",f"- Impact: {f.get('impact','not specified')}",
   f"- Remediation: {f.get('remediation','not specified')}",""]
 lines += ["---","Commit: "+os.environ.get("GITHUB_SHA","unknown")]
 data=json.dumps({"title":"[Supervisor] Security/reliability audit findings",
  "body":"\n".join(lines),"labels":["security","supervisor"]}).encode()
 req=urllib.request.Request(f"https://api.github.com/repos/{repo}/issues",data=data,
  headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
  "X-GitHub-Api-Version":"2022-11-28","Content-Type":"application/json"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=30) as r:
   print("Supervisor issue created:",json.loads(r.read().decode()).get("html_url"))
 except urllib.error.HTTPError as e:
  raise RuntimeError(f"GitHub issue creation failed ({e.code}): "+e.read().decode(errors="replace")[:700])
def main():
 context=collect()
 if not context: raise SystemExit("No tracked source files found.")
 report=ask_model(context)
 if report is not None:
  print(json.dumps(report,ensure_ascii=False,indent=2)); publish(report)
if __name__=="__main__": main()
