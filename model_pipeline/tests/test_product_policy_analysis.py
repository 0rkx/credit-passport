from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_product_policies import CANDIDATES, PRODUCT_ORDER, SELECTED_CANDIDATE, run  # noqa: E402


def test_selected_product_policy_sensitivity_is_reproducible_and_separated() -> None:
    first = run()
    second = run()
    assert first == second
    assert first["selected_candidate"] == SELECTED_CANDIDATE

    selected = first["candidates"][SELECTED_CANDIDATE]
    previous = first["candidates"]["v1"]
    assert CANDIDATES[SELECTED_CANDIDATE]["credit-card"] == [35, 10, 15, 25, 5, 5, 5]
    assert all(selected["products"][product]["n"] == 12_000 for product in PRODUCT_ORDER)
    assert all(selected["monotonicity_rate"][product] == 1.0 for product in PRODUCT_ORDER)
    assert (
        selected["pairwise"]["personal-loan_vs_credit-card"]["integer_difference_rate"]
        > previous["pairwise"]["personal-loan_vs_credit-card"]["integer_difference_rate"]
    )
