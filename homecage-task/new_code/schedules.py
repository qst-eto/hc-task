from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SCHEDULE_SETS = {"80-20": (0.80, 0.20), "70-30": (0.70, 0.30), "60-40": (0.60, 0.40),"90-10": (0.90,0.10)}


def _derive_rng(master_seed: int, stream: str) -> random.Random:
    seed_bytes = hashlib.sha256((str(master_seed) + ":" + stream).encode()).digest()[:8]
    seed_int = int.from_bytes(seed_bytes, "big")
    return random.Random(seed_int)


def _other_label(label: str) -> str:
    if label == "r":
        return "nr"
    if label == "nr":
        return "r"
    raise ValueError("high label must be 'r' or 'nr'")


def _canonical_hash(content: Dict) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class ReversalSchedule:
    seed: int
    n_blocks: int
    block_len: int
    reversal_min: int
    reversal_max: int
    schedule_set: str
    initial_high_label: str
    blocks: List[Dict]

    @classmethod
    def generate(
        cls,
        seed: int,
        n_blocks: int,
        block_len: int = 80,
        reversal_min: int = 30,
        reversal_max: int = 50,
        schedule_set: str = "80-20",
        initial_high_label: str = "r",
    ) -> "ReversalSchedule":
        schedule_rng = _derive_rng(seed, "schedule")
        blocks = []

        if initial_high_label == "random":
            high_label_before = schedule_rng.choice(["r", "nr"])
        elif initial_high_label in ("r", "nr"):
            high_label_before = initial_high_label
        else:
            raise ValueError("initial_high_label must be 'r', 'nr', or 'random'")

        schedule_keys = ["80-20", "70-30", "60-40","90-10"]
        if schedule_set != "mixed" and schedule_set not in SCHEDULE_SETS:
            raise ValueError("schedule_set must be one of 80-20, 70-30, 60-40, or mixed")

        for block_index in range(n_blocks):
            reversal_trial = schedule_rng.randint(reversal_min, reversal_max)

            if schedule_set == "mixed":
                schedule_set_used = schedule_rng.choice(schedule_keys)
            else:
                schedule_set_used = schedule_set

            p_high, p_low = SCHEDULE_SETS[schedule_set_used]
            high_label_after = _other_label(high_label_before)

            blocks.append(
                {
                    "block_index": block_index,
                    "p_high": p_high,
                    "p_low": p_low,
                    "reversal_trial": reversal_trial,
                    "high_label_before": high_label_before,
                    "high_label_after": high_label_after,
                    "schedule_set_used": schedule_set_used,
                }
            )

            high_label_before = high_label_after

        return cls(
            seed=seed,
            n_blocks=n_blocks,
            block_len=block_len,
            reversal_min=reversal_min,
            reversal_max=reversal_max,
            schedule_set=schedule_set,
            initial_high_label=initial_high_label,
            blocks=blocks,
        )

    def lookup(self, global_trial: int) -> Dict:
        if global_trial < 0:
            raise IndexError("global_trial must be non-negative")
        if global_trial >= self.n_blocks * self.block_len:
            raise IndexError("global_trial exceeds schedule length")

        block_index = global_trial // self.block_len
        trial_in_block = global_trial % self.block_len
        block = self.blocks[block_index]
        reversal_trial = block["reversal_trial"]
        is_post_reversal = trial_in_block >= reversal_trial
        high_label = block["high_label_after"] if is_post_reversal else block["high_label_before"]

        return {
            "block_index": block_index,
            "trial_in_block": trial_in_block,
            "high_label": high_label,
            "p_high": block["p_high"],
            "p_low": block["p_low"],
            "scheduled_reversal_trial": reversal_trial,
            "is_post_reversal": is_post_reversal,
        }

    def _content(self) -> Dict:
        return {
            "seed": self.seed,
            "params": {
                "n_blocks": self.n_blocks,
                "block_len": self.block_len,
                "reversal_min": self.reversal_min,
                "reversal_max": self.reversal_max,
                "schedule_set": self.schedule_set,
                "initial_high_label": self.initial_high_label,
            },
            "blocks": self.blocks,
        }

    def to_json(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._content(), f, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, path) -> "ReversalSchedule":
        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)

        params = content["params"]
        return cls(
            seed=content["seed"],
            n_blocks=params["n_blocks"],
            block_len=params["block_len"],
            reversal_min=params["reversal_min"],
            reversal_max=params["reversal_max"],
            schedule_set=params["schedule_set"],
            initial_high_label=params["initial_high_label"],
            blocks=content["blocks"],
        )

    def schedule_hash(self) -> str:
        return _canonical_hash(self._content())


def validate_reversal_schedule(s) -> None:
    assert len(s.blocks) == s.n_blocks
    for expected_index, block in enumerate(s.blocks):
        assert block["block_index"] == expected_index
        assert s.reversal_min <= block["reversal_trial"] <= s.reversal_max
        assert s.block_len > block["reversal_trial"]
        assert block["p_high"] > block["p_low"]
        assert block["high_label_after"] != block["high_label_before"]


@dataclass
class BanditWalk:
    seed: int
    n_trials: int
    step_prob: float
    step_size: float
    p_init_left: float
    p_init_right: float
    p_floor: float
    p_ceil: float
    balance_tol: float
    double_low_thresh: float
    double_low_max_run: int
    boundary_mode: str
    max_attempts: int
    p_left: List[float]
    p_right: List[float]
    attempts: int = 0
    meta: Optional[Dict] = None

    @classmethod
    def generate(
        cls,
        seed: int,
        n_trials: int = 300,
        step_prob: float = 0.10,
        step_size: float = 0.10,
        p_init_left: float = 0.50,
        p_init_right: float = 0.50,
        p_floor: float = 0.10,
        p_ceil: float = 0.90,
        balance_tol: float = 0.02,
        double_low_thresh: float = 0.20,
        double_low_max_run: int = 29,
        boundary_mode: str = "reject-step",
        max_attempts: int = 10000,
    ) -> "BanditWalk":
        if boundary_mode not in ("reject-step", "reflect", "reject-walk"):
            raise ValueError("boundary_mode must be reject-step, reflect, or reject-walk")

        for attempt in range(max_attempts):
            walk_rng = _derive_rng(seed, "walk" + str(attempt))
            p_left = []
            p_right = []
            current_left = round(p_init_left, 4)
            current_right = round(p_init_right, 4)
            invalid_walk = False

            for _trial in range(n_trials):
                current_left, invalid_left = _step_probability(
                    walk_rng, current_left, step_prob, step_size, p_floor, p_ceil, boundary_mode
                )
                current_right, invalid_right = _step_probability(
                    walk_rng, current_right, step_prob, step_size, p_floor, p_ceil, boundary_mode
                )
                if invalid_left or invalid_right:
                    invalid_walk = True
                    break

                p_left.append(round(current_left, 4))
                p_right.append(round(current_right, 4))

            if invalid_walk:
                continue

            walk = cls(
                seed=seed,
                n_trials=n_trials,
                step_prob=step_prob,
                step_size=step_size,
                p_init_left=p_init_left,
                p_init_right=p_init_right,
                p_floor=p_floor,
                p_ceil=p_ceil,
                balance_tol=balance_tol,
                double_low_thresh=double_low_thresh,
                double_low_max_run=double_low_max_run,
                boundary_mode=boundary_mode,
                max_attempts=max_attempts,
                p_left=p_left,
                p_right=p_right,
                attempts=attempt + 1,
                meta=_bandit_meta(p_left, p_right),
            )

            try:
                validate_bandit_walk(walk)
            except AssertionError:
                continue

            return walk

        raise RuntimeError("failed to generate a valid BanditWalk within max_attempts")

    def p_at(self, trial: int) -> Tuple[float, float]:
        if trial < 0 or trial >= self.n_trials:
            raise IndexError("trial out of range")
        return (self.p_left[trial], self.p_right[trial])

    def _content(self) -> Dict:
        return {
            "seed": self.seed,
            "params": {
                "n_trials": self.n_trials,
                "step_prob": self.step_prob,
                "step_size": self.step_size,
                "p_init_left": self.p_init_left,
                "p_init_right": self.p_init_right,
                "p_floor": self.p_floor,
                "p_ceil": self.p_ceil,
                "balance_tol": self.balance_tol,
                "double_low_thresh": self.double_low_thresh,
                "double_low_max_run": self.double_low_max_run,
                "boundary_mode": self.boundary_mode,
                "max_attempts": self.max_attempts,
            },
            "attempts": self.attempts,
            "p_left": self.p_left,
            "p_right": self.p_right,
            "meta": self.meta if self.meta is not None else _bandit_meta(self.p_left, self.p_right),
        }

    def to_json(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._content(), f, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, path) -> "BanditWalk":
        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)

        params = content["params"]
        meta = content.get("meta")
        if meta is None:
            meta = _bandit_meta(content["p_left"], content["p_right"])

        return cls(
            seed=content["seed"],
            n_trials=params["n_trials"],
            step_prob=params["step_prob"],
            step_size=params["step_size"],
            p_init_left=params["p_init_left"],
            p_init_right=params["p_init_right"],
            p_floor=params["p_floor"],
            p_ceil=params["p_ceil"],
            balance_tol=params["balance_tol"],
            double_low_thresh=params["double_low_thresh"],
            double_low_max_run=params["double_low_max_run"],
            boundary_mode=params["boundary_mode"],
            max_attempts=params["max_attempts"],
            p_left=content["p_left"],
            p_right=content["p_right"],
            attempts=content["attempts"],
            meta=meta,
        )

    def walk_hash(self) -> str:
        return _canonical_hash(self._content())


def _step_probability(
    rng: random.Random,
    p: float,
    step_prob: float,
    step_size: float,
    p_floor: float,
    p_ceil: float,
    boundary_mode: str,
) -> Tuple[float, bool]:
    if rng.random() >= step_prob:
        return (round(p, 4), False)

    direction = 1 if rng.random() < 0.5 else -1
    proposed = round(p + direction * step_size, 4)

    if p_floor <= proposed <= p_ceil:
        return (round(proposed, 4), False)

    if boundary_mode == "reject-step":
        return (round(p, 4), False)

    if boundary_mode == "reject-walk":
        return (round(p, 4), True)

    if proposed < p_floor:
        reflected = p_floor + (p_floor - proposed)
    else:
        reflected = p_ceil - (proposed - p_ceil)

    reflected = max(p_floor, min(p_ceil, reflected))
    return (round(reflected, 4), False)


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _bandit_meta(p_left: List[float], p_right: List[float]) -> Dict:
    return {
        "balance_metric": "between_arm_session_mean_abs_diff",
        "between_arm_session_mean_abs_diff": abs(_mean(p_left) - _mean(p_right)),
        "transition_rule": "step_prob is the TOTAL per-arm-per-trial probability of a +/- step; direction 50/50",
    }


def longest_double_low_run(p_left, p_right, thresh) -> int:
    longest = 0
    current = 0

    for left, right in zip(p_left, p_right):
        if left < thresh and right < thresh:
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0

    return longest


def validate_bandit_walk(w) -> None:
    assert len(w.p_left) == w.n_trials
    assert len(w.p_right) == w.n_trials

    if w.balance_tol >= 0:
        mean_diff = abs(_mean(w.p_left) - _mean(w.p_right))
        assert mean_diff <= w.balance_tol + 1e-9

    for p in w.p_left:
        assert w.p_floor - 1e-9 <= p <= w.p_ceil + 1e-9
    for p in w.p_right:
        assert w.p_floor - 1e-9 <= p <= w.p_ceil + 1e-9

    assert longest_double_low_run(w.p_left, w.p_right, w.double_low_thresh) <= w.double_low_max_run
