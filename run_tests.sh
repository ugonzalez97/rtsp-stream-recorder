#!/bin/bash

# RTSP Stream Recorder - Test Runner Script
# Run all tests with coverage reporting

echo "======================================"
echo "RTSP Stream Recorder - Test Suite"
echo "======================================"
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing test dependencies..."
    pip install -r requirements-test.txt
fi

echo "🧪 Running test suite..."
echo ""

# Run tests with coverage
pytest -v --cov=src --cov-report=term-missing --cov-report=html

TEST_RESULT=$?

echo ""
echo "======================================"

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ All tests passed!"
    echo ""
    echo "📊 Coverage report generated in htmlcov/index.html"
else
    echo "❌ Some tests failed. Check output above for details."
fi

echo "======================================"

exit $TEST_RESULT
