#!/bin/bash
# Quick test script for Agent Server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Agent Server Test Runner${NC}"
echo "========================="
echo ""

# Check if server is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "⚠️  Server not running at http://localhost:8000"
    echo ""
    echo "To start the server:"
    echo "  cd services/agent_server"
    echo "  uvicorn src.main:app --reload"
    echo ""
    exit 1
fi

# Parse command line arguments
TEST_TYPE="${1:-all}"
MESSAGE="${2:-What is the weather like?}"

case "$TEST_TYPE" in
    quick)
        echo "Running quick tests (health + websocket)..."
        python test_client.py --test health && python test_client.py --test websocket
        ;;
    full)
        echo "Running full test suite..."
        python test_client.py --test all --message "$MESSAGE"
        ;;
    chat)
        echo "Running chat test with message: '$MESSAGE'"
        python test_client.py --test chat --message "$MESSAGE"
        ;;
    *)
        echo "Running all tests..."
        python test_client.py --test all --message "$MESSAGE"
        ;;
esac

echo ""
echo -e "${GREEN}✓ Tests completed${NC}"
