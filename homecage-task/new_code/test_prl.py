from __future__ import annotations

import builtins
import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schedules import ReversalSchedule, validate_reversal_schedule
from task_common import derive_rng


def import_prl_without_pygame():
    sys.modules.pop("prl", None)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pygame" or name.startswith("pygame."):
            raise ImportError("pygame intentionally blocked for headless import test")
        return real_import(name, globals, locals, fromlist, level)

    with mock.patch("builtins.__import__", side_effect=guarded_import):
        import prl
    return prl


class TestPRL(unittest.TestCase):
    def make_schedule(self, seed=123, n_blocks=6, block_len=80):
        sched = ReversalSchedule.generate(
            seed=seed,
            n_blocks=n_blocks,
            block_len=block_len,
            reversal_min=30,
            reversal_max=50,
            schedule_set="80-20",
            initial_high_label="r",
        )
        validate_reversal_schedule(sched)
        return sched

    def test_import_headless(self):
        prl = import_prl_without_pygame()
        sched = self.make_schedule()
        rng = derive_rng(1, "reward")

        resolved = prl.resolve_trial(sched, 0, sched.lookup(0)["high_label"], rng)
        self.assertIn("reward_won", resolved)

        rows = prl.simulate(sched, seed=1, sim_choices="high", total_trials=10)
        self.assertEqual(len(rows), 10)
        self.assertIn("left_label", rows[0])

    def test_reward_rate(self):
        import prl

        sched = self.make_schedule(seed=222, n_blocks=6, block_len=80)
        total = sched.n_blocks * sched.block_len
        n = 5000

        high_rng = derive_rng(777, "reward")
        high_wins = 0
        for i in range(n):
            t = i % total
            chosen = sched.lookup(t)["high_label"]
            r = prl.resolve_trial(sched, t, chosen, high_rng)
            if r["reward_won"]:
                high_wins += 1

        low_rng = derive_rng(888, "reward")
        low_wins = 0
        for i in range(n):
            t = i % total
            high_label = sched.lookup(t)["high_label"]
            chosen = "nr" if high_label == "r" else "r"
            r = prl.resolve_trial(sched, t, chosen, low_rng)
            if r["reward_won"]:
                low_wins += 1

        self.assertLess(abs((high_wins / float(n)) - 0.80), 0.03)
        self.assertLess(abs((low_wins / float(n)) - 0.20), 0.03)

    def test_reversal_performance_independent(self):
        import prl

        sched = self.make_schedule(seed=333, n_blocks=6, block_len=80)
        total = sched.n_blocks * sched.block_len
        rows_high = prl.simulate(sched, seed=10, sim_choices="high", total_trials=total)
        rows_low = prl.simulate(sched, seed=10, sim_choices="low", total_trials=total)

        self.assertEqual(
            [r["high_label"] for r in rows_high],
            [r["high_label"] for r in rows_low],
        )

        for block_index in range(sched.n_blocks):
            block_rows = [r for r in rows_high if r["block_index"] == block_index]
            reversal_trial = block_rows[0]["scheduled_reversal_trial"]
            changes = []
            for prev, cur in zip(block_rows[:-1], block_rows[1:]):
                if prev["high_label"] != cur["high_label"]:
                    changes.append(cur["trial_in_block"])

            self.assertEqual(changes, [reversal_trial])
            self.assertNotEqual(
                block_rows[reversal_trial - 1]["high_label"],
                block_rows[reversal_trial]["high_label"],
            )

    def test_seed_reproducible(self):
        import prl

        sched = self.make_schedule(seed=444, n_blocks=6, block_len=80)
        total = sched.n_blocks * sched.block_len
        rows_a = prl.simulate(sched, seed=55, sim_choices="high", total_trials=total)
        rows_b = prl.simulate(sched, seed=55, sim_choices="high", total_trials=total)
        rows_c = prl.simulate(sched, seed=56, sim_choices="high", total_trials=total)

        self.assertEqual(rows_a, rows_b)
        self.assertEqual(
            [r["schedule_hash"] for r in rows_a],
            [r["schedule_hash"] for r in rows_b],
        )
        self.assertEqual(
            [r["left_label"] for r in rows_a],
            [r["left_label"] for r in rows_b],
        )
        self.assertEqual(
            [r["reward_won"] for r in rows_a],
            [r["reward_won"] for r in rows_b],
        )
        self.assertNotEqual(
            [r["reward_won"] for r in rows_a],
            [r["reward_won"] for r in rows_c],
        )

    def test_correct_and_iti(self):
        import prl

        sched = self.make_schedule(seed=555, n_blocks=6, block_len=80)
        rows = prl.simulate(sched, seed=66, sim_choices="random", total_trials=sched.n_blocks * sched.block_len)

        for row in rows:
            self.assertEqual(row["is_correct"], row["chosen_label"] == row["high_label"])
            self.assertEqual(row["iti_kind"], "rewarded" if row["reward_won"] else "unrewarded")

        unrewarded_correct = None
        for seed in range(1, 50):
            high_rows = prl.simulate(sched, seed=seed, sim_choices="high", total_trials=sched.n_blocks * sched.block_len)
            for row in high_rows:
                if row["is_correct"] and not row["reward_won"]:
                    unrewarded_correct = row
                    break
            if unrewarded_correct is not None:
                break

        self.assertIsNotNone(unrewarded_correct)
        self.assertTrue(unrewarded_correct["is_correct"])
        self.assertFalse(unrewarded_correct["reward_won"])
        self.assertEqual(unrewarded_correct["iti_kind"], "unrewarded")

    def test_csv_fieldnames(self):
        import prl

        sched = self.make_schedule(seed=666, n_blocks=6, block_len=80)
        rows = prl.simulate(sched, seed=77, sim_choices="alternate", total_trials=40)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = prl.write_simulation_csv(rows, tmpdir, filename="sim.csv")
            with open(out_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)

        for name in [
            "seed",
            "schedule_hash",
            "block_index",
            "trial_in_block",
            "scheduled_reversal_trial",
            "is_post_reversal",
            "high_label",
            "p_high",
            "p_low",
            "chosen_label",
            "is_correct",
            "p_chosen",
            "reward_draw",
            "reward_won",
            "reward_delivered",
            "iti_kind",
        ]:
            self.assertIn(name, header)

    def test_parse_args_allows_rectangular_stim(self):
        import prl

        args = prl.parse_args(["--seed", "1", "--stim-w", "300", "--stim-h", "200"])
        self.assertIsNone(args.stim_px)
        self.assertEqual(args.stim_w, 300)
        self.assertEqual(args.stim_h, 200)

    def test_main_restores_default_stim_px_when_unspecified(self):
        import prl

        captured = {}

        def fake_run(args):
            captured["args"] = args

        with mock.patch.object(sys, "argv", ["prl.py", "--seed", "1"]), mock.patch.object(prl, "run", side_effect=fake_run):
            prl.main()

        self.assertEqual(captured["args"].stim_px, 240)
        self.assertIsNone(captured["args"].stim_w)
        self.assertIsNone(captured["args"].stim_h)

    def test_main_rejects_partial_stim_size(self):
        import prl

        with mock.patch.object(sys, "argv", ["prl.py", "--seed", "1", "--stim-w", "300"]), mock.patch.object(prl, "run") as run_mock:
            with self.assertRaises(SystemExit) as cm:
                prl.main()

        self.assertEqual(cm.exception.code, 1)
        run_mock.assert_not_called()

    def test_main_rejects_partial_plate_size(self):
        import prl

        with mock.patch.object(sys, "argv", ["prl.py", "--seed", "1", "--plate-w", "300"]), mock.patch.object(prl, "run") as run_mock:
            with self.assertRaises(SystemExit) as cm:
                prl.main()

        self.assertEqual(cm.exception.code, 1)
        run_mock.assert_not_called()

    def test_main_allows_explicit_plate_size(self):
        import prl

        captured = {}

        def fake_run(args):
            captured["args"] = args

        with mock.patch.object(sys, "argv", ["prl.py", "--seed", "1", "--plate-w", "300", "--plate-h", "200"]), mock.patch.object(prl, "run", side_effect=fake_run):
            prl.main()

        self.assertEqual(captured["args"].plate_w, 300)
        self.assertEqual(captured["args"].plate_h, 200)

    def test_make_beep_sound_clamps_numpy_volume(self):
        import task_common

        def first_wave_multiplier(volume):
            captured = {"multipliers": []}

            class FakeArray:
                def __truediv__(self, _other):
                    return self

                def __rmul__(self, _other):
                    return self

            class FakeWave:
                def __mul__(self, value):
                    captured["multipliers"].append(value)
                    return self

                def astype(self, _dtype):
                    return [0]

            class FakeNumpy:
                float32 = "float32"
                int16 = "int16"

                @staticmethod
                def arange(_n_samples, dtype=None):
                    return FakeArray()

                @staticmethod
                def sin(_values):
                    return FakeWave()

                @staticmethod
                def column_stack(values):
                    return values

            fake_pygame = mock.Mock()
            fake_pygame.sndarray.make_sound.return_value = "sound"

            with mock.patch.dict(sys.modules, {"pygame": fake_pygame, "numpy": FakeNumpy()}):
                self.assertEqual(task_common.make_beep_sound(1000, 1, volume), "sound")

            return captured["multipliers"][0]

        self.assertEqual(first_wave_multiplier(2.5), 1.0)
        self.assertEqual(first_wave_multiplier(-2.5), 0.0)


if __name__ == "__main__":
    unittest.main()
