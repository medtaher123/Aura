#!/usr/bin/env python3
"""
CLI Test Client for Agent Server

Simple command-line tool to test:
- HTTP health endpoint
- WebSocket connection
- Message streaming
- Basic chat functionality
"""

import asyncio
import json
import sys
import argparse
from typing import Any, Optional
from datetime import datetime, timedelta, timezone
import httpx
import websockets
from websockets.exceptions import WebSocketException
from src.schemas.websocket import ChatResumeMessage
import jwt


import boto3
import os

def get_test_token(issuer: str = "metaplanet-local-test-environment") -> str:
    """Forges a JWT that matches the TestProvider's expected issuer."""
    payload = {
        "iss": issuer,
        "sub": "test_user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
        "token_use": "access"
    }
    return jwt.encode(payload, "secret", algorithm="HS256")


token = get_test_token()
headers = {"Authorization": f"Bearer {token}"} if token else {}

class AgentServerTestClient:
    """Simple test client for the Agent Server."""

    def __init__(self, host: str = "localhost", port: int = 8080):
        self.http_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/ws/chat"
        self.connected = False

    def print_status(self, message: str, status: str = "INFO"):
        """Print formatted status message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "\033[94m",  # Blue
            "SUCCESS": "\033[92m",  # Green
            "ERROR": "\033[91m",  # Red
            "WARN": "\033[93m",  # Yellow
        }
        reset = "\033[0m"
        color = colors.get(status, "")
        print(f"[{timestamp}] {color}{status}{reset}: {message}")

    async def test_health(self) -> bool:
        """Test the health endpoint."""
        self.print_status("Testing health endpoint...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.http_url}/health", timeout=5.0)

                if response.status_code == 200:
                    data = response.json()
                    self.print_status("Health check passed!", "SUCCESS")
                    self.print_status(f"  Service: {data.get('service')}")
                    self.print_status(f"  Version: {data.get('version')}")
                    self.print_status(f"  Status: {data.get('status')}")
                    self.print_status(f"  Uptime: {data.get('uptime_seconds')}s")
                    self.print_status(f"  MCP Server: {data.get('mcp_server_url')}")
                    return True
                else:
                    self.print_status(
                        f"Health check failed: HTTP {response.status_code}", "ERROR"
                    )
                    return False

        except Exception as e:
            self.print_status(f"Health check error: {e}", "ERROR")
            return False

    async def test_websocket_connection(self) -> bool:
        """Test WebSocket connection and acknowledgment."""
        self.print_status("Testing WebSocket connection...")

        try:
            async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                # Wait for connection acknowledgment
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(response)

                if data.get("type") == "connection_ack":
                    self.print_status("WebSocket connection established!", "SUCCESS")
                    self.print_status(f"  Server version: {data.get('server_version')}")
                    return True
                else:
                    self.print_status(
                        f"Unexpected message type: {data.get('type')}", "ERROR"
                    )
                    return False

        except asyncio.TimeoutError:
            self.print_status("WebSocket connection timeout", "ERROR")
            return False
        except WebSocketException as e:
            self.print_status(f"WebSocket connection error: {e}", "ERROR")
            return False
        except Exception as e:
            self.print_status(f"Unexpected error: {e}", "ERROR")
            return False

    async def test_chat_request(self, message: str, timeout: int = 60) -> bool:
        """
        Test sending a chat request and receiving responses.

        Args:
            message: The message to send to the agent
            timeout: Maximum time to wait for completion (seconds)
        """
        self.print_status(f"Testing chat request: '{message}'")

        try:
            
            async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                # Wait for connection acknowledgment
                ack = await asyncio.wait_for(ws.recv(), timeout=5.0)
                ack_data = json.loads(ack)

                if ack_data.get("type") != "connection_ack":
                    self.print_status(
                        "Did not receive connection acknowledgment", "ERROR"
                    )
                    return False

                self.print_status("Connected, sending chat request...")

                # Send chat request
                request = {
                    "type": "chat_request",
                    "message": message,
                    "chat_history": [],
                    "confirmed_locations": {},
                    "language": "en",
                }
                await ws.send(json.dumps(request))
                self.print_status("Request sent, waiting for responses...", "SUCCESS")

                # Listen for responses
                completed = False
                message_count = 0

                while not completed:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        data = json.loads(response)
                        message_count += 1
                        msg_type = data.get("type")

                        if msg_type == "status":
                            stage = data.get("stage", "unknown")
                            detail = data.get("detail", "")
                            self.print_status(f"Status update: {stage} - {detail}")

                        elif msg_type == "tool_start":
                            tool_name = data.get("tool_name", "unknown")
                            self.print_status(f"Tool starting: {tool_name}", "WARN")

                        elif msg_type == "tool_result":
                            tool_name = data.get("tool_name", "unknown")
                            result = data.get("result", {})
                            error = result.get("error", False)
                            status = "ERROR" if error else "SUCCESS"
                            self.print_status(f"Tool result: {tool_name}", status)

                        elif msg_type == "token":
                            # Stream tokens (not printed to keep output clean)
                            pass

                        elif msg_type == "complete":
                            response_text = data.get("response", "")
                            error = data.get("error", False)
                            artifacts = data.get("artifacts", {})

                            self.print_status("=" * 60)
                            self.print_status(
                                "RESPONSE RECEIVED", "SUCCESS" if not error else "ERROR"
                            )
                            self.print_status("=" * 60)
                            print(f"\n{response_text}\n")

                            if artifacts.get("maps"):
                                self.print_status(
                                    f"Maps: {len(artifacts['maps'])} generated"
                                )
                                # print all maps
                                for map in artifacts["maps"]:
                                    self.print_status(
                                        f"Map:\n{json.dumps(map, indent=2)}"
                                    )
                            if artifacts.get("urls"):
                                self.print_status(
                                    f"URLs: {len(artifacts['urls'])} provided"
                                )

                            self.print_status(
                                f"Total messages received: {message_count}"
                            )
                            completed = True
                            return not error

                        elif msg_type == "location_confirmation":
                            options = data.get("options", [])
                            pause_state = data.get("pause_state", {})
                            self.print_status(
                                f"Location confirmation requested: {len(options)} options",
                                "INFO",
                            )
                            self.print_status(
                                f"Pause state keys: {list(pause_state.keys())}"
                            )

                            for idx, option in enumerate(options):
                                self.print_status(f"  {idx}: {option}")
                            self.print_status(
                                "Please select the correct location by entering the number of the option:"
                            )
                            selection = input()
                            if selection.isdigit():
                                selection = int(selection)
                                if selection >= 0 and selection < len(options):
                                    self.print_status(
                                        f"Selected location: {options[selection]}"
                                    )
                                # stream the selected location to the agent
                                await ws.send(
                                    ChatResumeMessage(
                                        type="chat_resume",
                                        confirmed_location=options[selection],
                                        pause_state=pause_state,
                                    ).model_dump_json()
                                )
                            else:
                                self.print_status("Invalid selection", "ERROR")
                                # retry the location confirmation
                                return await self.test_chat_request(message, timeout)

                        elif msg_type == "error":
                            error_msg = data.get("message", "Unknown error")
                            recoverable = data.get("recoverable", False)
                            self.print_status(f"Error: {error_msg}", "ERROR")
                            self.print_status(f"Recoverable: {recoverable}")
                            return False

                        else:
                            self.print_status(
                                f"Unknown message type: {msg_type}", "WARN"
                            )

                    except asyncio.TimeoutError:
                        self.print_status(
                            f"Timeout waiting for response (>{timeout}s)", "ERROR"
                        )
                        return False

                return True

        except Exception as e:
            self.print_status(f"Chat request error: {e}", "ERROR")
            import traceback

            traceback.print_exc()
            return False

    async def run_all_tests(
        self, include_chat: bool = False, chat_message: Optional[str] = None
    ):
        """Run all tests in sequence."""
        self.print_status("=" * 60)
        self.print_status("AGENT SERVER TEST SUITE", "INFO")
        self.print_status("=" * 60)

        results = {}

        # Test 1: Health endpoint
        print()
        results["health"] = await self.test_health()

        # Test 2: WebSocket connection
        print()
        results["websocket"] = await self.test_websocket_connection()

        # Test 3: Chat request (optional)
        if include_chat and chat_message:
            print()
            results["chat"] = await self.test_chat_request(chat_message)

        # Summary
        print()
        self.print_status("=" * 60)
        self.print_status("TEST SUMMARY", "INFO")
        self.print_status("=" * 60)

        for test_name, passed in results.items():
            status = "SUCCESS" if passed else "ERROR"
            result = "PASSED" if passed else "FAILED"
            self.print_status(f"{test_name.upper()}: {result}", status)

        all_passed = all(results.values())
        print()
        if all_passed:
            self.print_status("All tests passed! ✓", "SUCCESS")
        else:
            self.print_status("Some tests failed ✗", "ERROR")

        return all_passed


async def main():
    """Main entry point for the test client."""
    parser = argparse.ArgumentParser(
        description="Test client for Agent Server WebSocket API"
    )
    parser.add_argument(
        "--host", default="localhost", help="Server host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Server port (default: 8080)"
    )
    parser.add_argument(
        "--test",
        choices=["health", "websocket", "chat", "all"],
        default="all",
        help="Which test to run (default: all)",
    )
    parser.add_argument(
        "--message",
        default="What is the weather like?",
        help="Message to send for chat test (default: 'What is the weather like?')",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout for chat test in seconds (default: 60)",
    )

    args = parser.parse_args()

    client = AgentServerTestClient(host=args.host, port=args.port)

    try:
        if args.test == "health":
            success = await client.test_health()
        elif args.test == "websocket":
            success = await client.test_websocket_connection()
        elif args.test == "chat":
            success = await client.test_chat_request(args.message, args.timeout)
        else:  # all
            success = await client.run_all_tests(
                include_chat=True, chat_message=args.message
            )

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        client.print_status("\nTest interrupted by user", "WARN")
        sys.exit(130)


if __name__ == "__main__":
    asyncio.run(main())
