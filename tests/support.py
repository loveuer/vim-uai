import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAPI:
    """A real local HTTP endpoint; tests never call a paid API."""

    def __init__(self):
        self.requests = []
        self.text = "    value = 42\n    return value\n"
        self.status = 200
        self.response = None
        self.delay = 0

    def __enter__(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.requests.append({"path": self.path, "headers": self.headers, "body": body})
                time.sleep(api.delay)
                if api.response is not None:
                    response = api.response
                elif self.path.endswith("/messages"):
                    response = {"content": [{"type": "text", "text": api.text}], "stop_reason": "end_turn"}
                else:
                    response = {"choices": [{"message": {"content": api.text}, "finish_reason": "stop"}]}
                raw = response if isinstance(response, bytes) else json.dumps(response).encode()
                try:
                    self.send_response(api.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = "http://127.0.0.1:{}/v1".format(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
