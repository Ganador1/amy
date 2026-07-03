#!/usr/bin/env python3
"""
Reproducibility Test for A.M.Y

Verifies that experiments produce consistent results across runs.
This is critical for scientific validity.
"""
import asyncio
import json
import hashlib
from pathlib import Path

from sandbox.executor import SandboxExecutor


# Standard reproducible experiment
REPRODUCIBLE_EXPERIMENT = '''
import numpy as np
from scipy import stats

# Fixed seed for reproducibility
np.random.seed(42)

# Generate sample data
data = np.random.normal(loc=5.0, scale=2.0, size=1000)

# Statistical tests
mean = np.mean(data)
std = np.std(data)
shapiro_stat, shapiro_p = stats.shapiro(data[:500])

# Print results with fixed precision
print(f"MEAN: {mean:.6f}")
print(f"STD: {std:.6f}")
print(f"SHAPIRO_W: {shapiro_stat:.6f}")
print(f"SHAPIRO_P: {shapiro_p:.6e}")
print(f"SKEWNESS: {stats.skew(data):.6f}")
print(f"KURTOSIS: {stats.kurtosis(data):.6f}")
'''


async def _run_reproducibility(n_runs: int = 3) -> dict:
    """Run the same experiment multiple times and verify identical results.

    Worker function (not collected by pytest — it takes a non-fixture arg).
    The collectable test is ``test_reproducibility`` below.
    """
    print("=" * 60)
    print("REPRODUCIBILITY TEST")
    print("=" * 60)
    print(f"Running experiment {n_runs} times with fixed seed...\n")

    executor = SandboxExecutor({"max_execution_time": 60})
    results = []

    for i in range(n_runs):
        print(f"Run {i + 1}/{n_runs}...")
        result = await executor.execute(REPRODUCIBLE_EXPERIMENT, language="python")

        if not result["success"]:
            print(f"  FAILED: {result['stderr'][:200]}")
            return {"success": False, "error": result["stderr"]}

        # Extract key metrics from stdout
        metrics = {}
        for line in result["stdout"].split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metrics[key.strip()] = value.strip()

        results.append(metrics)
        print(f"  Mean: {metrics.get('MEAN', 'N/A')}, Std: {metrics.get('STD', 'N/A')}")

    # Compare all runs
    print("\n" + "=" * 60)
    print("COMPARISON")
    print("=" * 60)

    all_match = True
    keys = list(results[0].keys())

    for key in keys:
        values = [r.get(key, "MISSING") for r in results]
        match = len(set(values)) == 1
        status = "✅ MATCH" if match else "❌ DIFFER"
        print(f"{key:15s}: {status}")
        if not match:
            all_match = False
            for i, v in enumerate(values):
                print(f"  Run {i+1}: {v}")

    # Compute hash of first result
    result_str = json.dumps(results[0], sort_keys=True)
    result_hash = hashlib.sha256(result_str.encode()).hexdigest()[:16]

    print(f"\nResult fingerprint: {result_hash}")

    if all_match:
        print("\n✅ REPRODUCIBILITY CONFIRMED")
        print("   All runs produced identical results.")
        return {"success": True, "hash": result_hash, "runs": n_runs}
    else:
        print("\n❌ REPRODUCIBILITY FAILED")
        print("   Results differ across runs!")
        return {"success": False, "runs": n_runs}


async def test_reproducibility():
    """Hermetic: the same fixed-seed experiment must produce identical output."""
    result = await _run_reproducibility(n_runs=3)
    assert result["success"], f"experiment was not reproducible across runs: {result}"


async def test_syntax_validation() -> dict:
    """Test that syntax errors are caught before execution."""
    print("\n" + "=" * 60)
    print("SYNTAX VALIDATION TEST")
    print("=" * 60)

    executor = SandboxExecutor({})

    # Test 1: Valid code
    valid_code = "print('hello')"
    result = await executor.execute(valid_code, language="python")
    test1 = result["success"]
    print(f"Valid code: {'✅ PASS' if test1 else '❌ FAIL'}")

    # Test 2: Invalid syntax (unterminated string)
    invalid_code = 'print("hello'
    result = await executor.execute(invalid_code, language="python")
    test2 = not result["success"] and "Syntax error" in result["stderr"]
    print(f"Invalid syntax caught: {'✅ PASS' if test2 else '❌ FAIL'}")
    if not result["success"]:
        print(f"  Error: {result['stderr'][:100]}")

    # Test 3: Missing parenthesis
    invalid_code2 = "print('hello'"
    result = await executor.execute(invalid_code2, language="python")
    test3 = not result["success"] and "Syntax error" in result["stderr"]
    print(f"Missing paren caught: {'✅ PASS' if test3 else '❌ FAIL'}")

    all_pass = test1 and test2 and test3
    assert all_pass, f"syntax validation failed: valid={test1} invalid={test2} missing_paren={test3}"
    return {"success": all_pass}


async def main():
    """Run all reproducibility tests."""
    print("\n🔬 A.M.Y SCIENTIFIC VALIDATION SUITE\n")

    # Test 1: Reproducibility
    repro_result = await _run_reproducibility(n_runs=3)

    # Test 2: Syntax validation
    syntax_result = await test_syntax_validation()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Reproducibility: {'✅ PASS' if repro_result['success'] else '❌ FAIL'}")
    print(f"Syntax Validation: {'✅ PASS' if syntax_result['success'] else '❌ FAIL'}")

    if repro_result["success"] and syntax_result["success"]:
        print("\n🎉 ALL SCIENTIFIC VALIDATION TESTS PASSED")
        print("   A.M.Y produces reproducible, validated science.")
        return 0
    else:
        print("\n⚠️ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
