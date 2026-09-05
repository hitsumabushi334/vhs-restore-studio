import math

import pytest

from vhs_restore.pipeline.dvd import plan_dvd_video_bitrate


@pytest.mark.parametrize(
    ("disc", "expected_bps"),
    [("DVD-5", 4_400_000), ("DVD-9", 8_100_000)],
)
def test_dvd_bitrate_reserves_overhead_safety_margin_and_ac3_audio(
    disc: str,
    expected_bps: int,
):
    assert plan_dvd_video_bitrate(7200.0, disc) == expected_bps


def test_dvd9_has_more_video_budget_than_dvd5_for_same_duration():
    dvd5 = plan_dvd_video_bitrate(7200.0, "DVD-5")
    dvd9 = plan_dvd_video_bitrate(7200.0, "DVD-9")

    assert dvd9 > dvd5


def test_longer_titles_get_a_lower_bitrate():
    assert plan_dvd_video_bitrate(7200.0) > plan_dvd_video_bitrate(10800.0)


def test_short_titles_are_capped_below_dvd_video_maximum():
    assert plan_dvd_video_bitrate(60.0, "DVD-5") == 9_000_000


@pytest.mark.parametrize("duration_s", [0, -1, math.inf, math.nan])
def test_dvd_bitrate_rejects_non_positive_or_non_finite_duration(duration_s: float):
    with pytest.raises(ValueError, match="duration"):
        plan_dvd_video_bitrate(duration_s)


def test_dvd_bitrate_rejects_unknown_disc_capacity():
    with pytest.raises(ValueError, match="disc"):
        plan_dvd_video_bitrate(7200.0, "DVD-10")


def test_dvd_bitrate_rejects_titles_that_cannot_fit_the_minimum_video_rate():
    with pytest.raises(ValueError, match="long"):
        plan_dvd_video_bitrate(100000.0)
