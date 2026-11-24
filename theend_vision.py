"""TheEnd vision and guarded-action layer.

This module deliberately separates observing the game from acting on it.
It never guesses screen coordinates from resource counters or circle shapes.
Actions are allowed only for a unique Android accessibility node whose exact
label and screen context are configured for the requested task.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Iterable, Optional


def normalize(value: str) -> str:
    value = (value or "").casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9 ]+", " ", value).strip()


@dataclass(frozen=True)
class UINode:
    label: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    enabled: bool

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)


@dataclass(frozen=True)
class ActionSpec:
    key: str
    contexts: tuple[str, ...]
    labels: tuple[str, ...]


# Exact UI text only. No inferred coordinates, generic "OK", or translated
# guesses: add a label only after it has been observed in the actual game.
SPECS = {
    "alliance_help": ActionSpec(
        "alliance_help",
        ("помощь альянсу", "alliance help"),
        ("помочь всем", "help all"),
    ),
    "exploration_camp": ActionSpec(
        "exploration_camp",
        ("лагерь разведки", "exploration camp"),
        ("забрать", "claim"),
    ),
    "sanctuary": ActionSpec(
        "sanctuary",
        ("святилище", "sanctuary"),
        ("собрать", "collect", "claim"),
    ),
    "golden_eggs": ActionSpec(
        "golden_eggs",
        ("золотые яйца", "golden eggs"),
        ("забрать", "claim", "collect"),
    ),
}


def parse_hierarchy(xml_text: str) -> list[UINode]:
    """Parse Android uiautomator XML into visible, actionable nodes."""
    root = ET.fromstring(xml_text)
    result: list[UINode] = []
    for raw in root.iter("node"):
        text = raw.attrib.get("text", "")
        desc = raw.attrib.get("content-desc", "")
        label = normalize(" ".join((text, desc)))
        match = re.fullmatch(
            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
            raw.attrib.get("bounds", ""),
        )
        if not label or not match:
            continue
        bounds = tuple(map(int, match.groups()))
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            continue
        result.append(UINode(
            label=label,
            bounds=bounds,
            clickable=raw.attrib.get("clickable") == "true",
            enabled=raw.attrib.get("enabled", "true") == "true",
        ))
    return result


def choose_action(task: str, nodes: Iterable[UINode]) -> tuple[Optional[UINode], str]:
    """Return a unique, context-bound accessibility target or a refusal reason."""
    spec = SPECS.get(task)
    if spec is None:
        return None, "unknown_task"
    visible = list(nodes)
    screen_text = " | ".join(node.label for node in visible)
    if not any(normalize(context) in screen_text for context in spec.contexts):
        return None, "screen_context_not_confirmed"
    targets = [
        node for node in visible
        if node.clickable and node.enabled
        and node.label in {normalize(label) for label in spec.labels}
    ]
    if len(targets) != 1:
        return None, "target_not_unique"
    return targets[0], "ready"


def execute_verified(
    task: str,
    read_nodes: Callable[[], list[UINode]],
    tap: Callable[[int, int], None],
    wait_seconds: float = 1.25,
) -> tuple[bool, str]:
    """Tap a unique target and require a measurable hierarchy change."""
    before = read_nodes()
    target, reason = choose_action(task, before)
    if target is None:
        return False, reason
    tap(*target.center)
    time.sleep(wait_seconds)
    after = read_nodes()
    before_signature = tuple((n.label, n.bounds, n.enabled) for n in before)
    after_signature = tuple((n.label, n.bounds, n.enabled) for n in after)
    if not after or after_signature == before_signature:
        return False, "no_ui_change"
    # A changed hierarchy is evidence of UI transition, not proof that the
    # server accepted the in-game action. Report this distinction explicitly.
    return True, "ui_changed_result_unconfirmed"




SCREEN_SIGNATURES = {
    "base": ("сумка", "герой", "мир", "почта"),
    "quest_panel": ("задания", "миссии", "ежедневные задания", "quests", "missions"),
    "alliance": ("альянс", "помощь альянсу", "технологии альянса"),
    "inventory": ("сумка", "рюкзак", "инвентарь", "inventory", "bag"),
    "mail": ("почта", "письма", "mail"),
    "popup": ("подтвердить", "отмена", "закрыть", "confirm", "cancel", "close"),
}

def classify_screen(lines: Iterable[dict]) -> dict:
    """Classify a game view from independent OCR labels; observation only."""
    normalized = [normalize(str(line.get("normalized", line.get("text", "")))) for line in lines]
    joined = " | ".join(normalized)
    scores = {}
    for screen_type, markers in SCREEN_SIGNATURES.items():
        hits = [marker for marker in markers if normalize(marker) in joined]
        if hits:
            scores[screen_type] = {"score": len(hits), "markers": hits}
    if not scores:
        # Unity-based city view often exposes noisy OCR rather than stable menu labels.
        # Recognize a generic game view from HUD/resource counters and lower-screen UI
        # density, but do not treat this fallback as permission to tap anything.
        top_hud = [line for line in lines if line.get("region") == "top_hud"
                   and re.search(r"\\d", str(line.get("text", "")))]
        bottom_ui = [line for line in lines if line.get("region") == "bottom_menu"]
        if len(top_hud) >= 2 and (len(bottom_ui) >= 1 or len(normalized) >= 12):
            return {"type": "game_view", "confidence": 0.60,
                    "evidence": ["multiple_top_hud_counters", "unity_game_layout"]}
        return {"type": "unknown", "confidence": 0.0, "evidence": []}
    ranked = sorted(scores.items(), key=lambda item: (item[1]["score"], item[0]), reverse=True)
    screen_type, evidence = ranked[0]
    distinctive = {"quest_panel": ("задания", "ежедневные задания", "missions", "quests"),
                   "alliance": ("помощь альянсу", "технологии альянса"),
                   "mail": ("почта", "mail")}
    has_title = any(normalize(x) in joined for x in distinctive.get(screen_type, ()))
    if evidence["score"] < 2 and not has_title:
        return {"type": "unknown", "confidence": 0.0, "evidence": evidence["markers"]}
    confidence = min(0.99, 0.55 + 0.15 * evidence["score"] + (0.1 if has_title else 0))
    return {"type": screen_type, "confidence": round(confidence, 2), "evidence": evidence["markers"]}


def suggest_quest_actions(lines: Iterable[dict]) -> list[dict]:
    """Extract possible quest action labels for review; never returns coordinates."""
    verbs = ("забрать", "получить", "выполнить", "перейти", "начать", "собрать",
             "claim", "collect", "go", "start", "complete")
    suggestions = []
    for line in lines:
        text = str(line.get("text", "")).strip()
        confidence = float(line.get("confidence", line.get("conf", 0)) or 0)
        normalized = normalize(text)
        matched = [verb for verb in verbs if re.search(r"(?<![a-zа-я])" + re.escape(normalize(verb)) + r"(?![a-zа-я])", normalized)]
        if matched and confidence >= 75:
            suggestions.append({"label": text, "verbs": matched, "confidence": round(confidence, 1)})
    return suggestions

def analyze_screen(words: Iterable[dict], width: int, height: int) -> dict:
    """Summarize OCR observations by screen region; never produces tap coordinates."""
    if width <= 0 or height <= 0:
        raise ValueError("Screen dimensions must be positive")
    observations = []
    for word in words:
        text = str(word.get("text", "")).strip()
        try:
            x, y = int(word["x"]), int(word["y"])
            confidence = float(word.get("conf", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if not text or confidence < 65 or not (0 <= x < width and 0 <= y < height):
            continue
        region = "top_hud" if y < height * 0.16 else "bottom_menu" if y > height * 0.82 else "game_area"
        observations.append({"text": text, "x": x, "y": y, "confidence": round(confidence, 1), "region": region})

    rows = []
    for item in sorted(observations, key=lambda value: (value["y"], value["x"])):
        row = next((candidate for candidate in rows if abs(candidate["y"] - item["y"]) <= 28), None)
        if row is None:
            row = {"y": item["y"], "items": []}
            rows.append(row)
        row["items"].append(item)

    lines = []
    for row in rows:
        row["items"].sort(key=lambda value: value["x"])
        text = " ".join(item["text"] for item in row["items"])
        y = row["y"]
        normalized = normalize(text)
        region = "top_hud" if y < height * 0.16 else "bottom_menu" if y > height * 0.82 else "game_area"
        lines.append({"text": text, "normalized": normalized, "y": y, "region": region,
                      "confidence": round(sum(item["confidence"] for item in row["items"]) / len(row["items"]), 1)})

    nav_terms = {"сумка": "bag", "звезды": "stars", "почта": "mail", "герой": "hero", "мир": "world"}
    navigation = sorted({value for line in lines for term, value in nav_terms.items()
                         if term in line["normalized"]})
    quest_terms = ("соберите", "задание", "миссия", "quest", "mission")
    quests = [line["text"] for line in lines if any(term in line["normalized"] for term in quest_terms)]
    counters = []
    for item in observations:
        compact = re.sub(r"[^0-9.,kmb]", "", item["text"].casefold())
        if item["region"] == "top_hud" and any(char.isdigit() for char in compact):
            counters.append({"text": item["text"], "x": item["x"], "y": item["y"],
                             "confidence": item["confidence"]})
    screen = classify_screen(lines)
    action_suggestions = suggest_quest_actions(lines)
    return {"resolution": [width, height], "lines": lines, "navigation": navigation,
            "quest_text": quests, "top_counters": counters, "screen": screen,
            "action_suggestions": action_suggestions,
            "observed_word_count": len(observations)}
