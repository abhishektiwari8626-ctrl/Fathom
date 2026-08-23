"""HTTP client for shipping spans to the Fathom backend.

Buffers spans locally and flushes them in batches via a background thread.
This avoids blocking the traced application with HTTP calls on every function exit.

Usage:
    client = FathomClient(endpoint="http://localhost:8000/api/v1")
    client.start()

    # ... spans are buffered by the tracer and flushed automatically ...

    client.shutdown()  # Flushes remaining spans and stops the background thread
"""

import atexit
import logging
import threading
import time
from queue import Empty, Queue
from uuid import UUID

import httpx

from fathom_sdk.types import SpanData

logger = logging.getLogger("fathom_sdk")


class FathomClient:
    """Async-safe HTTP client that batches and ships spans to Fathom backend.

    Args:
        endpoint: Base URL of the Fathom API (e.g., "http://localhost:8000/api/v1").
        flush_interval_s: How often to flush the buffer (in seconds).
        max_batch_size: Max spans per batch request.
        max_retries: Number of retries on HTTP failure.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:8000/api/v1",
        flush_interval_s: float = 1.0,
        max_batch_size: int = 100,
        max_retries: int = 3,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.flush_interval_s = flush_interval_s
        self.max_batch_size = max_batch_size
        self.max_retries = max_retries

        self._buffer: Queue[SpanData] = Queue()
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._http_client = httpx.Client(timeout=10.0)

        # Track active run ID
        self._current_run_id: UUID | None = None

    def start(self):
        """Start the background flush thread."""
        if self._flush_thread and self._flush_thread.is_alive():
            return

        self._stop_event.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="fathom-flush",
            daemon=True,
        )
        self._flush_thread.start()

        # Auto-shutdown on interpreter exit
        atexit.register(self.shutdown)
        logger.info("Fathom client started (flushing every %.1fs)", self.flush_interval_s)

    def shutdown(self):
        """Flush remaining spans and stop the background thread."""
        self._stop_event.set()
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5.0)

        # Final flush
        self._flush_now()
        self._http_client.close()
        logger.info("Fathom client shut down")

    def create_run(self, name: str, metadata: dict | None = None) -> UUID:
        """Create a new trace run on the backend and return its ID.

        Args:
            name: Human-readable name for this run.
            metadata: Optional metadata dict.

        Returns:
            The UUID of the created run.
        """
        payload = {"name": name, "metadata": metadata or {}}
        response = self._http_client.post(
            f"{self.endpoint}/traces/runs",
            json=payload,
        )
        response.raise_for_status()
        run_id = UUID(response.json()["id"])
        self._current_run_id = run_id
        logger.info("Created run %s (%s)", run_id, name)
        return run_id

    @property
    def current_run_id(self) -> UUID | None:
        """The ID of the currently active run."""
        return self._current_run_id

    def buffer_span(self, span: SpanData):
        """Add a span to the buffer queue. It will be flushed in the next batch."""
        self._buffer.put(span)

    def _flush_loop(self):
        """Background thread: periodically drains the buffer and ships spans."""
        while not self._stop_event.is_set():
            self._flush_now()
            self._stop_event.wait(timeout=self.flush_interval_s)

    def _flush_now(self):
        """Drain up to max_batch_size spans from the buffer and POST them."""
        spans: list[SpanData] = []
        while len(spans) < self.max_batch_size:
            try:
                span = self._buffer.get_nowait()
                spans.append(span)
            except Empty:
                break

        if not spans:
            return

        payload = {"spans": [s.to_dict() for s in spans]}

        for attempt in range(self.max_retries):
            try:
                response = self._http_client.post(
                    f"{self.endpoint}/traces/spans/batch",
                    json=payload,
                )
                response.raise_for_status()
                logger.debug("Flushed %d spans", len(spans))
                return
            except Exception as e:
                wait = 2**attempt * 0.1  # Exponential backoff: 0.1s, 0.2s, 0.4s
                logger.warning(
                    "Flush attempt %d/%d failed: %s (retrying in %.1fs)",
                    attempt + 1,
                    self.max_retries,
                    e,
                    wait,
                )
                time.sleep(wait)

        # All retries failed — log and move on (don't crash the traced app)
        logger.error("Failed to flush %d spans after %d retries", len(spans), self.max_retries)
