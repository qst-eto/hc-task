from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schedules import BanditWalk, ReversalSchedule, validate_bandit_walk, validate_reversal_schedule
from task_common import derive_rng, sample_reward


class TestReversalSchedule(unittest.TestCase):
    def test_reversal_schedule_many_seeds(self) -> None:
        for seed in range(1000):
            schedule = ReversalSchedule.generate(seed=seed, n_blocks=6, block_len=80)
            validate_reversal_schedule(schedule)

            for block in schedule.blocks:
                self.assertGreaterEqual(block["reversal_trial"], 30)
                self.assertLessEqual(block["reversal_trial"], 50)

            same = ReversalSchedule.generate(seed=seed, n_blocks=6, block_len=80)
            self.assertEqual(schedule.schedule_hash(), same.schedule_hash())

            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                path = tmp.name
            try:
                schedule.to_json(path)
                loaded = ReversalSchedule.from_json(path)
                self.assertEqual(schedule.schedule_hash(), loaded.schedule_hash())
            finally:
                os.unlink(path)


class TestBanditWalk(unittest.TestCase):
    def test_bandit_walk_many_seeds(self) -> None:
        attempts = []

        for seed in range(1000):
            walk = BanditWalk.generate(seed=seed)
            validate_bandit_walk(walk)
            attempts.append(walk.attempts)

            same = BanditWalk.generate(seed=seed)
            self.assertEqual(walk.walk_hash(), same.walk_hash())

            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                path = tmp.name
            try:
                walk.to_json(path)
                loaded = BanditWalk.from_json(path)
                self.assertEqual(walk.walk_hash(), loaded.walk_hash())
                self.assertEqual(walk.p_left, loaded.p_left)
                self.assertEqual(walk.p_right, loaded.p_right)
            finally:
                os.unlink(path)

        mean_attempts = sum(attempts) / float(len(attempts))
        self.assertLess(mean_attempts, 50)
        self.assertGreaterEqual(max(attempts), 1)

    def test_bandit_walk_from_json_rebuilds_missing_meta(self) -> None:
        walk = BanditWalk.generate(seed=1234)
        legacy_content = dict(walk._content())
        legacy_content.pop("meta")

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp:
            path = tmp.name
            json.dump(legacy_content, tmp, sort_keys=True, indent=2)

        try:
            loaded = BanditWalk.from_json(path)
        finally:
            os.unlink(path)

        self.assertEqual(loaded.meta["balance_metric"], "between_arm_session_mean_abs_diff")
        self.assertEqual(walk.walk_hash(), loaded.walk_hash())

    def test_double_low_boundary(self) -> None:
        pass_walk = BanditWalk(
            seed=1,
            n_trials=40,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=-1.0,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.1] * 29 + [0.2] * 11,
            p_right=[0.1] * 29 + [0.2] * 11,
            attempts=1,
        )
        validate_bandit_walk(pass_walk)

        fail_walk = BanditWalk(
            seed=1,
            n_trials=40,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=-1.0,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.1] * 30 + [0.2] * 10,
            p_right=[0.1] * 30 + [0.2] * 10,
            attempts=1,
        )
        with self.assertRaises(AssertionError):
            validate_bandit_walk(fail_walk)

    def test_bounds_boundary(self) -> None:
        exact_bounds = BanditWalk(
            seed=1,
            n_trials=2,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=-1.0,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.1, 0.9],
            p_right=[0.9, 0.1],
            attempts=1,
        )
        validate_bandit_walk(exact_bounds)

        below_floor = BanditWalk(
            seed=1,
            n_trials=1,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=-1.0,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.099],
            p_right=[0.5],
            attempts=1,
        )
        with self.assertRaises(AssertionError):
            validate_bandit_walk(below_floor)

        above_ceil = BanditWalk(
            seed=1,
            n_trials=1,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=-1.0,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.5],
            p_right=[0.901],
            attempts=1,
        )
        with self.assertRaises(AssertionError):
            validate_bandit_walk(above_ceil)

    def test_balance_boundary(self) -> None:
        exact_tol = BanditWalk(
            seed=1,
            n_trials=2,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=0.02,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.5, 0.5],
            p_right=[0.48, 0.48],
            attempts=1,
        )
        validate_bandit_walk(exact_tol)

        over_tol = BanditWalk(
            seed=1,
            n_trials=2,
            step_prob=0.1,
            step_size=0.1,
            p_init_left=0.5,
            p_init_right=0.5,
            p_floor=0.1,
            p_ceil=0.9,
            balance_tol=0.02,
            double_low_thresh=0.2,
            double_low_max_run=29,
            boundary_mode="reject-step",
            max_attempts=10000,
            p_left=[0.5, 0.5],
            p_right=[0.479, 0.479],
            attempts=1,
        )
        with self.assertRaises(AssertionError):
            validate_bandit_walk(over_tol)


class TestTaskCommon(unittest.TestCase):
    def test_sample_reward_empirical_rates(self) -> None:
        n = 100000

        for p in (0.2, 0.5, 0.8):
            rng = random.Random(12345)
            wins = 0
            for _ in range(n):
                _u, won = sample_reward(rng, p)
                if won:
                    wins += 1

            empirical_rate = wins / float(n)
            self.assertLess(abs(empirical_rate - p), 0.01)

    def test_derive_rng_streams(self) -> None:
        draws_a = [derive_rng(123, "a").random() for _ in range(1)]
        rng_a = derive_rng(123, "a")
        rng_b = derive_rng(123, "b")
        seq_a = [rng_a.random() for _ in range(1000)]
        seq_b = [rng_b.random() for _ in range(1000)]
        self.assertNotEqual(seq_a, seq_b)

        rng_a_again = derive_rng(123, "a")
        seq_a_again = [rng_a_again.random() for _ in range(1000)]
        self.assertEqual(seq_a, seq_a_again)
        self.assertEqual(draws_a[0], derive_rng(123, "a").random())


if __name__ == "__main__":
    unittest.main()
