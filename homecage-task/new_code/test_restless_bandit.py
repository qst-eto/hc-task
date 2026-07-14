from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from unittest import mock
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Tuple

CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import restless_bandit
from schedules import BanditWalk, longest_double_low_run, validate_bandit_walk
from task_common import derive_rng

K_WALKS = 40
N_TRIALS = 300
_WALK_CACHE: Dict[int, BanditWalk] = {}


def generated_walk(seed: int) -> BanditWalk:
    if seed not in _WALK_CACHE:
        _WALK_CACHE[seed] = BanditWalk.generate(
            seed=seed,
            n_trials=N_TRIALS,
            step_prob=0.10,
            step_size=0.10,
            p_init_left=0.50,
            p_init_right=0.50,
            p_floor=0.10,
            p_ceil=0.90,
            balance_tol=0.02,
            double_low_thresh=0.20,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
        )
    return _WALK_CACHE[seed]


def constructed_walk(pairs: List[Tuple[float, float]]) -> BanditWalk:
    p_left = [p[0] for p in pairs]
    p_right = [p[1] for p in pairs]
    return BanditWalk(
        seed=999,
        n_trials=len(pairs),
        step_prob=0.0,
        step_size=0.0,
        p_init_left=p_left[0],
        p_init_right=p_right[0],
        p_floor=0.0,
        p_ceil=1.0,
        balance_tol=1.0,
        double_low_thresh=0.0,
        double_low_max_run=len(pairs),
        boundary_mode="reject-step",
        max_attempts=1,
        p_left=p_left,
        p_right=p_right,
        attempts=1,
        meta={"balance_metric": "test_balance_metric"},
    )


def sim_args(out_dir: str, seed: int = 123, n_trials: int = 30, max_trials: int = 12):
    return Namespace(
        seed=seed,
        walk_json=None,
        save_walk_json=None,
        n_trials=n_trials,
        step_prob_frac=0.10,
        step_size_frac=0.10,
        p_init_left_frac=0.50,
        p_init_right_frac=0.50,
        p_floor_frac=0.10,
        p_ceil_frac=0.90,
        balance_tol_frac=0.02,
        double_low_thresh_frac=0.20,
        double_low_max_run=29,
        boundary_mode="reject-step",
        max_walk_generation_attempts=10000,
        sim_choices="random",
        max_trials=max_trials,
        max_rewards=None,
        out_dir=out_dir,
    )


class RestlessBanditTests(unittest.TestCase):
    def test_import_headless(self):
        self.assertTrue(callable(restless_bandit.resolve_trial))
        self.assertTrue(callable(restless_bandit.simulate))
        self.assertFalse(hasattr(restless_bandit, "pygame"))

        walk = constructed_walk([(0.5, 0.5), (0.7, 0.2), (0.1, 0.9)])
        row = restless_bandit.resolve_trial(walk, 0, "left", derive_rng(1, "reward"))
        self.assertEqual(row["trial_index"], 0)
        self.assertEqual(row["chosen_side"], "left")

        rows = restless_bandit.simulate(walk, 1, "higher", 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["chosen_side"], "left")

    def test_reward_rate(self):
        total_left_rewards = 0
        total_right_rewards = 0
        total_left_p = 0.0
        total_right_p = 0.0
        total_trials = 0

        for seed in range(K_WALKS):
            walk = generated_walk(seed)
            rows_left = restless_bandit.simulate(walk, seed, "left", N_TRIALS)
            rows_right = restless_bandit.simulate(walk, seed, "right", N_TRIALS)

            total_left_rewards += sum(1 for r in rows_left if r["reward_won"])
            total_right_rewards += sum(1 for r in rows_right if r["reward_won"])
            total_left_p += sum(walk.p_left)
            total_right_p += sum(walk.p_right)
            total_trials += N_TRIALS

        emp_left = total_left_rewards / float(total_trials)
        emp_right = total_right_rewards / float(total_trials)
        mean_left = total_left_p / float(total_trials)
        mean_right = total_right_p / float(total_trials)

        self.assertLessEqual(abs(emp_left - mean_left), 0.02)
        self.assertLessEqual(abs(emp_right - mean_right), 0.02)

    def test_walk_constraints(self):
        for seed in range(K_WALKS):
            walk = generated_walk(seed)
            validate_bandit_walk(walk)

            mean_left = sum(walk.p_left) / float(walk.n_trials)
            mean_right = sum(walk.p_right) / float(walk.n_trials)
            self.assertLessEqual(abs(mean_left - mean_right), walk.balance_tol + 1e-9)

            for p in walk.p_left + walk.p_right:
                self.assertGreaterEqual(p, walk.p_floor - 1e-9)
                self.assertLessEqual(p, walk.p_ceil + 1e-9)

            self.assertLessEqual(
                longest_double_low_run(walk.p_left, walk.p_right, walk.double_low_thresh),
                walk.double_low_max_run,
            )

    def test_seed_reproducible(self):
        walk = generated_walk(0)
        rows_a = restless_bandit.simulate(walk, 77, "random", 80)
        rows_b = restless_bandit.simulate(walk, 77, "random", 80)
        rows_c = restless_bandit.simulate(walk, 78, "random", 80)

        self.assertEqual(
            [(r["walk_hash"], r["reward_won"]) for r in rows_a],
            [(r["walk_hash"], r["reward_won"]) for r in rows_b],
        )
        self.assertNotEqual(
            [r["reward_won"] for r in rows_a],
            [r["reward_won"] for r in rows_c],
        )

        tie_walk = constructed_walk([(0.5, 0.5), (0.1, 0.9), (0.3, 0.3), (0.8, 0.2)])
        tie_a = restless_bandit.simulate(tie_walk, 1, "higher", 4)
        tie_b = restless_bandit.simulate(tie_walk, 999, "higher", 4)
        self.assertEqual([tie_a[0]["chosen_side"], tie_a[2]["chosen_side"]], ["left", "left"])
        self.assertEqual([tie_b[0]["chosen_side"], tie_b[2]["chosen_side"]], ["left", "left"])

    def test_no_correct_column(self):
        self.assertNotIn("correct", restless_bandit.CSV_FIELDNAMES)
        self.assertNotIn("is_correct", restless_bandit.CSV_FIELDNAMES)
        self.assertIn("chose_higher_p", restless_bandit.CSV_FIELDNAMES)

        walk = constructed_walk([(0.5, 0.5)])
        row = restless_bandit.resolve_trial(walk, 0, "left", derive_rng(2, "reward"))
        self.assertEqual(row["chose_higher_p"], "")

    def test_csv_no_dictwriter_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = restless_bandit.run_sim(sim_args(tmp))
            with path.open("r", newline="", encoding="utf-8") as f:
                header = next(csv.reader(f))

        for name in [
            "p_left",
            "p_right",
            "chosen_side",
            "p_chosen",
            "chose_higher_p",
            "reward_won",
            "reward_delivered",
            "walk_hash",
            "iti_kind",
        ]:
            self.assertIn(name, header)
        self.assertNotIn("is_correct", header)

    def test_spatial_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = restless_bandit.parse_args([
                "--seed", "11",
                "--sim",
                "--n-trials", "12",
                "--max-trials", "5",
                "--out-dir", tmp,
            ])
            self.assertFalse(args.images)
            self.assertIsNone(args.stim_dir)

            path = restless_bandit.run_sim(args)
            self.assertTrue(path.exists())

    def test_simulate_blank_timestamps(self):
        walk = constructed_walk([(0.5, 0.5), (0.7, 0.2), (0.1, 0.9)])
        rows = restless_bandit.simulate(walk, 1, "higher", 3)

        for row in rows:
            self.assertEqual(row["start_iso"], "")
            self.assertEqual(row["iso"], "")
            self.assertEqual(row["rel_s"], "")

    def test_main_rejects_partial_plate_size(self):
        with mock.patch.object(sys, "argv", ["restless_bandit.py", "--seed", "1", "--sim", "--plate-w", "300"]), mock.patch.object(restless_bandit, "run_sim") as run_sim_mock:
            with self.assertRaises(SystemExit) as cm:
                restless_bandit.main()

        self.assertEqual(cm.exception.code, 1)
        run_sim_mock.assert_not_called()

    def test_main_allows_explicit_plate_size(self):
        captured = {}

        def fake_run_sim(args):
            captured["args"] = args

        with mock.patch.object(sys, "argv", ["restless_bandit.py", "--seed", "1", "--sim", "--plate-w", "300", "--plate-h", "200"]), mock.patch.object(restless_bandit, "run_sim", side_effect=fake_run_sim):
            restless_bandit.main()

        self.assertEqual(captured["args"].plate_w, 300)
        self.assertEqual(captured["args"].plate_h, 200)


if __name__ == "__main__":
    unittest.main()
