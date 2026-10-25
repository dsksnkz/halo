"""Paired TLS transport and signed LAN discovery. AI remains on the laptop."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import threading

STATE = Path.home()/'.local/state/halo/wifi'
PORT = 8767
DISCOVERY_PORT = 8768


def identity():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE,0o700)
    cert,key,token = (STATE/name for name in ('certificate.pem','private-key.pem','token'))
    if not cert.exists() or not key.exists():
        subprocess.run(['openssl','req','-x509','-newkey','rsa:3072','-nodes','-keyout',str(key),
                        '-out',str(cert),'-days','1825','-subj','/CN=Halo Laptop',
                        '-addext','subjectAltName=DNS:halo.local'],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not token.exists():
        fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:file.write(secrets.token_urlsafe(32))
    for file in (cert,key,token):file.chmod(0o600)
    fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    return {'cert':cert,'key':key,'token':token.read_text().strip(),'fingerprint':fingerprint}


def signed_discovery(nonce, info):
    payload=nonce+'|'+str(PORT)+'|'+info['fingerprint']
    return {'nonce':nonce,'port':PORT,'fingerprint':info['fingerprint'],
            'signature':hmac.new(info['token'].encode(),payload.encode(),hashlib.sha256).hexdigest()}


def discover(info):
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:
        sock.bind(('0.0.0.0',DISCOVERY_PORT))
        while True:
            raw,peer=sock.recvfrom(512)
            try:
                request=json.loads(raw)
                nonce=request.get('nonce','')
                if request.get('type')!='halo-discover-1' or len(nonce)!=32 or any(c not in '0123456789abcdef' for c in nonce):continue
                sock.sendto(json.dumps(signed_discovery(nonce,info)).encode(),peer)
            except (ValueError,TypeError,OSError):continue
    finally:sock.close()


def start(handler, server_class):
    info=identity()
    class PairedHandler(handler):
        wifi=True
        def authenticated(self):
            valid=hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+info['token'])
            if not valid:
                self.close_connection=True
                self.json_response({'error':'Pair this phone with Halo on the laptop.'},401)
            return valid
        def do_GET(self):
            if self.authenticated():super().do_GET()
        def do_POST(self):
            if self.authenticated():super().do_POST()
        def do_HEAD(self):
            if self.authenticated():super().do_HEAD()
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(info['cert']),str(info['key']))
    class TLSHTTPServer(server_class):
        def get_request(self):
            connection,address=self.socket.accept()
            connection.settimeout(10)
            return tls.wrap_socket(connection,server_side=True,do_handshake_on_connect=False),address
    server=TLSHTTPServer(('0.0.0.0',PORT),PairedHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    threading.Thread(target=discover,args=(info,),daemon=True).start()
    return server


if __name__=='__main__':
    # This output contains a pairing secret. Only use in a private pipe to ADB.
    import sys
    info=identity()
    route=json.loads(subprocess.check_output(['ip','-j','route','get','1.1.1.1']))[0]
    json.dump({'name':socket.gethostname(),'host':route['prefsrc'],'port':PORT,
               'fingerprint':info['fingerprint'],'token':info['token']},sys.stdout)
