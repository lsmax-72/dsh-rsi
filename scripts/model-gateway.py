"""Fixed-upstream OpenAI relay for a Docker internal network; no general HTTP proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import urllib.error
import urllib.request

upstream = os.environ['RSI_MODEL_UPSTREAM'].rstrip('/')
model = os.environ.get('RSI_MODEL_ID', 'qwen3.8-27b')
limit = int(os.environ.get('RSI_MODEL_REQUEST_LIMIT', '140'))
counter = 0
lock = threading.Lock()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reject(self, status, message):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(message.encode())

    def do_GET(self):
        if self.path != '/v1/models':
            self.reject(403, 'Only the declared model API is permitted.')
            return
        self.forward(None)

    def do_POST(self):
        global counter
        if self.path != '/v1/chat/completions':
            self.reject(403, 'Only chat completions are permitted.')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.reject(400, 'Invalid body size.')
            return
        if not 0 < length <= 20 * 1024 * 1024:
            self.reject(413, 'Invalid body size.')
            return
        body = self.rfile.read(length)
        try:
            request = json.loads(body)
            if request.get('model') != model or not isinstance(request.get('messages'), list):
                raise ValueError('Unexpected model or messages.')
            for field in ['max_tokens', 'max_completion_tokens']:
                if field in request and not 0 < request[field] <= 8192:
                    raise ValueError('Output budget exceeds pilot cap.')
            if not any(field in request for field in ['max_tokens','max_completion_tokens']):
                request['max_tokens'] = 8192
            body = json.dumps(request).encode()
        except (ValueError, TypeError) as exc:
            self.reject(400, str(exc))
            return
        with lock:
            if counter >= limit:
                self.reject(429, 'Pilot model request limit reached.')
                return
            counter += 1
            count = counter
        print(json.dumps({'request': count, 'model': model, 'path': self.path}), flush=True)
        self.forward(body)

    def forward(self, body):
        # Ignore caller URLs, redirects, proxy env and headers that could select another host.
        request = urllib.request.Request(upstream + self.path.removeprefix('/v1'), data=body,
                                         headers={'Content-Type': 'application/json'}, method='POST' if body else 'GET')
        try:
            with opener.open(request, timeout=300) as response:
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                self.end_headers()
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as exc:
            self.reject(exc.code, 'Upstream returned an HTTP error.')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, TimeoutError):
            self.reject(502, 'Declared model service unavailable.')


ThreadingHTTPServer(('0.0.0.0', 8080), Relay).serve_forever()
