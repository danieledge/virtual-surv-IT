"""
Tests for the statistical synthesiser (scripts/synthesise.py). All data is synthetic (§5).
"""

from __future__ import annotations

from scripts.gen_synthetic import benign_session, spoofing_session
from scripts.synthesise import detection_rate, fit, sample


def _corpus():
    # 3 spoofing + 3 benign sessions => a known spoof rate of 0.5.
    return [spoofing_session(seed=s) if s % 2 == 0 else benign_session(seed=s) for s in range(6)]


def test_fit_learns_a_plausible_spoof_rate():
    profile = fit(_corpus())
    assert profile.spoof_rate == 0.5
    assert profile.spoof_multiple >= 5.0  # outsized, as the rule requires
    assert profile.qty_values  # learned a size distribution


def test_sampled_data_carries_the_signal():
    """Synthetic sessions must still trigger the detector (utility preserved)."""
    profile = fit(_corpus())
    synthetic = sample(profile, n_sessions=40, seed=1)
    rate = detection_rate(synthetic)
    assert 0.3 <= rate <= 0.7  # near the learned 0.5, within sampling noise


def test_synthetic_shares_no_real_entities():
    """Privacy: synthetic data reuses no identifier from the input corpus."""
    corpus = _corpus()
    input_traders = {e.trader for s in corpus for e in s}
    input_orders = {e.order_id for s in corpus for e in s}
    synthetic = sample(fit(corpus), n_sessions=20, seed=2)
    syn_traders = {e.trader for s in synthetic for e in s}
    syn_orders = {e.order_id for s in synthetic for e in s}
    assert input_traders.isdisjoint(syn_traders)
    assert input_orders.isdisjoint(syn_orders)


def test_sampling_is_deterministic():
    profile = fit(_corpus())
    a = sample(profile, n_sessions=5, seed=7)
    b = sample(profile, n_sessions=5, seed=7)
    assert [e.__dict__ for s in a for e in s] == [e.__dict__ for s in b for e in s]
