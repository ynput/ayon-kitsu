"""HTTP fault proxy for Kitsu requests (Requirement 4.15).

Injects HTTP 503 responses for requests matching a target task ID to simulate
repeated Retryable_Kitsu_Failure outcomes across all 4 attempts.
"""

from __future__ import annotations

import http.server
import threading
from typing import Any, Dict, Optional, Tuple


class FaultProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that intercepts target task paths and injects 503."""

    target_task_id: Optional[str] = None
    injected_count: int = 0

    def do_POST(self) -> None:
        """Handle POST request (status comments, etc.)."""
        self._handle_request()

    def do_GET(self) -> None:
        """Handle GET request."""
        self._handle_request()

    def do_PUT(self) -> None:
        """Handle PUT request."""
        self._handle_request()

    def _handle_request(self) -> None:
        """Check if request concerns target task; inject 503 if matched."""
        if self.target_task_id and self.target_task_id in self.path:
            FaultProxyHandler.injected_count += 1
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_body = b'{"error": "Simulated Kitsu 503 Service Unavailable"}'
            self.wfile.write(err_body)
            return

        # Fallback response for non-target paths in mock/proxy mode
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging."""
        pass


class KitsuFaultProxy:
    """Threaded HTTP fault proxy server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Initialize server on ephemeral or specified port."""
        self.server = http.server.HTTPServer((host, port), FaultProxyHandler)
        self.host, self.port = self.server.server_address
        self.thread: Optional[threading.Thread] = None

    def start(self, target_task_id: str) -> str:
        """Start proxy server targeting task id."""
        FaultProxyHandler.target_task_id = target_task_id
        FaultProxyHandler.injected_count = 0
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        return f"http://{self.host}:{self.port}"

    def stop(self) -> int:
        """Stop proxy server and return count of injected faults."""
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)
        return FaultProxyHandler.injected_count
