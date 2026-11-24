#!/usr/bin/env python3
"""TheEnd Support: local, free project status and next-step console."""
import json
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "supervisor" / "tasks.json"
REPORT_FILE = ROOT / "supervisor" / "latest-audit.json"
REPO = "https://github.com/uroff265-collab/theend"
PR = REPO + "/pull/4"
RUN = REPO + "/actions/runs/45493848401"

def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def task_data():
    return read_json(TASKS_FILE, {"tasks": []})

def evidence_missing(task):
    evidence = task.get("evidence", [])
    return [c for c in task.get("acceptance_criteria", [])
            if not any(e.get("criterion") == c and e.get("proof") for e in evidence)]

def show_status():
    data = task_data()
    report = read_json(REPORT_FILE, {})
    print("\n=== THEEND SUPPORT / СТАТУС ===")
    print("Аудит:", report.get("overall", "ещё не запускался"))
    for t in data.get("tasks", []):
        missing = evidence_missing(t)
        print(f"\n[{t.get('status', 'unknown').upper()}] {t.get('title', t.get('id'))}")
        print("  Подтверждено:", len(t.get("acceptance_criteria", [])) - len(missing),
              "/", len(t.get("acceptance_criteria", [])))
        if missing:
            print("  Осталось:")
            for item in missing:
                print("   -", item)
    print("\nЧестный статус: сапорт помогает контролировать работу; игровой бот и облачная сессия не объявляются готовыми без доказательств.")

def run_audit():
    file = ROOT / "tools" / "theend_supervisor.py"
    print("\nЗапускаю локальную проверку...")
    result = subprocess.run([sys.executable, str(file)], cwd=str(ROOT))
    print("\nПроверка завершена. Код возврата:", result.returncode)

def next_steps():
    data = task_data()
    print("\n=== СЛЕДУЮЩИЕ ДЕЙСТВИЯ ===")
    for t in data.get("tasks", []):
        missing = evidence_missing(t)
        if not missing:
            continue
        print("\n•", t.get("title", t.get("id")))
        print("  Первый незакрытый критерий:", missing[0])
        if t.get("id") == "cloud-session":
            print("  Нужно получить реально открывающуюся браузерную ссылку и приложить скриншот старта.")
        elif t.get("id") == "gameplay-agent":
            print("  Нужно запустить игру, обнаружить ресурс, выполнить сбор и подтвердить результат до/после.")
        else:
            print("  Добавить проверяемое подтверждение в supervisor/tasks.json.")

def open_links():
    print("\nОткрываю страницу текущей работы и проверки в браузере.")
    webbrowser.open(PR)
    webbrowser.open(RUN)

def menu():
    while True:
        print("\n" + "=" * 40)
        print(" THEEND SUPPORT")
        print(" 1 — Статус проекта")
        print(" 2 — Запустить аудит")
        print(" 3 — Что делать дальше")
        print(" 4 — Открыть GitHub (PR и проверка)")
        print("  0 — Выход")
        choice = input("Выбор: ").strip()
        if choice == "1": show_status()
        elif choice == "2": run_audit()
        elif choice == "3": next_steps()
        elif choice == "4": open_links()
        elif choice == "0": break
        else: print("Введите 1, 2, 3, 4 или 0.")

if __name__ == "__main__":
    menu()
