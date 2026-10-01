"""
Performance baseline — Day 23.
Tests matching engine only (no DB, no network).
Seed is fixed for reproducibility.
"""
from __future__ import annotations
import random
import time
import pytest

SEED = 42


def _gstin(rng: random.Random) -> str:
    state = str(rng.randint(10, 35))
    pan = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))
    num = "".join(rng.choices("0123456789", k=4))
    chk = rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f"{state}{pan}{num}1Z{chk}"


def make_data(gstr_n: int, pr_match_rate: float, seed: int = SEED):
    rng = random.Random(seed)
    gstin_pool = [_gstin(rng) for _ in range(max(10, gstr_n // 10))]
    weights = [6 if i < len(gstin_pool) // 10 else 1 for i in range(len(gstin_pool))]
    gstr = []
    for i in range(gstr_n):
        gstin = rng.choices(gstin_pool, weights=weights)[0]
        amount = round(rng.uniform(1000, 500000), 2)
        gstr.append({
            "id": f"gstr-{i}",
            "supplier_gstin": gstin,
            "invoice_number": f"INV-{i:05d}",
            "invoice_number_normalized": f"INV{i:05d}",
            "invoice_date": "2024-01-15",
            "taxable_amount": amount,
            "igst": round(amount * 0.18, 2),
            "cgst": 0.0,
            "sgst": 0.0,
            "total_tax": round(amount * 0.18, 2),
            "period": "2024-01",
        })
    matched_pool = rng.sample(gstr, int(gstr_n * pr_match_rate))
    pr = []
    for i, g in enumerate(matched_pool):
        amount = g["taxable_amount"] if rng.random() > 0.05 else round(g["taxable_amount"] * 1.01, 2)
        pr.append({
            "id": f"pr-{i}",
            "supplier_gstin": g["supplier_gstin"],
            "invoice_number": g["invoice_number"],
            "invoice_number_normalized": g["invoice_number_normalized"],
            "invoice_date": g["invoice_date"],
            "taxable_amount": amount,
            "igst": round(amount * 0.18, 2),
            "cgst": 0.0,
            "sgst": 0.0,
            "total_tax": round(amount * 0.18, 2),
            "period": g["period"],
        })
    return gstr, pr


@pytest.mark.parametrize("scale", [100, 500, 1000])
def test_matching_baseline(scale: int):
    """Measure matching engine at different scales. Seed=42 for reproducibility."""
    from app.services.matcher import match_gstr_to_pr
    gstr, pr = make_data(scale, pr_match_rate=0.95)
    print(f"\n[BASELINE] scale={scale} gstr={len(gstr)} pr={len(pr)} seed={SEED}")
    start = time.perf_counter()
    results = [match_gstr_to_pr(g, pr) for g in gstr]
    elapsed = time.perf_counter() - start
    matched = sum(1 for r in results if r is not None)
    print(f"[BASELINE] scale={scale} elapsed={elapsed:.3f}s matched={matched}/{scale}")
    assert elapsed < 240, f"Too slow at scale={scale}: {elapsed:.2f}s"
