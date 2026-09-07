"""
Quick sanity checks (not a full validation against SAS output -- that
would require running the original SAS code side by side -- but these
confirm every function runs, returns probabilities in [0, 1], and shows
the expected qualitative behaviour (e.g. tighter variability => higher
pass probability; boundary tables are widest near the target/Q value).

Sanity checks for the new extdisp1 / extdisp2 / deldisp1 / deldisp2
modules (USP <711> Extended-Release and Delayed-Release Dissolution).

These are new derivations (not translations of an original SAS macro), so
there is no legacy reference output to diff against. These checks instead
confirm: probabilities stay in [0, 1]; acceptance boundaries behave with
the expected qualitative shape (symmetric bump for the two-sided
Extended-Release criterion; monotonic single boundary for the one-sided
Delayed-Release Buffer Stage); and sample_probability agrees qualitatively
with the corresponding acceptance-limit table.
"""

import math

from cudal import cusp1, cusp2, disp1, disp2
from cudal import deldisp1, deldisp2, extdisp1, extdisp2
from cudal.core import content_uniformity_bound, dissolution_bound
from cudal.core import acid_stage_bound, delayed_release_bound, extended_release_bound


def check_prob_range(name, value):
    assert -1e-9 <= value <= 1 + 1e-9, f"{name} out of [0,1]: {value}"


def test_core():
    p1 = content_uniformity_bound(100, 1.0, 100)
    p2 = content_uniformity_bound(100, 10.0, 100)
    check_prob_range("CU tight", p1)
    check_prob_range("CU loose", p2)
    assert p1 > p2, "tighter SD should have a higher pass probability"

    d1 = dissolution_bound(20, 2.0)
    d2 = dissolution_bound(20, 15.0)
    check_prob_range("Diss tight", d1)
    check_prob_range("Diss loose", d2)
    assert d1 > d2


def test_cusp1():
    tab = cusp1.acceptance_limit_table(
        number=10, target=100, lbound=95, cilevel=95, mean_low=95, mean_high=105, mean_step=1.0
    )
    assert (tab["CV"] >= 0).all()
    peak_row = tab.loc[tab["CV"].idxmax()]
    assert 98 <= peak_row["MEAN"] <= 102, "CV boundary should peak near the target"

    r = cusp1.sample_probability(mean=100, cv=1.0, number=10, target=100, lbound=95, cilevel=95)
    check_prob_range("cusp1 sample", r["OVERBD"])


def test_cusp2():
    tab = cusp2.acceptance_limit_table(
        num=6, loc=10, target=100, lbound=95, cilevel=95, se_values=[1, 2], sm_values=[1, 2]
    )
    ok = tab.dropna()
    assert (ok["MEANU"] > ok["MEANL"]).all()

    r = cusp2.sample_probability(mean=100, se=2.2, sm=2.46, num=6, loc=10, target=100, cilevel=95)
    check_prob_range("cusp2 sample", r["OVERBD"])


def test_disp1():
    tab = disp1.acceptance_limit_table(number=6, q=80, lbound=95, cilevel=95, meanadj_step=2.0)
    assert (tab["CV"] >= 0).all()
    assert tab["CV"].iloc[-1] > tab["CV"].iloc[0], "CV bound should grow further above Q"

    r = disp1.sample_probability(mean=90, cv=2.0, number=6, q=80, cilevel=95)
    check_prob_range("disp1 sample", r["OVERBD"])


def test_disp2():
    tab = disp2.acceptance_limit_table(
        num=6, loc=5, q=80, lbound=95, cilevel=95, se_values=[2, 3], sm_values=[2, 3]
    )
    assert tab["MEAN"].notna().any()

    r = disp2.sample_probability(mean=90, se=2.2, sm=2.46, num=6, loc=5, q=80, cilevel=95)
    check_prob_range("disp2 sample", r["OVERBD"])


def check_prob_range(name, value):
    assert -1e-9 <= value <= 1 + 1e-9, f"{name} out of [0,1]: {value}"


def test_core_extended_release_bound():
    centered = extended_release_bound(50, 1.0, 45, 55)
    off_range = extended_release_bound(70, 1.0, 45, 55)
    loose = extended_release_bound(50, 10.0, 45, 55)
    check_prob_range("ext centered", centered)
    check_prob_range("ext off-range", off_range)
    check_prob_range("ext loose", loose)
    assert centered > loose > off_range


def test_core_acid_stage_bound():
    low = acid_stage_bound(2, 1.0)  # barely dissolves in acid -> good
    high = acid_stage_bound(20, 1.0)  # dissolves too much in acid -> bad
    check_prob_range("acid low", low)
    check_prob_range("acid high", high)
    assert low > high


def test_core_delayed_release_bound():
    good = delayed_release_bound(2, 1.0, 90, 3.0)
    bad_acid = delayed_release_bound(30, 1.0, 90, 3.0)
    check_prob_range("delayed good", good)
    check_prob_range("delayed bad-acid", bad_acid)
    assert good > bad_acid
    # A badly failing acid stage must cap the combined result low,
    # regardless of how good the buffer stage is.
    assert bad_acid < 0.05


def test_extdisp1_acceptance_table_symmetric_bump():
    tab = extdisp1.acceptance_limit_table(
        number=6,
        ql=45,
        qu=55,
        lbound=95,
        cilevel=95,
        mean_low=45,
        mean_high=55,
        mean_step=1.0,
    )
    assert (tab["CV"] >= 0).all()
    peak_row = tab.loc[tab["CV"].idxmax()]
    assert abs(peak_row["MEAN"] - 50.0) < 1e-6, "CV boundary should peak at the range midpoint"
    # boundary should vanish exactly at the range edges
    assert tab.loc[tab["MEAN"] == 45.0, "CV"].iloc[0] == 0.0
    assert tab.loc[tab["MEAN"] == 55.0, "CV"].iloc[0] == 0.0

    r = extdisp1.sample_probability(mean=50, cv=1.0, number=6, ql=45, qu=55, lbound=95, cilevel=95)
    check_prob_range("extdisp1 sample", r["OVERBD"])


def test_extdisp2_acceptance_table():
    tab = extdisp2.acceptance_limit_table(
        num=6,
        loc=10,
        ql=45,
        qu=55,
        lbound=95,
        cilevel=95,
        se_values=[0.2, 0.5],
        sm_values=[0.2, 0.5],
    )
    ok = tab.dropna()
    assert len(ok) > 0, "expected at least one feasible (SE, SM) combination"
    assert (ok["MEANU"] > ok["MEANL"]).all()
    # boundaries should widen (move toward 45/55) as variability shrinks
    row_tight = tab[(tab.SE == 0.2) & (tab.SM == 0.2)].iloc[0]
    row_loose = tab[(tab.SE == 0.5) & (tab.SM == 0.5)].iloc[0]
    assert row_tight["MEANL"] < row_loose["MEANL"]
    assert row_tight["MEANU"] > row_loose["MEANU"]

    r = extdisp2.sample_probability(
        mean=50, se=0.3, sm=0.3, num=6, loc=10, ql=45, qu=55, cilevel=95
    )
    check_prob_range("extdisp2 sample", r["OVERBD"])


def test_deldisp1_acceptance_table_monotonic():
    tab = deldisp1.acceptance_limit_table(
        number=6,
        mean_acid=3.0,
        cv_acid=20.0,
        q_buffer=75.0,
        lbound=95,
        cilevel=95,
        mean_low=80,
        mean_high=100,
        mean_step=5.0,
    )
    assert (tab["CV"] >= 0).all()
    assert tab["CV"].iloc[-1] > tab["CV"].iloc[0], "allowed CV should grow further above Q"

    r = deldisp1.sample_probability(
        mean_acid=3.0,
        cv_acid=20.0,
        mean_buffer=90.0,
        cv_buffer=5.0,
        number=6,
        q_buffer=75.0,
        cilevel=95,
    )
    check_prob_range("deldisp1 sample", r["OVERBD"])


def test_deldisp2_acceptance_table():
    tab = deldisp2.acceptance_limit_table(
        num=6,
        loc=5,
        mean_acid=3.0,
        cv_acid=20.0,
        number_acid=6,
        q_buffer=75.0,
        lbound=95,
        cilevel=95,
        se_values=[1, 2],
        sm_values=[1, 2],
    )
    assert tab["MEAN"].notna().any()

    r = deldisp2.sample_probability(
        mean_acid=3.0,
        cv_acid=20.0,
        number_acid=6,
        mean_buffer=90.0,
        se_buffer=2.0,
        sm_buffer=1.5,
        num=6,
        loc=5,
        q_buffer=75.0,
        cilevel=95,
    )
    check_prob_range("deldisp2 sample", r["OVERBD"])


def test_dissolution_bound_unchanged_after_refactor():
    """Regression guard: refactoring dissolution_bound to expose
    _dissolution_stage_probs must not change its public behavior."""
    from cudal.core import dissolution_bound

    assert math.isclose(dissolution_bound(20, 2.0), 1.0, abs_tol=1e-6)
    assert math.isclose(dissolution_bound(20, 15.0), 0.9670559072421239, rel_tol=1e-9)


if __name__ == "__main__":
    test_core()
    test_cusp1()
    test_cusp2()
    test_disp1()
    test_disp2()
    test_core_extended_release_bound()
    test_core_acid_stage_bound()
    test_core_delayed_release_bound()
    test_extdisp1_acceptance_table_symmetric_bump()
    test_extdisp2_acceptance_table()
    test_deldisp1_acceptance_table_monotonic()
    test_deldisp2_acceptance_table()
    test_dissolution_bound_unchanged_after_refactor()
    print("All sanity checks passed.")
