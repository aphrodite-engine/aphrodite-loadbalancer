#!/bin/bash

# Exit on error
set -e

echo "Running isort..."
if ! isort --check --diff .; then
    echo "❌ isort found issues"
    exit_code=1
else
    echo "✅ isort check passed"
fi

echo -e "\nRunning Ruff..."
if ! ruff check .; then
    echo "❌ Ruff found issues"
    exit_code=1
else
    echo "✅ Ruff check passed"
fi

# Exit with error if any checks failed
if [ "${exit_code}" = 1 ]; then
    echo -e "\n❌ Linting failed. To fix:"
    echo "  - Run 'isort .' to fix import sorting"
    echo "  - Run 'ruff check --fix .' to fix auto-fixable issues"
    exit 1
else
    echo -e "\n✅ All checks passed!"
fi