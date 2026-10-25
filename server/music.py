"""Now playing for the Halo music screen: MPRIS through playerctl, no extra services."""
import hashlib
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from urllib.parse import unquote, urlparse

FIELDS = ('playerName','status','title','artist','album','mpris:artUrl','mpris:length','position','mpris:trackid','shuffle','loop')
LOOPS = ('None','Playlist','Track')
# Album art may only come from where players actually cache it.
ART_DIRS = (Path('/tmp'), Path.home()/'.cache', Path.home()/'.local/share')
_lock = threading.Lock()
_cache = {'at':0, 'value':None}
_art = {'url':None, 'data':None, 'type':None}
_support = {}


def _run(*args):
    return subprocess.run(['playerctl',*args], capture_output=True, text=True, timeout=3)


def _supports(player, feature):
    # Chromium, for one, has no shuffle or repeat; ask each player once.
    key = (player, feature)
    if key not in _support:
        _support[key] = _run('-p', player, feature).returncode == 0
    return _support[key]


def _number(value, scale):
    try:return round(int(value)/scale, 3)
    except ValueError:return 0


def _current():
    out = _run('-a', 'metadata', '--format', '\t'.join('{{'+field+'}}' for field in FIELDS)).stdout
    rows = [dict(zip(FIELDS, line.split('\t'))) for line in out.splitlines() if line.count('\t') == len(FIELDS)-1]
    rank = {'Playing':0, 'Paused':1}
    return min(rows, key=lambda row:rank.get(row['status'], 2)) if rows else None


def state(fresh=False):
    with _lock:
        if not fresh and time.monotonic()-_cache['at'] < .25:
            return _cache['value']
        row = _current()
        if row is None:
            value = {'active':False}
            _art['pending'] = None
        else:
            player = row['playerName']
            art = row['mpris:artUrl']
            value = {'active':True, 'player':player, 'status':row['status'], 'title':row['title'],
                     'artist':row['artist'], 'album':row['album'], 'track':row['mpris:trackid'],
                     'length':_number(row['mpris:length'], 1e6), 'position':_number(row['position'], 1e6),
                     'shuffle':row['shuffle'] == 'true', 'loop':row['loop'] if row['loop'] in LOOPS else 'None',
                     'can_shuffle':_supports(player, 'shuffle'), 'can_loop':_supports(player, 'loop'),
                     'art':hashlib.sha1(art.encode()).hexdigest()[:12] if art else None,
                     'sampled':time.time()}
            _art['pending'] = art
        _cache.update(at=time.monotonic(), value=value)
        return value


def _image_type(data):
    for magic, kind in ((b'\x89PNG','image/png'), (b'\xff\xd8\xff','image/jpeg'), (b'GIF8','image/gif')):
        if data.startswith(magic):return kind
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':return 'image/webp'
    return None


def art():
    """Bytes and type of the current cover, or None."""
    state()
    url = _art.get('pending')
    if not url:return None
    with _lock:
        if _art['url'] == url:
            return _art['data'], _art['type']
    parsed = urlparse(url)
    if parsed.scheme == 'file':
        path = Path(unquote(parsed.path)).resolve()
        if not any(path.is_relative_to(root) for root in ART_DIRS) or not path.is_file() or path.stat().st_size > 8_000_000:
            return None
        data = path.read_bytes()
    elif parsed.scheme in ('http','https'):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Halo'}), timeout=4) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000:return None
    else:
        return None
    kind = _image_type(data)
    if not kind:return None
    with _lock:
        _art.update(url=url, data=data, type=kind)
    return data, kind


def control(action, value=None):
    current = state(fresh=True)
    if not current.get('active'):
        raise ValueError('Nothing is playing.')
    player = current['player']
    commands = {'toggle':['play-pause'], 'next':['next'], 'previous':['previous'], 'shuffle':['shuffle','Toggle']}
    if action == 'loop':
        command = ['loop', LOOPS[(LOOPS.index(current['loop'])+1) % len(LOOPS)]]
    elif action == 'seek':
        command = ['position', str(max(0, min(float(value), current['length'] or float(value))))]
    elif action in commands:
        command = commands[action]
    else:
        raise ValueError('Unknown music control.')
    if _run('-p', player, *command).returncode:
        raise ValueError('This player does not support that control.')
    time.sleep(.12)  # let the player publish its new state
    return state(fresh=True)
