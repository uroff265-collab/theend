import unittest

from theend_vision import UINode, analyze_screen, choose_action, parse_hierarchy, classify_screen, suggest_quest_actions


class VisionTests(unittest.TestCase):
    def test_parse_android_accessibility_nodes(self):
        xml = """<hierarchy><node text="Помощь альянсу" bounds="[0,0][200,50]" clickable="false" enabled="true"/><node text="Помочь всем" bounds="[20,80][180,130]" clickable="true" enabled="true"/></hierarchy>"""
        nodes = parse_hierarchy(xml)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1].center, (100, 105))

    def test_unique_contextual_button_is_selected(self):
        nodes = [
            UINode("помощь альянсу", (0, 0, 200, 50), False, True),
            UINode("помочь всем", (20, 80, 180, 130), True, True),
        ]
        target, reason = choose_action("alliance_help", nodes)
        self.assertEqual(reason, "ready")
        self.assertEqual(target.center, (100, 105))

    def test_duplicate_buttons_are_rejected(self):
        nodes = [
            UINode("помощь альянсу", (0, 0, 200, 50), False, True),
            UINode("помочь всем", (20, 80, 180, 130), True, True),
            UINode("помочь всем", (20, 150, 180, 200), True, True),
        ]
        target, reason = choose_action("alliance_help", nodes)
        self.assertIsNone(target)
        self.assertEqual(reason, "target_not_unique")

    def test_wrong_screen_is_rejected(self):
        nodes = [UINode("помочь всем", (20, 80, 180, 130), True, True)]
        target, reason = choose_action("alliance_help", nodes)
        self.assertIsNone(target)
        self.assertEqual(reason, "screen_context_not_confirmed")

    def test_disabled_button_is_rejected(self):
        nodes = [
            UINode("помощь альянсу", (0, 0, 200, 50), False, True),
            UINode("помочь всем", (20, 80, 180, 130), True, False),
        ]
        target, reason = choose_action("alliance_help", nodes)
        self.assertIsNone(target)
        self.assertEqual(reason, "target_not_unique")


    def test_analyze_russian_game_hud_and_quest(self):
        words = [
            {"text": "VIP", "x": 80, "y": 55, "conf": 90},
            {"text": "5", "x": 115, "y": 55, "conf": 92},
            {"text": "12.7M", "x": 260, "y": 100, "conf": 88},
            {"text": "Соберите", "x": 330, "y": 1180, "conf": 91},
            {"text": "3000000", "x": 490, "y": 1180, "conf": 90},
            {"text": "древесины", "x": 630, "y": 1180, "conf": 90},
            {"text": "Сумка", "x": 110, "y": 1510, "conf": 93},
            {"text": "Почта", "x": 780, "y": 1510, "conf": 94},
        ]
        state = analyze_screen(words, 900, 1600)
        self.assertEqual(state["resolution"], [900, 1600])
        self.assertEqual(state["navigation"], ["bag", "mail"])
        self.assertTrue(any("Соберите" in line for line in state["quest_text"]))
        self.assertIn("12.7M", [item["text"] for item in state["top_counters"]])

    def test_analyze_screen_rejects_out_of_bounds_and_low_confidence(self):
        words = [
            {"text": "Сумка", "x": 20, "y": 1550, "conf": 95},
            {"text": "Почта", "x": 950, "y": 1550, "conf": 95},
            {"text": "VIP", "x": 50, "y": 40, "conf": 20},
        ]
        state = analyze_screen(words, 900, 1600)
        self.assertEqual(state["navigation"], ["bag"])
        self.assertEqual(state["observed_word_count"], 1)

    def test_analyze_screen_requires_valid_dimensions(self):
        with self.assertRaises(ValueError):
            analyze_screen([], 0, 1600)


    def test_classifies_quest_panel_from_distinctive_title(self):
        result = classify_screen([
            {"text": "Ежедневные задания", "confidence": 92},
            {"text": "Соберите 3000000 древесины", "confidence": 88},
        ])
        self.assertEqual(result["type"], "quest_panel")
        self.assertGreaterEqual(result["confidence"], 0.65)

    def test_ambiguous_screen_stays_unknown(self):
        result = classify_screen([{"text": "Получить", "confidence": 90}])
        self.assertEqual(result["type"], "unknown")

    def test_quest_action_suggestions_do_not_include_coordinates(self):
        result = suggest_quest_actions([
            {"text": "Забрать награду", "confidence": 95, "x": 120, "y": 300},
            {"text": "Сумка", "confidence": 98, "x": 20, "y": 1500},
            {"text": "Получить", "confidence": 40, "x": 200, "y": 500},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["label"], "Забрать награду")
        self.assertNotIn("x", result[0])
        self.assertNotIn("y", result[0])


if __name__ == "__main__":
    unittest.main()
