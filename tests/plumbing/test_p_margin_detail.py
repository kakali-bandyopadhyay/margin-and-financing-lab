from __future__ import annotations

import numpy as np

from mfl.io import load_case
from mfl.margin import margin_by_pb, margin_detail
from mfl.optimise import optimise


def _assert_detail_matches(case, weights):
    family, issuer = margin_detail(case.book, weights, case.rates, case.providers, case.params)
    detail = family.groupby("pb_id")["margin_usd"].sum().add(
        issuer.groupby("pb_id")["addon_usd"].sum(), fill_value=0.0
    ) * case.params["house_buffer"]
    direct = margin_by_pb(case.book, weights, case.rates, case.providers, case.params).set_index("pb_id")["margin_usd"]
    np.testing.assert_allclose(detail.reindex(direct.index), direct, atol=1e-6 * max(1.0, float(direct.sum())), rtol=0.0)


def test_p4_margin_detail_equals_margin_by_pb(data_raw):
    case = load_case(data_raw)
    rng = np.random.default_rng(42)
    for _ in range(5):
        weights = rng.dirichlet(np.ones(len(case.providers)), size=len(case.book))
        _assert_detail_matches(case, weights)
    result = optimise(case.book, case.rates, case.providers, case.borrow, case.params)
    assert result.status == "optimal"
    _assert_detail_matches(case, result.w)
