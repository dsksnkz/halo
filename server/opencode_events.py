"""Read only Halo's answer text from the authenticated local native stream."""
import base64
import http.client
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlparse


class AnswerStream:
    def __init__(self, info, session_id, publish):
        self.connection = self.response = self.socket = None
        self.closed = False
        self.session_id, self.publish = session_id, publish
        self.message_id, self.parts = None, {}
        self.changed = threading.Event()
        try:
            url = next(urlparse(u) for u in info['urls']
                       if urlparse(u).scheme == 'http' and urlparse(u).hostname == '127.0.0.1')
            # The credential remains on the laptop, never in URLs, logs,
            # subprocess arguments, browser responses, or the Android app.
            config = json.loads((Path.home()/'.config/opencode/service.json').read_text())
            auth = base64.b64encode(('opencode:'+config['password']).encode()).decode()
            self.connection = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
            self.connection.request('GET', '/api/event', headers={'Authorization':'Basic '+auth})
            self.socket = self.connection.sock
            self.response = self.connection.getresponse()
            if self.response.status != 200:
                self.close()
                return
            threading.Thread(target=self.read, daemon=True).start()
        except Exception:
            self.close()  # Polling remains the fallback if the native stream is unavailable.

    def accept(self, event):
        data = event.get('data', {})
        if data.get('sessionID') != self.session_id:
            return
        kind = event.get('type')
        if kind in ('session.execution.succeeded','session.execution.failed','session.execution.interrupted',
                    'permission.asked','permission.replied','session.tool.called','session.tool.success','session.tool.failed'):
            self.changed.set()  # Only a wake-up signal; the event body is not exposed.
        if kind not in ('session.text.started','session.text.delta','session.text.ended'):
            return  # Never expose reasoning, credentials, tool output, or another session.
        message_id = data.get('assistantMessageID')
        if message_id != self.message_id:
            self.message_id, self.parts = message_id, {}
        ordinal = data.get('ordinal',0)
        if kind == 'session.text.delta':
            self.parts[ordinal] = self.parts.get(ordinal,'') + data.get('delta','')
        elif kind == 'session.text.ended':
            self.parts[ordinal] = data.get('text','')
        self.publish('\n'.join(self.parts[k] for k in sorted(self.parts)))

    def read(self):
        try:
            while not self.closed:
                line = self.response.readline()
                if not line:
                    break
                if line.startswith(b'data: '):
                    self.accept(json.loads(line[6:]))
        except Exception:
            pass

    def close(self):
        self.closed = True
        if self.socket:
            try:self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        if self.response:self.response.close()
        if self.connection:self.connection.close()
