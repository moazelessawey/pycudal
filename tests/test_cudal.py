"""
Quick sanity checks (not a full validation against SAS output -- that
would require running the original SAS code side by side -- but these
confirm every function runs, returns probabilities in [0, 1], and shows
the expected qualitative behaviour (e.g. tighter variability => higher
pass probability; boundary tables are widest near the target/Q value).
"""
import numpy as np
from cudal import cusp1, cusp2, disp1, disp2
from cudal.core import content_uniformity_bound, dissolution_bound


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
    tab = cusp1.acceptance_limit_table(number=10, target=100, lbound=95, cilevel=95,
                                        mean_low=95, mean_high=105, mean_step=1.0)
    assert (tab["CV"] >= 0).all()
    peak_row = tab.loc[tab["CV"].idxmax()]
    assert 98 <= peak_row["MEAN"] <= 102, "CV boundary should peak near the target"

    r = cusp1.sample_probability(mean=100, cv=1.0, number=10, target=100, lbound=95, cilevel=95)
    check_prob_range("cusp1 sample", r["OVERBD"])


def test_cusp2():
    tab = cusp2.acceptance_limit_table(num=6, loc=10, target=100, lbound=95, cilevel=95,
                                        se_values=[1, 2], sm_values=[1, 2])
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
    tab = disp2.acceptance_limit_table(num=6, loc=5, q=80, lbound=95, cilevel=95,
                                        se_values=[2, 3], sm_values=[2, 3])
    assert tab["MEAN"].notna().any()

    r = disp2.sample_probability(mean=90, se=2.2, sm=2.46, num=6, loc=5, q=80, cilevel=95)
    check_prob_range("disp2 sample", r["OVERBD"])


if __name__ == "__main__":
    test_core()
    test_cusp1()
    test_cusp2()
    test_disp1()
    test_disp2()
    print("All sanity checks passed.")
