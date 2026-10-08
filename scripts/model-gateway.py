"""Fixed-upstream OpenAI relay for a Docker internal network; no general HTTP proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
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


class ResponseAudit:
    """Observe exact upstream bytes without changing the forwarded stream."""
    def __init__(self, directory, ordinal, body):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.stem='request-'+str(ordinal).zfill(4);self.body=body
        (self.directory/(self.stem+'.request.json')).write_bytes(body)
        self.stream=(self.directory/(self.stem+'.response.bin')).open('wb')
        self.digest=hashlib.sha256();self.buffer=b'';self.reasoningEvents=0;self.reasoningChars=0;self.reasoningContentEvents=0;self.reasoningContentChars=0;self.finishReasons=[];self.usage=[];self.parseErrors=0;self.done=False;self.contentType='';self.responseModels=[];self.systemFingerprints=[]
    def event(self,value):
        if value.get('model') is not None and value['model'] not in self.responseModels:self.responseModels.append(value['model'])
        if value.get('system_fingerprint') is not None and value['system_fingerprint'] not in self.systemFingerprints:self.systemFingerprints.append(value['system_fingerprint'])
        if value.get('usage') is not None:self.usage.append(value['usage'])
        for choice in value.get('choices',[]):
            if choice.get('finish_reason') is not None:self.finishReasons.append(choice['finish_reason'])
            delta=choice.get('delta',choice.get('message',{})) or {}
            # Count canonical reasoning_content separately; accept the same fallback fields as pi-ai.
            raw=delta.get('reasoning_content')
            if isinstance(raw,str) and raw:self.reasoningContentEvents+=1;self.reasoningContentChars+=len(raw)
            reasoning=next((delta[k] for k in ['reasoning_content','reasoning','reasoning_text'] if isinstance(delta.get(k),str) and delta[k]),'')
            if reasoning:self.reasoningEvents+=1;self.reasoningChars+=len(reasoning)
    def line(self,line):
        if not line.startswith(b'data:'):return
        data=line[5:].strip()
        if data==b'[DONE]':self.done=True;return
        if not data:return
        try:self.event(json.loads(data))
        except (ValueError,TypeError,AttributeError):self.parseErrors+=1
    def feed(self,chunk):
        self.stream.write(chunk);self.digest.update(chunk)
        if 'event-stream' in self.contentType:
            self.buffer+=chunk
            while b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1);self.line(line.rstrip(b'\r'))
    def close(self,complete,error=None):
        self.stream.flush();os.fsync(self.stream.fileno());self.stream.close()
        if 'event-stream' in self.contentType:
            if self.buffer:self.line(self.buffer)
        elif complete:
            try:self.event(json.loads((self.directory/(self.stem+'.response.bin')).read_bytes()))
            except (ValueError,TypeError,AttributeError):self.parseErrors+=1
        summary={'responseRequest':int(self.stem.split('-')[1]),'responseComplete':complete,'sseDone':self.done,'contentType':self.contentType,'reasoningEvents':self.reasoningEvents,'reasoningChars':self.reasoningChars,'reasoningContentEvents':self.reasoningContentEvents,'reasoningContentChars':self.reasoningContentChars,'finishReasons':self.finishReasons,'responseModels':self.responseModels,'systemFingerprints':self.systemFingerprints,'weightsHash':None,'usage':self.usage,'parseErrors':self.parseErrors,'requestSha256':hashlib.sha256(self.body).hexdigest(),'responseSha256':self.digest.hexdigest(),'rawRequest':self.stem+'.request.json','rawResponse':self.stem+'.response.bin','error':error}
        (self.directory/(self.stem+'.summary.json')).write_text(json.dumps(summary,ensure_ascii=False)+'\n');print(json.dumps(summary,ensure_ascii=False),flush=True)


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
        print(json.dumps({'request': count, 'model': model, 'path': self.path, 'enableThinking': request.get('chat_template_kwargs',{}).get('enable_thinking','ABSENT'),'messageRoles': [m.get('role') for m in request['messages']],'messagesSha256':hashlib.sha256(json.dumps(request['messages'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),'toolsSha256':hashlib.sha256(json.dumps(request.get('tools'),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),'maxOutputTokens':request.get('max_tokens',request.get('max_completion_tokens')),'temperature':request.get('temperature')}), flush=True)
        self.forward(body,count)

    def forward(self, body, ordinal=None):
        # Ignore caller URLs, redirects, proxy env and headers that could select another host.
        request = urllib.request.Request(upstream + self.path.removeprefix('/v1'), data=body,
                                         headers={'Content-Type': 'application/json'}, method='POST' if body else 'GET')
        audit=ResponseAudit(os.environ.get('RSI_WIRE_DIR','/tmp/gateway-evidence'),ordinal,body) if ordinal is not None else None
        complete=False;error=None
        try:
            with opener.open(request, timeout=300) as response:
                if audit:audit.contentType=response.headers.get('Content-Type','application/json')
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                self.end_headers()
                while chunk := response.read1(65536):
                    if audit:audit.feed(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
                complete=True
        except urllib.error.HTTPError as exc:
            error="HTTP_ERROR"
            try:
                payload = json.loads(exc.read())
                detail = payload.get('error', payload)
                message = detail.get('message','') if isinstance(detail,dict) else str(detail)
            except (ValueError,OSError):
                message = 'Non-JSON upstream error'
            print(json.dumps({'upstreamStatus':exc.code,'errorMessage':message[:1000]}),flush=True)
            self.reject(exc.code, 'Upstream returned an HTTP error.')
        except (BrokenPipeError, ConnectionResetError):
            error="CLIENT_DISCONNECTED"
        except (OSError, TimeoutError):
            error="TRANSPORT_ERROR"
            self.reject(502, 'Declared model service unavailable.')

        finally:
            if audit:audit.close(complete,error)


if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Relay).serve_forever()
