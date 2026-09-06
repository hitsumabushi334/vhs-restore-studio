from pathlib import Path

import pytest

from vhs_restore.analysis.interlace import InterlaceAnalysis
from vhs_restore.analysis.source_info import SourceInfo
from vhs_restore.pipeline.deinterlace import decide_deinterlace
from vhs_restore.settings import RestoreSettings


def _source(*, classification: str, frame_rate: float, field_order: str | None = None) -> SourceInfo:
    return SourceInfo(
        path=Path("日本語 capture (raw) [01].avi"),
        width=720,
        height=480,
        frame_rate=frame_rate,
        field_order=field_order,
        interlace=InterlaceAnalysis(classification, confidence=1.0),
    )


@pytest.mark.parametrize("field_order", ["TFF", "BFF"])
def test_2997i_field_order_uses_qtgmc_double_rate_when_available(field_order: str):
    analysis = _source(
        classification=field_order,
        field_order=field_order,
        frame_rate=30000 / 1001,
    )

    decision = decide_deinterlace(
        analysis,
        RestoreSettings(qtgmc_preset="balanced"),
        qtgmc_available=True,
    )

    assert decision.enabled is True
    assert decision.method == "qtgmc"
    assert decision.field_order == field_order
    assert decision.double_rate is True
    assert decision.output_frame_rate == pytest.approx(60000 / 1001)
    assert decision.filter_expression is None
    assert decision.qtgmc_script is not None
    assert "havsfunc.QTGMC" in decision.qtgmc_script
    assert "FPSDivisor=1" in decision.qtgmc_script
    assert f"TFF={field_order == 'TFF'}" in decision.qtgmc_script


def test_clean_5994p_progressive_source_disables_deinterlace():
    analysis = _source(
        classification="Progressive",
        frame_rate=60000 / 1001,
        field_order="Progressive",
    )

    decision = decide_deinterlace(
        analysis,
        RestoreSettings(),
        qtgmc_available=True,
    )

    assert decision.enabled is False
    assert decision.method == "off"
    assert decision.double_rate is False
    assert decision.output_frame_rate == pytest.approx(60000 / 1001)
    assert decision.filter_expression is None
    assert decision.qtgmc_script is None

def test_mixed_5994p_source_stays_progressive_in_auto_mode():
    analysis = _source(
        classification="Mixed",
        frame_rate=60000 / 1001,
    )

    decision = decide_deinterlace(
        analysis,
        RestoreSettings(),
        qtgmc_available=True,
    )

    assert decision.enabled is False
    assert decision.method == "off"
    assert decision.double_rate is False
    assert decision.output_frame_rate == pytest.approx(60000 / 1001)
    assert "already-progressive" in decision.reason
    assert "59.94p" in decision.reason


def test_forced_tff_still_deinterlaces_5994p_source():
    analysis = _source(
        classification="Mixed",
        frame_rate=60000 / 1001,
    )

    decision = decide_deinterlace(
        analysis,
        RestoreSettings(deinterlace="tff"),
        qtgmc_available=True,
    )

    assert decision.enabled is True
    assert decision.method == "qtgmc"
    assert decision.field_order == "TFF"
    assert decision.double_rate is True
    assert decision.output_frame_rate == pytest.approx(120000 / 1001)

def test_interlaced_source_uses_bwdif_double_rate_when_qtgmc_is_unavailable():
    analysis = _source(
        classification="TFF",
        field_order="TFF",
        frame_rate=30000 / 1001,
    )

    decision = decide_deinterlace(
        analysis,
        RestoreSettings(),
        qtgmc_available=False,
    )

    assert decision.enabled is True
    assert decision.method == "bwdif"
    assert decision.double_rate is True
    assert decision.filter_expression == "bwdif=mode=send_field:parity=tff:deint=all"
    assert decision.qtgmc_script is None
    assert decision.warning is not None
    assert "QTGMC unavailable" in decision.warning

