"""Tests for ``scripts/bench_vendor_compare.py``.

In-memory only — no live Gemini / Serper calls. The bench itself is the
integration test for those vendors; these tests cover only the runner's
helpers (``validate``, ``apple_variant_check``, ``percentile``,
``warm_rows``, ``recall_stats``) so a regression in the math doesn't
silently corrupt a head-to-head decision.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "bench_vendor_compare.py"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Stub a SERPER_API_KEY so the script's _bench_serper import doesn't crash
# downstream consumers — the tests never instantiate SerperClient.
os.environ.setdefault("SERPER_API_KEY", "test-key-for-imports")
# Ensure scripts/ is on sys.path so _bench_serper is importable.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "bench_vendor_compare", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_vendor_compare"] = module
    spec.loader.exec_module(module)
    return module


bvc = _load_module()


# MARK: - validate()


def test_validate_matches_expected_brand_and_token():
    case = {
        "difficulty": "flagship",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
    }
    result = {"device_name": "Apple AirPods Pro 2nd Gen USB-C", "model": None}
    assert bvc.validate(result, case) is True


def test_validate_null_device_name_returns_false_for_non_invalid():
    case = {
        "difficulty": "flagship",
        "expected_brand": "Apple",
        "expected_name_contains": ["iPhone"],
    }
    assert bvc.validate({"device_name": None}, case) is False
    assert bvc.validate({"device_name": ""}, case) is False


def test_validate_invalid_difficulty_treats_null_as_pass():
    case = {
        "difficulty": "invalid",
        "expected_brand": "(invalid)",
        "expected_name_contains": [],
    }
    assert bvc.validate({"device_name": None}, case) is True
    # And a non-null result on an invalid case should fail (we want graceful
    # rejection of pattern UPCs, not hallucinated products).
    assert bvc.validate({"device_name": "Sony WH-1000XM5"}, case) is False


def test_validate_apple_rule_2c_rejects_chip_disagreement():
    case = {
        "difficulty": "flagship",
        "expected_brand": "Apple",
        "expected_name_contains": ["MacBook Air"],
        "expected_chip": "M4",
    }
    # M3 result for M4 case → Rule 2c rejects
    result_wrong_chip = {
        "device_name": "Apple MacBook Air 13",
        "model": None,
        "chip": "M3",
    }
    assert bvc.validate(result_wrong_chip, case) is False
    # Same metadata but with M4 → passes
    result_right_chip = {
        "device_name": "Apple MacBook Air 13",
        "model": None,
        "chip": "M4",
    }
    assert bvc.validate(result_right_chip, case) is True


def test_validate_apple_rule_2d_rejects_display_size_disagreement():
    case = {
        "difficulty": "flagship",
        "expected_brand": "Apple",
        "expected_name_contains": ["iPad Pro"],
        "expected_display_size_in": 13,
    }
    # 11" result for 13" case → Rule 2d rejects
    result_wrong_size = {
        "device_name": "Apple iPad Pro",
        "model": None,
        "display_size_in": 11,
    }
    assert bvc.validate(result_wrong_size, case) is False
    # Same metadata but with 13" → passes
    result_right_size = {
        "device_name": "Apple iPad Pro",
        "model": None,
        "display_size_in": 13,
    }
    assert bvc.validate(result_right_size, case) is True


def test_validate_apple_rule_2c_allows_chip_omission():
    """Disagreement-only — null chip on either side passes (used sellers
    routinely omit it from listings; production Rule 2c does the same)."""
    case = {
        "difficulty": "flagship",
        "expected_brand": "Apple",
        "expected_name_contains": ["MacBook Air"],
        "expected_chip": "M4",
    }
    # Result emits no chip → passes (omission, not disagreement)
    result_no_chip = {
        "device_name": "Apple MacBook Air 13",
        "model": None,
        "chip": None,
    }
    assert bvc.validate(result_no_chip, case) is True
    # Empty string also counts as omission
    result_empty_chip = {
        "device_name": "Apple MacBook Air 13",
        "model": None,
        "chip": "",
    }
    assert bvc.validate(result_empty_chip, case) is True


# MARK: - apple_variant_check telemetry column


def test_apple_variant_check_returns_rule_id_on_disagreement():
    case = {
        "expected_chip": "M4",
        "expected_display_size_in": 13,
    }
    assert bvc.apple_variant_check({"chip": "M3", "display_size_in": 13}, case) == "rule_2c"
    assert bvc.apple_variant_check({"chip": "M4", "display_size_in": 11}, case) == "rule_2d"
    assert bvc.apple_variant_check({"chip": "M4", "display_size_in": 13}, case) is None
    # Omission on either side → None
    assert bvc.apple_variant_check({"chip": None, "display_size_in": None}, case) is None


# MARK: - percentile / warm_rows / recall_stats


def test_summary_excludes_cold_runs_from_percentiles():
    """warm_rows must drop run==1 (is_cold=true) so cold-start latency
    doesn't pollute p50/p90/p99."""
    rows = [
        {"config": "X", "is_cold": True,  "total_latency_ms": 99999, "error": None,
         "difficulty": "flagship", "matches_expected": True, "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "total_latency_ms": 100,   "error": None,
         "difficulty": "flagship", "matches_expected": True, "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "total_latency_ms": 200,   "error": None,
         "difficulty": "flagship", "matches_expected": True, "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "total_latency_ms": 300,   "error": None,
         "difficulty": "flagship", "matches_expected": True, "apple_variant_rejected": None},
    ]
    warm = bvc.warm_rows(rows, "X")
    assert len(warm) == 3
    latencies = [r["total_latency_ms"] for r in warm]
    # p50 should be 200, NOT 99999 (cold excluded)
    assert bvc.percentile(latencies, 50) == 200
    assert 99999 not in latencies


def test_summary_excludes_invalid_upcs_from_recall():
    """recall_stats(exclude_invalid=True) must drop the invalid UPCs from
    both numerator and denominator. Otherwise the invalid bucket would
    inflate any config that returns null (the whole point of the bucket)."""
    rows = [
        {"config": "X", "is_cold": False, "difficulty": "flagship",
         "matches_expected": True, "total_latency_ms": 0, "error": None,
         "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "difficulty": "flagship",
         "matches_expected": False, "total_latency_ms": 0, "error": None,
         "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "difficulty": "invalid",
         "matches_expected": True, "total_latency_ms": 0, "error": None,
         "apple_variant_rejected": None},
        {"config": "X", "is_cold": False, "difficulty": "invalid",
         "matches_expected": True, "total_latency_ms": 0, "error": None,
         "apple_variant_rejected": None},
    ]
    warm = bvc.warm_rows(rows, "X")
    hits, total = bvc.recall_stats(warm, exclude_invalid=True)
    # Should be 1/2 (one flagship hit, one flagship miss; both invalid dropped)
    assert hits == 1
    assert total == 2
