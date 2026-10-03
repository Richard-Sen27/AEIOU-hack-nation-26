import socket
import threading
import time

import uvicorn

from backend.devtools.mock_openai.app import create_app
from backend.devtools.mock_openai.state import MockState


def free_port(preferred: int | None = None) -> int:
    if preferred:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockOpenAIServer:
    """Runs the mock in a background thread. Use as a context manager or start()/stop()."""

    def __init__(self, port: int | None = None, state: MockState | None = None):
        # Bind now and hand the socket to uvicorn: no window in which another process
        # (e.g. a parallel pytest run) can take the port.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", port or 0))
        self.port = self._sock.getsockname()[1]
        self.state = state or MockState()
        self.app = create_app(self.state)
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="off",
            timeout_keep_alive=60,
        )
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def issuer(self) -> str:
        return self.url

    @property
    def api_base(self) -> str:
        return f"{self.url}/v1"

    def start(self) -> "MockOpenAIServer":
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("mock OpenAI server failed to start")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        self._sock.close()

    # convenience passthroughs
    def reset(self) -> None:
        self.state.reset()

    def configure(self, **switches) -> None:
        self.state.configure(**switches)

    def enqueue(self, *responses) -> None:
        self.state.enqueue(*responses)

    def __enter__(self) -> "MockOpenAIServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
