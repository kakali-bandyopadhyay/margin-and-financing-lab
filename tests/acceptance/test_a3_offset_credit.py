"""A3: offset credit in a partly hedged family, before add-on and buffer."""

import pytest

from mfl.margin import family_margin


def test_a3_partly_hedged_family_matches_offset_credit_identity():
    # Long 10m and short 4m in the same family: gross=14m, net=6m.
    rate = 0.27
    phi = 0.60
    gross = 14_000_000.0
    net = abs(10_000_000.0 - 4_000_000.0)

    actual = family_margin(rate, phi, gross, net)
    expected_from_identity = rate * gross - phi * (gross - net) * rate
    expected_from_definition = rate * (phi * net + (1.0 - phi) * gross)

    assert expected_from_identity == pytest.approx(2_484_000.0, abs=1e-9)
    assert expected_from_definition == pytest.approx(expected_from_identity, abs=1e-9)
    assert actual == pytest.approx(expected_from_identity, abs=1e-9)
