import pytest

from backend.plugin.rider_salary.engine.ladder import ladder

TIERS = [[0, 300, 5], [300, 600, 5.5], [600, None, 6]]
DISTANCE_TIERS = [[0, 3, 0], [3, 5, 1], [5, 8, 2], [8, None, 4]]
WEIGHT_TIERS = [[0, 10, 0], [10, 20, 1], [20, None, 3]]


def test_full_band_unit_price() -> None:
    assert ladder(420, '全量落档', '按单价', TIERS) == pytest.approx(420 * 5.5)
    assert ladder(299, '全量落档', '按单价', TIERS) == pytest.approx(299 * 5)
    assert ladder(300, '全量落档', '按单价', TIERS) == pytest.approx(300 * 5.5)
    assert ladder(599, '全量落档', '按单价', TIERS) == pytest.approx(599 * 5.5)
    assert ladder(600, '全量落档', '按单价', TIERS) == pytest.approx(600 * 6)
    assert ladder(700, '全量落档', '按单价', TIERS) == pytest.approx(700 * 6)
    assert ladder(0, '全量落档', '按单价', TIERS) == pytest.approx(0)


def test_progressive_unit_price() -> None:
    assert ladder(420, '分段累进', '按单价', TIERS) == pytest.approx(300 * 5 + 120 * 5.5)
    assert ladder(300, '分段累进', '按单价', TIERS) == pytest.approx(1500)
    assert ladder(299, '分段累进', '按单价', TIERS) == pytest.approx(299 * 5)
    assert ladder(600, '分段累进', '按单价', TIERS) == pytest.approx(300 * 5 + 300 * 5.5)
    assert ladder(700, '分段累进', '按单价', TIERS) == pytest.approx(300 * 5 + 300 * 5.5 + 100 * 6)
    assert ladder(0, '分段累进', '按单价', TIERS) == pytest.approx(0)


def test_full_band_fixed_amount() -> None:
    assert ladder(7.2, '全量落档', '固定金额', DISTANCE_TIERS) == pytest.approx(2)
    assert ladder(3, '全量落档', '固定金额', DISTANCE_TIERS) == pytest.approx(1)
    assert ladder(2.9, '全量落档', '固定金额', DISTANCE_TIERS) == pytest.approx(0)
    assert ladder(8, '全量落档', '固定金额', DISTANCE_TIERS) == pytest.approx(4)
    assert ladder(12, '全量落档', '固定金额', WEIGHT_TIERS) == pytest.approx(1)
    assert ladder(25, '全量落档', '固定金额', WEIGHT_TIERS) == pytest.approx(3)
    assert ladder(10, '全量落档', '固定金额', WEIGHT_TIERS) == pytest.approx(1)


def test_progressive_fixed_forbidden() -> None:
    try:
        ladder(100, '分段累进', '固定金额', TIERS)
        raise AssertionError('应当禁止分段累进+固定金额')
    except ValueError as exc:
        assert '分段累进模式仅支持按单价计价' in str(exc)
