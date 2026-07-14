from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import touch_task_runner as ttr


def old_two_choice_rects(sw, sh, item_w, item_h, plate_w, plate_h, center_offset_px, edge_margin_px):
    max_offset = max(0, (sw // 2) - (plate_w // 2) - edge_margin_px)
    center_offset = min(max_offset, max(0, center_offset_px))

    cy = sh // 2
    left_cx = (sw // 2) - center_offset
    right_cx = (sw // 2) + center_offset

    return (
        (left_cx - item_w // 2, cy - item_h // 2, item_w, item_h),
        (right_cx - item_w // 2, cy - item_h // 2, item_w, item_h),
        (left_cx - plate_w // 2, cy - plate_h // 2, plate_w, plate_h),
        (right_cx - plate_w // 2, cy - plate_h // 2, plate_w, plate_h),
        center_offset,
    )


def rect_tuple(rect):
    return (rect.x, rect.y, rect.w, rect.h)


class TouchTaskRunnerTests(unittest.TestCase):
    def test_import_headless_without_pygame(self):
        sys.modules.pop("touch_task_runner", None)
        real_import = __import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pygame" or name.startswith("pygame."):
                raise ImportError("pygame intentionally blocked for headless import test")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            __import__("touch_task_runner")

    def test_complete_csv_row_rejects_extra_keys_and_preserves_field_order(self):
        fieldnames = ["b", "a", "c"]

        complete = ttr.complete_csv_row({"a": 1}, fieldnames)

        self.assertEqual(list(complete.keys()), fieldnames)
        self.assertEqual(complete, {"b": "", "a": 1, "c": ""})

        with self.assertRaisesRegex(ValueError, "extra"):
            ttr.complete_csv_row({"a": 1, "extra": 2}, fieldnames)

    def test_bounded_range_matches_existing_boundaries(self):
        self.assertEqual(ttr.bounded_range(None, None, 100, 200), (100, 200))
        self.assertEqual(ttr.bounded_range(300, 100, 100, 200), (300, 300))
        self.assertEqual(ttr.bounded_range(-10, 50, 100, 200), (0, 50))
        self.assertEqual(ttr.bounded_range(None, 50, 100, 200), (100, 100))

    def test_truncate_at_max_rewards_preserves_existing_truthiness_and_boundary(self):
        rows = [
            {"id": 1, "reward_delivered": 0},
            {"id": 2, "reward_delivered": ""},
            {"id": 3, "reward_delivered": 1},
            {"id": 4, "reward_delivered": 0},
            {"id": 5, "reward_delivered": 1},
        ]

        self.assertIs(ttr.truncate_at_max_rewards(rows, None), rows)
        self.assertEqual(ttr.truncate_at_max_rewards(rows, 0), rows[:3])
        self.assertEqual(ttr.truncate_at_max_rewards(rows, 1), rows[:3])
        self.assertEqual(ttr.truncate_at_max_rewards(rows, 2), rows[:5])

    def test_compute_two_choice_rects_matches_old_prl_and_restless_geometry(self):
        cases = [
            (1280, 720, 240, 240, 240, 240, 300, 16),
            (1000, 600, 300, 200, 340, 260, 220, 20),
            (400, 300, 240, 240, 300, 260, 300, 80),
            (900, 500, 180, 220, 260, 260, -50, 10),
        ]

        for case in cases:
            with self.subTest(case=case):
                expected = old_two_choice_rects(*case)
                rects, center_offset = ttr.compute_two_choice_rects(*case)

                self.assertEqual(rect_tuple(rects.left), expected[0])
                self.assertEqual(rect_tuple(rects.right), expected[1])
                self.assertEqual(rect_tuple(rects.left_plate), expected[2])
                self.assertEqual(rect_tuple(rects.right_plate), expected[3])
                self.assertEqual(center_offset, expected[4])


if __name__ == "__main__":
    unittest.main()
