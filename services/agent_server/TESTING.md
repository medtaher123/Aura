# Agent Server Testing Guide

## Quick Start

### 1. Install Dependencies

```bash
cd services/agent_server
pip install -r requirements.txt
```

### 2. Start the Server

```bash
uvicorn src.main:app --reload --port 8000
```

### 3. Run Tests

**Easiest method (recommended):**
```bash
./test.sh
```

**Using Python directly:**
```bash
python test_client.py --test all
```

## Test Scenarios

### Scenario 1: Quick Health Check

```bash
python test_client.py --test health
```

Expected output:
```
[14:23:45] INFO: Testing health endpoint...
[14:23:45] SUCCESS: Health check passed!
[14:23:45] INFO:   Service: agent-server
[14:23:45] INFO:   Version: 1.0.0
[14:23:45] INFO:   Status: healthy
```

### Scenario 2: WebSocket Connection

```bash
python test_client.py --test websocket
```

Expected output:
```
[14:23:46] INFO: Testing WebSocket connection...
[14:23:46] SUCCESS: WebSocket connection established!
[14:23:46] INFO:   Server version: 1.0.0
```

### Scenario 3: Full Chat Flow

```bash
python test_client.py --test chat --message "What is the weather like?"
```

Expected output:
```
[14:23:47] INFO: Testing chat request: 'What is the weather like?'
[14:23:47] SUCCESS: Connected, sending chat request...
[14:23:47] SUCCESS: Request sent, waiting for responses...
[14:23:48] INFO: Status update: planning - Processing your request...
[14:23:49] WARN: Tool starting: get_weather
[14:23:50] SUCCESS: Tool result: get_weather
[14:23:51] SUCCESS: RESPONSE RECEIVED
============================================================

The current weather is sunny with a temperature of 22°C...

[14:23:51] INFO: Total messages received: 8
```

## What Gets Tested

### ✅ Connection Tests
- [x] HTTP health endpoint (`/health`)
- [x] WebSocket connection (`/ws/chat`)
- [x] Connection acknowledgment message

### ✅ Message Protocol Tests
- [x] Chat request message format
- [x] Server message parsing
- [x] Status updates
- [x] Tool execution notifications
- [x] Completion messages
- [x] Error handling

### ✅ Stream Tests
- [x] Real-time message streaming
- [x] Status update flow
- [x] Tool start/result flow
- [x] Response completion
- [x] Timeout handling

### ✅ Functional Tests
- [x] End-to-end chat request
- [x] Agent orchestration
- [x] Tool execution monitoring
- [x] Error recovery

## Files Created

```
services/agent_server/
├── test_client.py      # Main test client (CLI)
├── test.sh            # Quick test runner script
├── TEST_CLIENT.md     # Detailed test client docs
├── TESTING.md         # This file
└── README.md          # Complete service documentation
```

## Test Client Features

- **Simple CLI interface** - No complex setup required
- **Color-coded output** - Easy to read results
- **Flexible testing** - Run individual or all tests
- **Timeout handling** - Configurable timeouts
- **Error reporting** - Clear error messages
- **Exit codes** - Scriptable for CI/CD

## Integration with CI/CD

Add to your CI pipeline:

```yaml
# GitHub Actions example
- name: Test Agent Server
  run: |
    cd services/agent_server
    pip install -r requirements.txt
    uvicorn src.main:app &
    sleep 5
    python test_client.py --test all || exit 1
```

## Troubleshooting

### "Connection refused"
- Ensure server is running: `uvicorn src.main:app --reload`
- Check port is not in use: `lsof -i :8000`

### "Module not found"
- Install dependencies: `pip install -r requirements.txt`

### "Timeout"
- Increase timeout: `--timeout 120`
- Check MCP server is running
- Verify AWS credentials

### "WebSocket connection failed"
- Check CORS settings in `src/main.py`
- Verify no proxy blocking WebSocket
- Test with browser DevTools

## Advanced Usage

### Custom Server Location

```bash
python test_client.py --host production.example.com --port 443
```

### Long-Running Tests

```bash
python test_client.py --test chat --message "Complex analysis" --timeout 300
```

### Programmatic Usage

```python
from test_client import AgentServerTestClient
import asyncio

async def test():
    client = AgentServerTestClient(host="localhost", port=8000)
    success = await client.test_health()
    print(f"Health check: {'passed' if success else 'failed'}")

asyncio.run(test())
```

## Next Steps

1. **Run the tests** to verify your setup
2. **Check the logs** if tests fail
3. **Review TEST_CLIENT.md** for more options
4. **Integrate into CI/CD** for automated testing

## Support

For issues or questions:
- Review server logs: `docker-compose logs agent_server`
- Check MCP server connectivity
- Verify AWS credentials
- See README.md for detailed documentation
