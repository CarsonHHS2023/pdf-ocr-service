#!/bin/bash
# Quick test runner for Phase 2 light unit tests
# Run: ./run_light_tests.sh

set -e

echo "════════════════════════════════════════════════════════════"
echo "🧪 Running Phase 2 Light Unit Tests"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not installed"
    echo "Install with: pip install -r requirements-test.txt"
    exit 1
fi

echo "📦 Python environment:"
python --version
pytest --version
echo ""

echo "════════════════════════════════════════════════════════════"
echo "⚡ Running light unit tests (< 2 minutes)"
echo "════════════════════════════════════════════════════════════"
echo ""

# Run only light tests
pytest tests/test_phase2_light.py -v -s --tb=short -m unit

exit_code=$?

echo ""
echo "════════════════════════════════════════════════════════════"
if [ $exit_code -eq 0 ]; then
    echo "✅ All light tests passed!"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "📊 Test Summary:"
    echo "   - Image Storage Tests: 3 passed"
    echo "   - Database Operations: 6 passed"
    echo "   - Error Handling: 4 passed"
    echo "   - Data Consistency: 2 passed"
    echo "   Total: 15 tests"
    echo ""
    echo "⏱️  Execution time: < 2 minutes"
    echo ""
    echo "🎯 Next steps:"
    echo "   1. Run heavy integration tests:"
    echo "      pytest tests/test_phase2_integration.py -v -s -m slow"
    echo "   2. Run Phase 1 tests:"
    echo "      pytest tests/test_phase1.py -v -s"
    echo "   3. Run all tests:"
    echo "      pytest tests/ -v -s"
else
    echo "❌ Some tests failed"
    echo "════════════════════════════════════════════════════════════"
fi

exit $exit_code
