"""Small, in-memory companion monitor and USB reconnection worker."""
from collections import deque
from contextlib import contextmanager
import copy
import subprocess
import threading
import time

lock = threading.RLock()
messages = []
revision = 0
operations = {}
events = deque(maxlen=40)
metrics = {'requests': 0, 'last_response_ms': None, 'searches': 0,
           'wake_packets':0, 'wake_triggers':0, 'last_wake_packet_at':None}
device = {'status': 'checking', 'name': 'Phone', 'serial': None, 'linked': False}
phone_seen = 0
phone_transport = None
last_haptic = 0

def event(text):
    with lock:
        events.appendleft({'time': time.time(), 'text': text})

def phone_ping(transport='usb'):
    global phone_seen,phone_transport
    with lock:
        phone_seen = time.time()
        phone_transport = transport

def wake_packet(woke):
    with lock:
        metrics['wake_packets'] += 1
        metrics['last_wake_packet_at'] = time.time()
        if woke:
            metrics['wake_triggers'] += 1

@contextmanager
def operation(name):
    started = time.monotonic()
    with lock:
        operations[name] = operations.get(name, 0) + 1
    try:
        yield
    except Exception:
        event(name.capitalize() + ' failed')
        raise
    finally:
        with lock:
            operations[name] = max(0, operations.get(name, 1) - 1)

def begin_chat(history):
    global messages, revision
    with lock:
        messages = copy.deepcopy(history)
        revision += 1
        metrics['requests'] += 1
    event('Message received')

def finish_chat(result, elapsed):
    global revision
    with lock:
        messages.append({'role': 'assistant', 'content': result['text'], 'sources': result.get('sources', [])})
        del messages[:-48]
        revision += 1
        metrics['last_response_ms'] = round(elapsed * 1000)
        if result.get('searched'):
            metrics['searches'] += 1
    event('Reply ready' + (' with web sources' if result.get('searched') else ''))

def clear_chat():
    global revision
    with lock:
        messages.clear()
        revision += 1
    event('Conversation cleared')

def conversation():
    with lock:
        return {'messages': copy.deepcopy(messages), 'revision': revision}

def snapshot():
    with lock:
        current_device=dict(device)
        online=time.time()-phone_seen<16
        if online:
            current_device.update(linked=True,status='connected',transport=phone_transport)
        return {**conversation(), 'operations': dict(operations), 'events': list(events),
                'metrics': dict(metrics), 'device': current_device,
                'phone_online': online}

def adb(*args):
    return subprocess.run(['adb', *args], capture_output=True, text=True, timeout=6, check=True).stdout

def open_phone():
    with lock:
        serial = device.get('serial')
        linked = device.get('linked')
    if not serial or not linked:
        raise ValueError('Connect and authorize the phone first.')
    try:
        installed = adb('-s',serial,'shell','pm','path','dev.halo.phone').startswith('package:')
    except subprocess.CalledProcessError:
        installed = False
    if installed:
        adb('-s',serial,'shell','am','start','-n','dev.halo.phone/.MainActivity')
    else:
        adb('-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', 'http://127.0.0.1:8765/?companion=1')
    event('Opened Halo on phone')

def haptic():
    """A fixed short Android touch effect; no caller-supplied shell arguments."""
    global last_haptic
    with lock:
        serial = device.get('serial')
        if not serial or not device.get('linked'):
            raise ValueError('Phone USB link unavailable')
        now = time.monotonic()
        if now-last_haptic < .15:
            return
        last_haptic = now
    adb('-s',serial,'shell','cmd','vibrator_manager','synced','-d','HaloTap','oneshot','35')

def usb_worker():
    previous = None
    while True:
        try:
            lines = adb('devices', '-l').splitlines()[1:]
            rows = [line.split() for line in lines if line.strip()]
            authorized = [row for row in rows if len(row) > 1 and row[1] == 'device']
            authorized.sort(key=lambda row: 'model:NOH_AL00' not in row)
            if not authorized:
                status = 'authorization needed' if any(len(r)>1 and r[1]=='unauthorized' for r in rows) else 'disconnected'
                with lock:
                    device.update(status=status, linked=False, serial=None)
                if previous:
                    event('Phone disconnected')
                previous = None
            else:
                row = authorized[0]
                serial = row[0]
                name = next((part[6:].replace('_', ' ') for part in row if part.startswith('model:')), 'Android phone')
                # Reapply when the ADB server restarts or the cable reconnects.
                mappings = adb('-s', serial, 'reverse', '--list')
                restored = 'tcp:8765 tcp:8765' not in mappings
                if restored:
                    adb('-s', serial, 'reverse', 'tcp:8765', 'tcp:8765')
                    event('USB tunnel restored')
                with lock:
                    device.update(status='connected', name=name, serial=serial, linked=True)
                if previous != serial:
                    event('Phone connected over USB')
                    if restored:
                        open_phone()
                previous = serial
        except Exception as exc:
            with lock:
                device.update(status='connection error', linked=False)
            if previous:
                event('USB link interrupted')
            previous = None
        time.sleep(8)
