# Agent Server

WebSocket-based FastAPI backend for LLM agent orchestration with real-time streaming support.

## Overview

The Agent Server provides a WebSocket API for interacting with intelligent agents that can:
- Process natural language queries
- Execute tools via MCP (Model Context Protocol)
- Stream real-time status updates
- Handle location disambiguation
- Support multi-language interactions
- Generate artifacts (maps, data visualizations)

## Architecture

```
┌─────────────┐         WebSocket          ┌──────────────┐
│   Client    │ ◄──────────────────────► │ Agent Server │
│ (Streamlit) │                            │  (FastAPI)   │
└─────────────┘                            └──────┬───────┘
                                                  │
                                                  │ HTTP/SSE
                                                  ▼
                                           ┌──────────────┐
                                           │  MCP Server  │
                                           │   (Tools)    │
                                           └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- AWS credentials configured (for Bedrock)
- MCP Server running (for tool execution)

### Installation

```bash
cd services/agent_server
pip install -r requirements.txt
```

### Configuration

Set environment variables:

```bash
export MCP_SERVER_URL="http://localhost:8001"
export BEDROCK_MODEL_ID="anthropic.claude-3-5-sonnet-20241022-v2:0"
export AWS_REGION="us-east-1"
export LOG_LEVEL="INFO"
```

Or create a `.env` file:

```env
MCP_SERVER_URL=http://localhost:8001
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
AWS_REGION=us-east-1
LOG_LEVEL=INFO
```

### Running the Server

**Development mode:**
```bash
uvicorn src.main:app --reload --port 8000
```

**Production mode:**
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2
```

**Using Docker:**
```bash
docker build -t agent-server .
docker run -p 8000:8000 --env-file .env agent-server
```

### Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "agent-server",
  "version": "1.0.0",
  "uptime_seconds": 123.45,
  "timestamp": "2024-01-30T14:23:45.123456+00:00",
  "mcp_server_url": "http://localhost:8001"
}
```

## Testing

### Quick Test

Use the provided test client to verify functionality:

```bash
# Run all tests
./test.sh

# Quick smoke test (health + websocket only)
./test.sh quick

# Full integration test with custom message
./test.sh full "What is the weather in Paris?"

# Chat test only
./test.sh chat "Analyze flood risks in Tunisia"
```

### Manual Testing

```bash
python test_client.py --test all
```

See [TEST_CLIENT.md](./TEST_CLIENT.md) for detailed usage.

### Unit Tests

```bash
pytest tests/ -v
```

## API Reference

### WebSocket Endpoint

**URL:** `ws://localhost:8000/ws/chat`

**Connection Flow:**
1. Client connects
2. Server sends `connection_ack` message
3. Client sends `chat_request` message
4. Server streams updates (`status`, `tool_start`, `tool_result`)
5. Server sends `complete` message
6. Connection remains open for next request

### Message Types

#### Client → Server

**Chat Request:**
```json
{
  "type": "chat_request",
  "message": "What is the weather like?",
  "chat_history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"}
  ],
  "confirmed_locations": {},
  "language": "en"
}
```

**Chat Resume (after location confirmation):**
```json
{
  "type": "chat_resume",
  "confirmed_location": {
    "name": "Paris, France",
    "coordinates": [48.8566, 2.3522]
  },
  "pause_state": { /* server-provided state */ }
}
```

**Cancel:**
```json
{
  "type": "cancel"
}
```

#### Server → Client

**Connection Acknowledgment:**
```json
{
  "type": "connection_ack",
  "server_version": "1.0.0"
}
```

**Status Update:**
```json
{
  "type": "status",
  "stage": "planning",  // planning | tool_call | analyzing
  "detail": "Processing your request..."
}
```

**Tool Start:**
```json
{
  "type": "tool_start",
  "tool_name": "get_weather",
  "tool_input": {"location": "Paris"}
}
```

**Tool Result:**
```json
{
  "type": "tool_result",
  "tool_name": "get_weather",
  "result": {"observation": "Weather data retrieved"},
  "artifacts": {"maps": [], "urls": []}
}
```

**Complete:**
```json
{
  "type": "complete",
  "response": "The weather in Paris is sunny...",
  "artifacts": {
    "maps": ["base64_encoded_map"],
    "thumbnails": [],
    "urls": ["https://example.com"]
  },
  "error": false
}
```

**Error:**
```json
{
  "type": "error",
  "message": "Failed to process request",
  "recoverable": true
}
```

## Project Structure

```
agent_server/
├── src/
│   ├── api/              # API endpoints and routes
│   │   ├── health.py     # Health check endpoint
│   │   ├── models.py     # Pydantic message models
│   │   └── websocket.py  # WebSocket handler
│   ├── core/             # Core utilities
│   │   ├── config.py     # Configuration management
│   │   ├── logger.py     # Logging setup
│   │   ├── memory.py     # Chat history management
│   │   └── prompts.py    # Agent prompts
│   ├── services/         # Business logic
│   │   ├── agent_runner.py            # Agent execution
│   │   ├── orchestrator_agent_service.py  # Main orchestrator
│   │   ├── data_agent_service.py      # Data retrieval agent
│   │   ├── analysis_agent_service.py  # Analysis agent
│   │   ├── llm_service.py            # LLM client
│   │   ├── document_service.py       # PDF processing
│   │   └── translate_service.py      # Translation
│   ├── tools/            # Tool definitions
│   │   ├── contracts.py          # Tool type definitions
│   │   ├── mcp_remote_tools.py   # MCP tool integration
│   │   └── tools.py              # Tool registry
│   ├── config.py         # App configuration
│   └── main.py           # FastAPI application
├── tests/                # Unit tests
├── Dockerfile            # Container definition
├── requirements.txt      # Python dependencies
├── test_client.py        # CLI test client
├── test.sh              # Test runner script
└── README.md            # This file
```

## Development

### Code Style

- Follow PEP 8
- Use type hints
- Document functions with docstrings
- Keep functions focused and testable

### Adding New Tools

1. Define tool in MCP server
2. Tool automatically available via MCP integration
3. Update agent prompts if needed

### Adding New Agent Services

1. Create service file in `src/services/`
2. Implement agent graph with LangGraph
3. Register in orchestrator
4. Add tests

### Logging

Configure log level via environment:
```bash
export LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

Logs include:
- Request/response tracking
- Tool execution details
- Error stack traces
- Performance metrics

## Deployment

### Docker

```bash
# Build
docker build -t agent-server .

# Run
docker run -d \
  --name agent-server \
  -p 8000:8000 \
  --env-file .env \
  agent-server
```

### Docker Compose

```yaml
services:
  agent-server:
    build: ./services/agent_server
    ports:
      - "8000:8000"
    environment:
      - MCP_SERVER_URL=http://mcp-server:8001
    depends_on:
      - mcp-server
```

### AWS ECS

See [infrastructure/](../../infrastructure/) for Terraform configurations.

## Monitoring

### Health Checks

```bash
# Local
curl http://localhost:8000/health

# Production
curl https://your-domain.com/health
```

### Metrics

- Uptime tracking via `/health` endpoint
- WebSocket connection count
- Request processing time
- Error rates

### Logging

Structured JSON logs for:
- Request tracking
- Tool execution
- Errors and exceptions
- Performance metrics

## Troubleshooting

### Server won't start

**Check port availability:**
```bash
lsof -i :8000
```

**Check environment variables:**
```bash
python -c "from src.config import get_config; print(get_config())"
```

### WebSocket connection fails

- Verify CORS settings in `src/main.py`
- Check firewall rules
- Test with `test_client.py`

### Agent requests timeout

- Verify MCP server is running
- Check AWS credentials: `aws sts get-caller-identity`
- Review agent_server logs
- Increase timeout in client

### Tools not working

- Check MCP server logs
- Verify tool registration
- Test tools directly with MCP test client

## Contributing

1. Create feature branch
2. Add tests for new functionality
3. Ensure all tests pass: `pytest tests/`
4. Run test client: `./test.sh`
5. Submit pull request

## License

Proprietary - MetaPlanet SAS
