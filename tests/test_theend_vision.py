import unittest

from theend_vision import UINode, choose_action, parse_hierarchy


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


if __name__ == "__main__":
    unittest.main()
