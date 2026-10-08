#!/usr/bin/env python3
"""Local synthetic upstream only; prove relay bytes, reasoning audit and mode rejection."""
import contextlib,hashlib,importlib.util,io,json,os,tempfile,threading,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
P=Path(__file__).resolve().parent.parent
class Upstream(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));assert request['max_tokens']==8192
  reasoning='核对前提' if request['chat_template_kwargs']['enable_thinking'] else ''
  chunks=[{'model':'qwen3.8-27b','system_fingerprint':'fixture-weights-version','choices':[{'delta':{'reasoning_content':reasoning},'finish_reason':None}]},{'choices':[{'delta':{'content':'answer'},'finish_reason':'stop'}]},{'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18,'completion_tokens_details':{'reasoning_tokens':4 if reasoning else 0}}}]
  body=b''.join(b'data: '+json.dumps(c,ensure_ascii=False).encode()+b'\n\n' for c in chunks)+b'data: [DONE]\n\n';self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  for i in range(0,len(body),3):self.wfile.write(body[i:i+3]);self.wfile.flush()
up=ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=up.serve_forever,daemon=True).start();os.environ['RSI_MODEL_UPSTREAM']='http://127.0.0.1:'+str(up.server_port)+'/v1'
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
g=load('gateway',P/'scripts/model-gateway.py');runner=load('runner',P/'scripts/probe-runner.py');relay=ThreadingHTTPServer(('127.0.0.1',0),g.Relay);threading.Thread(target=relay.serve_forever,daemon=True).start();checks=[]
try:
 with tempfile.TemporaryDirectory() as td:
  for mode in ['on','off']:
   out=Path(td)/mode;out.mkdir();os.environ['RSI_WIRE_DIR']=str(out/'gateway-evidence');logs=io.StringIO()
   req={'model':'qwen3.8-27b','messages':[{'role':'user','content':'fixture'}],'stream':True,'max_tokens':8192,'chat_template_kwargs':{'enable_thinking':mode=='on','preserve_thinking':True}}
   with contextlib.redirect_stdout(logs):
    raw=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(relay.server_port)+'/v1/chat/completions',data=json.dumps(req).encode(),headers={'Content-Type':'application/json'})).read()
   (out/'gateway.log').write_text(logs.getvalue());summary=next(json.loads(l) for l in logs.getvalue().splitlines() if 'responseRequest' in json.loads(l));assert raw==(out/'gateway-evidence'/summary['rawResponse']).read_bytes();assert summary['usage'][0]['completion_tokens_details']['reasoning_tokens']==(4 if mode=='on' else 0)
   result=runner.verify_thinking_wire(out,mode);assert result['reasoningChars']==(4 if mode=='on' else 0);assert result['responseModels']==['qwen3.8-27b'] and result['systemFingerprints']==['fixture-weights-version']
   first=next(json.loads(l) for l in logs.getvalue().splitlines() if 'request' in json.loads(l));assert first['messagesSha256']==hashlib.sha256(json.dumps(req['messages'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();assert first['maxOutputTokens']==8192
   try:runner.verify_thinking_wire(out,'off' if mode=='on' else 'on')
   except AssertionError:pass
   else:raise AssertionError('Wrong mode accepted')
   (out/'gateway-evidence'/summary['rawResponse']).write_bytes(b'tampered')
   try:runner.verify_thinking_wire(out,mode)
   except AssertionError:pass
   else:raise AssertionError('Tampered evidence accepted')
  checks+=['actual local relay preserves exact SSE bytes across split Unicode chunks','on has genuine fixture reasoning and off has none','wire mode mismatch rejected','raw response tampering rejected','raw detailed reasoning usage retained']
  # Reject flags alone: wire=true without upstream reasoning must fail.
  out=Path(td)/'empty-on';out.mkdir();body=json.dumps({'chat_template_kwargs':{'enable_thinking':True}}).encode();logs=io.StringIO()
  with contextlib.redirect_stdout(logs):
   a=g.ResponseAudit(out/'gateway-evidence',99,body);a.contentType='text/event-stream';a.feed(b'data: {"choices":[{"delta":{"content":"text"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');a.close(True)
  (out/'gateway.log').write_text(json.dumps({'request':99,'model':'qwen3.8-27b','enableThinking':True})+'\n'+logs.getvalue())
  try:runner.verify_thinking_wire(out,'on')
  except AssertionError:pass
  else:raise AssertionError('Flag only accepted')
  checks.append('wire=true without actual reasoning output rejected')
finally:relay.shutdown();up.shutdown()
print(json.dumps({'status':'PASS_LOCAL_THINKING_WIRE','realProviderRequests':0,'dockerOperations':0,'checks':checks},ensure_ascii=False))
