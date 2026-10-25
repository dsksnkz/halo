#!/usr/bin/env python3
"""Paired Halo dashboard, local OpenCode AI and speech over Wi-Fi or USB."""
import base64
import fcntl
import http.client
import json
import os
from pathlib import Path
import pty
import select
import re
import socket
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
import urllib.request
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import companion_state as monitor

ROOT = Path(__file__).resolve().parent
from opencode_backend import MODEL, DISPLAY_NAME
SESSION_ID = uuid.uuid4().hex
OLLAMA = 'http://127.0.0.1:11434'
voice_lock = threading.Lock()
chat_lock = threading.Lock()
whisper = None
speaker = None
tts_lock = threading.Lock()
stats_cache = {}

def ollama(path, body=None, timeout=10):
    if body and body.get('stream'):
        return streamed_reply(path, body, timeout)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(OLLAMA + path, data=data, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)

def streamed_reply(path, body, timeout):
    """Cancel model generation at the wall-clock deadline, including cold loads."""
    deadline = time.monotonic()+timeout
    connection = http.client.HTTPConnection('127.0.0.1',11434,timeout=timeout)
    response = None
    chunks = []
    finished = False
    try:
        connection.request('POST',path,body=json.dumps(body),headers={'Content-Type':'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Local model request failed')
        while time.monotonic()<deadline:
            if connection.sock:
                connection.sock.settimeout(max(.01,deadline-time.monotonic()))
            raw = response.readline()
            if not raw:
                break
            item = json.loads(raw)
            if item.get('error'):
                raise ValueError(item['error'])
            chunks.append(item.get('message',{}).get('content',''))
            if item.get('done'):
                finished = True
                break
    except (socket.timeout, TimeoutError):
        pass
    finally:
        if response is not None:
            response.close()
        connection.close()
    text = ''.join(chunks).strip()
    if not finished:
        sentences = re.findall(r'.*?[.!?](?:\s|$)',text,re.S)
        text = ''.join(sentences).strip()
    return {'message':{'content':text},'deadline_reached':not finished}

def load_whisper():
    """small.en on the GPU (~450 MB VRAM, ~6x faster); CPU if CUDA is unavailable."""
    from faster_whisper import WhisperModel
    try:
        import ctypes
        # Optional: a directory holding CUDA 12 cuBLAS (e.g. Ollama's bundled copy).
        cuda = os.environ.get('HALO_CUDA_LIBS')
        for name in ('libcublasLt.so.12','libcublas.so.12') if cuda else ():
            ctypes.CDLL(str(Path(cuda) / name), mode=ctypes.RTLD_GLOBAL)
        model = WhisperModel('small.en', device='cuda', compute_type='int8_float16')
        list(model.transcribe(__import__('numpy').zeros(16000, dtype='float32'), language='en')[0])
        monitor.event('Speech recognition on GPU')
        return model
    except Exception:
        monitor.event('Speech recognition on CPU')
        return WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=4)

def verify_wake(audio):
    """Transcribe a two-second wake candidate with the shared Whisper model."""
    global whisper
    with voice_lock:
        if whisper is None:
            whisper = load_whisper()
        segments, _ = whisper.transcribe(audio, language='en', beam_size=1, temperature=0.0, hotwords='Halo', condition_on_previous_text=False, without_timestamps=True, vad_filter=False)
        return ' '.join(s.text.strip() for s in segments)

def warm_worker():
    """Warm local speech; OpenCode owns its model connection."""
    global whisper, speaker
    try:
        with voice_lock:
            if whisper is None:
                whisper = load_whisper()
        with tts_lock:
            from voice import HaloVoice
            if speaker is None:
                speaker = HaloVoice()
            speaker.synthesize('Ready.')
        monitor.event('Speech engines ready for OpenCode')
        # Gemini needs no local load or prompt warm-up; skipping it saves a
        # free-tier request on every dashboard restart.
    except Exception:
        monitor.event('Speech warmup unavailable')

def stats_worker():
    global stats_cache
    while True:
        try:
            raw = json.loads(subprocess.check_output(['fastfetch','--logo','none','--structure','OS:Kernel:Uptime:Memory:WM','--format','json'], timeout=5))
            data = {r['type']:r.get('result', {}) for r in raw}
            try:
                from opencode_backend import available
                ready = available()
            except Exception:
                ready = False
            stats_cache = {'system':data, 'ready':ready, 'model':MODEL, 'session_id':SESSION_ID,'provider':'google','model_label':DISPLAY_NAME,'agent_enabled':True}
        except Exception as exc:
            stats_cache = {'error':str(exc), 'ready':False}
        time.sleep(5)

class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'static'), **kwargs)

    def log_message(self, format, *args):
        if self.path not in ('/api/stats', '/api/wake'):
            super().log_message(format, *args)

    def json_response(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == '/api/link':
            return self.json_response({'ok':True,'transport':'wifi' if getattr(self,'wifi',False) else 'usb'})
        if route.path == '/api/stats':
            if getattr(self,'wifi',False) or self.headers.get('X-Halo-Phone')=='1':
                monitor.phone_ping('wifi' if getattr(self,'wifi',False) else 'usb')
            return self.json_response({**stats_cache, 'conversation':monitor.conversation()})
        if route.path == '/api/agent':
            from opencode_backend import status
            return self.json_response(status())
        if route.path == '/api/companion':
            from opencode_backend import status
            return self.json_response({**monitor.snapshot(), **stats_cache, 'agent':status()})
        if route.path == '/api/music':
            import music
            return self.json_response(music.state())
        if route.path == '/api/music/art':
            import music
            cover = music.art()
            if not cover:
                return self.json_response({'error':'No album art'},404)
            data, kind = cover
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)))
            # The URL carries the cover's hash, so a cached copy is always right.
            self.send_header('Cache-Control','private, max-age=86400')
            self.end_headers()
            self.wfile.write(data)
            return
        if route.path == '/api/cava':
            config = 'cava-music.conf' if parse_qs(route.query).get('music') == ['1'] else 'cava-raw.conf'
            process = subprocess.Popen(['cava','-p',str(ROOT / config)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close')
            self.end_headers()
            self.close_connection = True
            try:
                for line in process.stdout:
                    try:
                        values = [max(0,min(100,int(value))) for value in line.decode().strip().split(';') if value]
                    except ValueError:
                        continue
                    self.wfile.write(b'data: '+json.dumps(values).encode()+b'\n\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.terminate()
                process.wait(timeout=5)
            return
        if route.path == '/api/lava':
            args = parse_qs(route.query)
            cols = max(20, min(320, int(args.get('cols',['60'])[0])))
            rows = max(8, min(120, int(args.get('rows',['25'])[0])))
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
            mode = args.get('mode',['lavat'])[0]
            commands = {'lavat':'lavat -c white -s 3 -r 3 -b 5 -C','cava':f'cava -p {ROOT}/cava.conf','pipes':'pipes.sh -p 3 -t 0 -c 7 -f 20 -B','clock':'tty-clock -c -C 7 -s -D'}
            if mode not in commands:
                os.close(master)
                os.close(slave)
                return self.json_response({'error':'Unknown visualizer'},400)
            process = subprocess.Popen(['script','-q','-c',commands[mode],'/dev/null'], stdin=slave, stdout=slave, stderr=slave, start_new_session=True, env={**os.environ,'TERM':'xterm-256color'})
            os.close(slave)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close')
            self.end_headers()
            self.close_connection = True
            try:
                while process.poll() is None:
                    if select.select([master],[],[],2)[0]:
                        payload = os.read(master,65536)
                        if not payload:
                            break
                        self.wfile.write(b'data: '+base64.b64encode(payload)+b'\n\n')
                    else:
                        self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except ProcessLookupError:
                    pass
                os.close(master)
            return
        super().do_GET()

    def do_POST(self):
        # Browser requests must come from this local page. No permissive CORS.
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:8766','http://127.0.0.1:8769'):
            return self.json_response({'error':'Origin refused'},403)
        size = int(self.headers.get('Content-Length','0'))
        if size > 8_000_000:
            return self.json_response({'error':'Recording too large; keep it under one minute.'},413)
        body = self.rfile.read(size)
        try:
            if self.path == '/api/device/haptic':
                monitor.haptic()
                return self.json_response({'ok':True})
            if self.path == '/api/agent/cancel':
                from opencode_backend import cancel
                cancel()
                return self.json_response({'ok':True})
            if self.path == '/api/agent/permission':
                from opencode_backend import permission_reply
                request=json.loads(body)
                permission_reply(request['id'],request.get('allow') is True)
                return self.json_response({'ok':True})
            if self.path == '/api/music/control':
                import music
                request = json.loads(body)
                try:
                    return self.json_response(music.control(str(request.get('action')), request.get('value')))
                except ValueError as exc:
                    return self.json_response({'error':str(exc)},409)
            if self.path == '/api/device/open':
                monitor.open_phone()
                return self.json_response({'ok':True})
            if self.path == '/api/conversation/clear':
                if not chat_lock.acquire(blocking=False):
                    return self.json_response({'error':'Wait for the current reply before clearing.'},409)
                try:
                    from opencode_backend import reset
                    reset()
                    monitor.clear_chat()
                finally:
                    chat_lock.release()
                return self.json_response({'ok':True})
            if self.path == '/api/wake':
                import wake_detector
                if wake_detector.verifier is None:
                    wake_detector.verifier = verify_wake
                detect = wake_detector.detect
                result = detect(body, self.headers.get('X-Wake-Session','default'), self.headers.get('X-Wake-Reset') == '1')
                monitor.wake_packet(result['wake'])
                if result['wake']:
                    monitor.event('Halo wake word detected')
                return self.json_response(result)
            if self.path == '/api/speak':
                global speaker
                text = str(json.loads(body).get('text',''))[:4000]
                with monitor.operation('voice'), tts_lock:
                    from voice import HaloVoice
                    if speaker is None:
                        speaker = HaloVoice()
                    payload = speaker.synthesize(text)
                self.send_response(200)
                self.send_header('Content-Type','audio/wav')
                self.send_header('Content-Length',str(len(payload)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path == '/api/transcribe':
                global whisper
                with monitor.operation('transcription'), voice_lock:
                    if whisper is None:
                        whisper = load_whisper()
                    with tempfile.NamedTemporaryFile(suffix='.webm') as clip:
                        clip.write(body)
                        clip.flush()
                        def transcribe():
                            segments, _ = whisper.transcribe(clip.name, language='en', beam_size=5, best_of=1, patience=1.2, hotwords='Halo OpenCode Gemini Hyprland Arch Linux Firefox Chrome Steam terminal', temperature=0.0, condition_on_previous_text=False, vad_filter=True, vad_parameters={'min_silence_duration_ms':400,'speech_pad_ms':400})
                            return ' '.join(s.text.strip() for s in segments).strip()
                        try:
                            transcript = transcribe()
                        except RuntimeError:
                            # GPU memory can vanish under a game; finish this clip on the CPU.
                            from faster_whisper import WhisperModel
                            whisper = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=4)
                            monitor.event('Speech recognition moved to CPU')
                            transcript = transcribe()
                return self.json_response({'text':transcript})
            if self.path == '/api/chat':
                request = json.loads(body)
                history = request.get('messages', [])[-12:]
                if not history or any(m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) for m in history):
                    return self.json_response({'error':'Invalid conversation'},400)
                history = [{'role':m['role'],'content':m['content'][:6000]} for m in history]
                if request.get('session_id') != SESSION_ID:
                    history = [message for message in history if message['role']=='user'][-1:]
                if not history:
                    return self.json_response({'error':'A user message is required'},400)
                from opencode_backend import answer
                if not chat_lock.acquire(blocking=False):
                    return self.json_response({'error':'Halo is already answering. Wait for the current reply.'},409)
                try:
                    started = time.monotonic()
                    monitor.begin_chat(history)
                    with monitor.operation('model'):
                        result = answer(history,request.get('web',True) is True)
                    monitor.finish_chat(result, time.monotonic()-started)
                finally:
                    chat_lock.release()
                return self.json_response({**result,'session_id':SESSION_ID})
            return self.json_response({'error':'Unknown endpoint'},404)
        except Exception as exc:
            return self.json_response({'error':str(exc)},503)

if __name__ == '__main__':
    from wifi_link import start as start_wifi
    start_wifi(Handler,ThreadingHTTPServer)
    threading.Thread(target=stats_worker, daemon=True).start()
    threading.Thread(target=monitor.usb_worker, daemon=True).start()
    threading.Thread(target=warm_worker, daemon=True).start()
    print('JARVIS: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765), Handler).serve_forever()
