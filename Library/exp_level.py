from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal


# Keep these constants identical between Discord bot and FastAPI.
LEVEL_C0 = 1000
LEVEL_N0 = 30
LEVEL_ALPHA = 0.35
LEVEL_GLOBAL_C0_MULTIPLIER = 1.4
LEVEL_GLOBAL_C0 = int(round(LEVEL_C0 * LEVEL_GLOBAL_C0_MULTIPLIER))
LevelCurveProfile = Literal["server", "global"]


@dataclass(frozen=True)
class LevelProgress:
    level: int
    exp: int
    exp_at_level: int
    exp_to_next: int
    into_level: int
    level_span: int
    ratio: float


def _normalize_exp(exp: int | None) -> int:
    if exp is None:
        return 0
    return max(0, int(exp))


def _normalize_profile(profile: LevelCurveProfile | str | None) -> LevelCurveProfile:
    if profile is None:
        return "server"
    value = str(profile).strip().lower()
    if value == "server":
        return "server"
    if value == "global":
        return "global"
    raise ValueError(f"Unknown level curve profile: {profile}")


def _curve_c0(profile: LevelCurveProfile) -> int:
    if profile == "global":
        return LEVEL_GLOBAL_C0
    return LEVEL_C0


def level_cost(n: int, *, profile: LevelCurveProfile | str = "server") -> int:
    """
    Return EXP cost from level n+1 to n+2 where n is 0-based.

    cost(n) = C0(profile) * (1 + (n / N0) ** alpha)
    Rounding policy must stay stable across all services.
    """
    idx = max(0, int(n))
    curve = _normalize_profile(profile)
    raw = _curve_c0(curve) * (1.0 + (idx / LEVEL_N0) ** LEVEL_ALPHA)
    return max(1, int(round(raw)))


@lru_cache(maxsize=None)
def exp_for_level(level: int, *, profile: LevelCurveProfile | str = "server") -> int:
    """
    Return EXP threshold for the given 1-based level.

    Examples:
    - level 1 -> 0
    - level 2 -> level_cost(0, profile="server")
    - exp_for_level(2, profile="server") == level_cost(0, profile="server")
    """
    lv = int(level)
    if lv <= 1:
        return 0
    curve = _normalize_profile(profile)
    return sum(level_cost(i, profile=curve) for i in range(lv - 1))


def level_from_exp(exp: int | None, *, profile: LevelCurveProfile | str = "server") -> int:
    exp_value = _normalize_exp(exp)
    if exp_value <= 0:
        return 1

    curve = _normalize_profile(profile)
    hi = 2
    while exp_for_level(hi, profile=curve) <= exp_value:
        hi *= 2
    lo = hi // 2

    while lo < hi:
        mid = (lo + hi + 1) // 2
        if exp_for_level(mid, profile=curve) <= exp_value:
            lo = mid
        else:
            hi = mid - 1
    return max(1, lo)


def level_progress(exp: int | None, *, profile: LevelCurveProfile | str = "server") -> LevelProgress:
    """
    Derive level/progress from EXP only.

    FastAPI integration note:
    Use this module as-is (or copy exactly) and keep LEVEL_C0, LEVEL_N0,
    LEVEL_ALPHA, LEVEL_GLOBAL_C0_MULTIPLIER and the rounding policy in
    level_cost() synchronized across all services to prevent mismatch between
    Discord and web displays.

    Sanity examples:
    - level_from_exp(0, profile="server") == 1
    - exp_for_level(2, profile="server") == level_cost(0, profile="server")
    - For any exp/profile, into_level + exp_to_next == exp_for_level(level+1, profile) - exp_for_level(level, profile)
    """
    exp_value = _normalize_exp(exp)
    curve = _normalize_profile(profile)
    level = level_from_exp(exp_value, profile=curve)
    exp_at_level = exp_for_level(level, profile=curve)
    exp_at_next = exp_for_level(level + 1, profile=curve)
    into_level = max(0, exp_value - exp_at_level)
    exp_to_next = max(0, exp_at_next - exp_value)
    level_span = max(1, exp_at_next - exp_at_level)
    ratio = min(1.0, max(0.0, into_level / level_span))
    return LevelProgress(
        level=level,
        exp=exp_value,
        exp_at_level=exp_at_level,
        exp_to_next=exp_to_next,
        into_level=into_level,
        level_span=level_span,
        ratio=ratio,
    )

