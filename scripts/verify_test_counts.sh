#!/usr/bin/env bash
# Pre-Fix D (savings-math-prominence) — pin canonical test counts before
# updating any guiding-doc test number.
#
# demo-prep-1-3 carry-forward: a miscounted test total made it into 4
# guiding docs before the catch. The fix is to never type a test count
# from memory — always paste the output of this script.
#
# Usage: `make verify-counts` (or `bash scripts/verify_test_counts.sh`).
#
# Why ``cd backend`` for pytest: see CLAUDE.md L-pytest-cwd-flake. Running
# pytest from the repo root intermittently reports unrelated failures.
#
# Why ``-parallel-testing-enabled NO``: see CLAUDE.md L-parallel-runner.
#
# Why ``SEARCH_TIER2_USE_EBAY=false``: see CLAUDE.md L-Experiment-flags-default-off.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "==> Backend tests (cd backend && pytest -q)"
( cd backend && SEARCH_TIER2_USE_EBAY=false pytest -q 2>&1 | tail -1 )

echo
echo "==> iOS tests (xcodebuild test -only-testing:BarkainTests)"
xcodebuild test \
  -project Barkain.xcodeproj \
  -scheme Barkain \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -parallel-testing-enabled NO \
  -only-testing:BarkainTests 2>&1 \
  | grep -E "Test run with|Executed [0-9]+ test|TEST SUCCEEDED|TEST FAILED" \
  | tail -5
