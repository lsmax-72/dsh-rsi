"""Local deterministic API fixture; tests native embedding HTTP wiring, never model quality."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

class EmbeddingFixtureServer:
    def __enter__(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_POST(self):
                if self.path != '/v1/embeddings':
                    self.send_error(404);return
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                texts=body['input'] if isinstance(body['input'], list) else [body['input']]
                data=[]
                for index,text in enumerate(texts):
                    vector=[0.0]*768;vector[0]=1.0
                    for char in text: vector[1+ord(char)%767]+=1
                    norm=sum(value*value for value in vector)**.5
                    data.append({'index':index,'embedding':[value/norm for value in vector]})
                payload=json.dumps({'data':data}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.config={'provider':'fixture','baseUrl':f'http://127.0.0.1:{self.server.server_port}/v1','apiKey':'fixture-only','model':'character-hash-test-double','dimensions':768}
        return self
    def __exit__(self,*_args):
        self.server.shutdown();self.server.server_close();self.thread.join()
