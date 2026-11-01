"""JUnit report comparator for baseline vs feature regression testing.

Compares two pytest --junitxml reports (baseline and feature branch) and
identifies every test id whose outcome differs (Requirements 2.5, 14.8).

Validates: Requirements 2.5, 14.8
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple


def parse_junit_xml(file_path: str) -> Dict[str, str]:
    """Parse a JUnit XML file and return a mapping of test ID to outcome.

    Outcomes are one of: "passed", "failed", "error", "skipped".

    Args:
        file_path: Path to the JUnit XML file.

    Returns:
        Dict mapping test id (classname::name) to outcome string.
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    results: Dict[str, str] = {}
    for testcase in root.iter("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        test_id = f"{classname}::{name}" if classname else name

        outcome = "passed"
        if testcase.find("failure") is not None:
            outcome = "failed"
        elif testcase.find("error") is not None:
            outcome = "error"
        elif testcase.find("skipped") is not None:
            outcome = "skipped"

        results[test_id] = outcome

    return results


def compare_junit_reports(
    baseline_path: str,
    feature_path: str,
) -> Dict[str, Any]:
    """Compare baseline and feature JUnit XML test results.

    Args:
        baseline_path: Path to baseline JUnit XML file.
        feature_path: Path to feature branch JUnit XML file.

    Returns:
        Dict with total, matched, changed, missing, and added tests.
    """
    baseline = parse_junit_xml(baseline_path)
    feature = parse_junit_xml(feature_path)

    matched: List[str] = []
    changed: List[Dict[str, str]] = []
    missing_in_feature: List[str] = []
    added_in_feature: List[str] = []

    for test_id, base_outcome in baseline.items():
        if test_id not in feature:
            missing_in_feature.append(test_id)
        else:
            feat_outcome = feature[test_id]
            if base_outcome == feat_outcome:
                matched.append(test_id)
            else:
                changed.append({
                    "test_id": test_id,
                    "baseline": base_outcome,
                    "feature": feat_outcome,
                })

    for test_id in feature:
        if test_id not in baseline:
            added_in_feature.append(test_id)

    return {
        "baseline_count": len(baseline),
        "feature_count": len(feature),
        "matched_count": len(matched),
        "changed": changed,
        "missing_in_feature": missing_in_feature,
        "added_in_feature": added_in_feature,
        "is_regression_free": (
            len(changed) == 0 and len(missing_in_feature) == 0
        ),
    }


def main() -> None:
    """CLI entry point for comparing two JUnit XML files."""
    parser = argparse.ArgumentParser(
        description="Compare two JUnit XML files for regressions."
    )
    parser.add_argument("baseline", help="Path to baseline JUnit XML")
    parser.add_argument("feature", help="Path to feature JUnit XML")
    args = parser.parse_args()

    diff = compare_junit_reports(args.baseline, args.feature)
    print("=== JUnit Comparison Summary ===")
    print(f"Baseline tests: {diff['baseline_count']}")
    print(f"Feature tests: {diff['feature_count']}")
    print(f"Matching outcomes: {diff['matched_count']}")
    print(f"Changed outcomes: {len(diff['changed'])}")
    print(f"Missing in feature: {len(diff['missing_in_feature'])}")
    print(f"Added in feature: {len(diff['added_in_feature'])}")

    if diff["changed"]:
        print("\nChanged test outcomes:")
        for c in diff["changed"]:
            print(f"  {c['test_id']}: {c['baseline']} -> {c['feature']}")

    if diff["missing_in_feature"]:
        print("\nMissing tests in feature:")
        for m in diff["missing_in_feature"]:
            print(f"  {m}")

    sys.exit(0 if diff["is_regression_free"] else 1)


if __name__ == "__main__":
    main()
