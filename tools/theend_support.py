#!/usr/bin/env python3
"""TheEnd Support: local project supervisor and launcher."""
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "supervisor" / "tasks.json"
REPORT_FILE = ROOT / "supervisor" / "latest-audit.json"
REPO = "https://github.com/uroff265-collab/theend"
PR = REPO + "/pull/4"
ACTIONS = REPO + "/actions"
BOT_LAUNCHER = ROOT / "START_THEEND.bat"


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
    print("Локальный аудит:", report.get("overall", "ещё не запускался"))
    print("Лаунчер бота:", "найден" if BOT_LAUNCHER.is_file() else "НЕ НАЙДЕН")
    for t in data.get("tasks", []):
        missing = evidence_missing(t)
        print(f"\n[{t.get('status', 'unknown').upper()}] {t.get('title', t.get('id'))}")
        print("  Подтверждено:", len(t.get("acceptance_criteria", [])) - len(missing),
              "/", len(t.get("acceptance_criteria", [])))
        if missing:
            print("  Осталось:")
            for item in missing:
                print("   -", item)
    print("\nВажно: Support проверяет файлы и доказательства. Он не управляет ChatGPT.")
    print("Игровой сбор считается готовым только после подтверждённого действия в игре.")


def run_audit():
    file = ROOT / "tools" / "theend_supervisor.py"
    if not file.is_file():
        print("Не найден tools/theend_supervisor.py")
        return
    print("\nЗапускаю локальную проверку...")
    result = subprocess.run([sys.executable, str(file)], cwd=str(ROOT))
    print("\nПроверка завершена. Код возврата:", result.returncode)


def next_steps():
    data = task_data()
    print("\n=== СЛЕДУЮЩИЕ ДЕЙСТВИЯ ===")
    found = False
    for t in data.get("tasks", []):
        missing = evidence_missing(t)
        if not missing:
            continue
        found = True
        print("\n•", t.get("title", t.get("id")))
        print("  Первый незакрытый критерий:", missing[0])
        if t.get("id") == "cloud-session":
            print("  Требуется открывающаяся браузерная сессия и снимок старта.")
        elif t.get("id") == "gameplay-agent":
            print("  Требуется доказать обнаружение ресурса и сбор в игре (до/после).")
        else:
            print("  Требуется проверяемое подтверждение в supervisor/tasks.json.")
    if not found:
        print("По tasks.json незакрытых критериев нет.")


def start_bot():
    if not BOT_LAUNCHER.is_file():
        print("Не найден START_THEEND.bat. Распакуй полный архив проекта.")
        return
    if os.name != "nt":
        print("Этот лаунчер предназначен для Windows + LDPlayer.")
        return
    print("Запускаю TheEnd Agent в отдельном окне. Остановить его можно Ctrl+C.")
    subprocess.Popen(["cmd.exe", "/c", str(BOT_LAUNCHER)], cwd=str(ROOT),
                     creationflags=subprocess.CREATE_NEW_CONSOLE)


def open_links():
    webbrowser.open(PR)
    webbrowser.open(ACTIONS)
    print("Открыты PR #4 и страница всех актуальных запусков GitHub Actions.")


def menu():
    while True:
        print("\n" + "=" * 42)
        print(" THEEND SUPPORT")
        print(" 1 — Статус проекта")
        print(" 2 — Запустить аудит")
        print(" 3 — Что осталось сделать")
        print(" 4 — Открыть GitHub проверки")
        print(" 5 — Запустить TheEnd Agent (LDPlayer)")
        print("  0 — Выход")
        choice = input("Выбор: ").strip()
        if choice == "1":
            show_status()
        elif choice == "2":
            run_audit()
        elif choice == "3":
            next_steps()
        elif choice == "4":
            open_links()
        elif choice == "5":
            start_bot()
        elif choice == "0":
            break
        else:
            print("Введите 1, 2, 3, 4, 5 или 0.")


if __name__ == "__main__":
    menu()
