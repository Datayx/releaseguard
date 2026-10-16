"""Local disposable task API. Demo only; binds to loopback."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


def make_server(port=8000):
    tasks = {}
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.path != "/tasks":
                return self.reply(404, {})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                task_id = body["id"]
                title = body["title"]
                if not isinstance(task_id, str) or not isinstance(title, str):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {})
            with lock:
                if task_id in tasks:
                    return self.reply(409, {})
                tasks[task_id] = {"id": task_id, "title": title}
            self.reply(201, {"id": task_id})

        def do_GET(self):
            with lock:
                task = tasks.get(self.path.removeprefix("/tasks/"))
            if not task:
                return self.reply(404, {})
            if os.environ.get("DEMO_BROKEN") == "1":
                task = task | {"title": "incorrect value"}
            self.reply(200, task)

        def do_DELETE(self):
            with lock:
                task = tasks.pop(self.path.removeprefix("/tasks/"), None)
            self.reply(200 if task else 404, {})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    print("Demo API: http://127.0.0.1:8000", flush=True)
    try:
        make_server().serve_forever()
    except KeyboardInterrupt:
        pass
