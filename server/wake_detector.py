"""Local Halo wake word. Vosk spots candidates, Whisper confirms them.
PCM and transcripts are never stored or logged."""
from collections import OrderedDict
import json
from pathlib import Path
import re
import threading
import time
import numpy as np

_lock = threading.Lock()
_model = None
_sessions = OrderedDict()
# Keep acoustically similar competitors so "hello" is not forced into Halo.
_GRAMMAR = json.dumps(['halo','hey halo','hey low','hay low','hello','hey hello','yellow','hollow','[unk]'])
_WINDOW = 32000  # last two seconds at 16 kHz
# Whisper sometimes spells the name "Kalo" or "Hallo"; "hello" never matches.
_NAME = re.compile(r'\b(?:[hk]a+y?l+o+s?|hey,? low)\b')
# Set by the server: float32 16 kHz audio -> transcript, using the shared Whisper.
verifier = None


def _spotted(words):
    return 'halo' in words or words[:2] in (['hey','low'],['hay','low'])


def detect(audio, session, reset=False):
    global _model
    if not audio or len(audio)%2560 or len(audio)>40960:
        raise ValueError('Expected 16 kHz mono int16 PCM in 80ms frames')
    with _lock:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        if _model is None:
            _model = Model(str(Path(__file__).resolve().parents[1]/'models/vosk-model-small-en-us-0.15'))
        now = time.monotonic()
        state = _sessions.get(session)
        if state is None or reset or now-state['last_packet']>3:
            state = {'recognizer':KaldiRecognizer(_model,16000,_GRAMMAR),'last_packet':now,
                     'buffer':np.zeros(0,dtype=np.float32),'waiting':None,'tries':0}
            _sessions[session] = state
        _sessions.move_to_end(session)
        while len(_sessions)>6:
            _sessions.popitem(last=False)
        state['last_packet'] = now
        samples = np.frombuffer(audio,dtype='<i2').astype(np.float32)/32768
        state['buffer'] = np.concatenate([state['buffer'],samples])[-_WINDOW:]
        recognizer = state['recognizer']
        final = recognizer.AcceptWaveform(audio)
        result = json.loads(recognizer.Result() if final else recognizer.PartialResult())
        if state['waiting'] is None:
            if not _spotted(result.get('text',result.get('partial','')).split()):
                return {'wake':False}
            # Let the word finish in the next packet before confirming it.
            state['waiting'],state['tries'] = 1,0
            return {'wake':False}
        buffer = state['buffer']
    # Confirm outside the lock so one phone's check never stalls another.
    woke = verifier is not None and bool(_NAME.search(verifier(buffer).lower()))
    with _lock:
        state['tries'] += 1
        if woke or state['tries']>=2:
            # Done with this candidate either way; start listening afresh.
            state['recognizer'].Reset()
            state['waiting'] = None
            if woke:state['buffer'] = np.zeros(0,dtype=np.float32)
    return {'wake':woke}
