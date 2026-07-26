#!/usr/bin/env python3
import json,hashlib,math
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
class H(BaseHTTPRequestHandler):
 def do_POST(self):
  n=int(self.headers.get('content-length','0'));p=json.loads(self.rfile.read(n));out=[]
  for text in p.get('texts',[]):
   b=hashlib.shake_256(text.encode()).digest(72*4);v=[]
   for i in range(72):v.append((int.from_bytes(b[i*4:i*4+4],'little')/2**32)*2-1)
   z=math.sqrt(sum(x*x for x in v));out.append([x/z for x in v])
  data=json.dumps({'vectors':out,'dim':72}).encode();self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8899),H).serve_forever()
