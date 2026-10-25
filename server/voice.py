"""CPU Kokoro voice with fractional-speed support for the v1.1 ONNX export."""
from pathlib import Path
import io
import wave
from functools import lru_cache
import numpy as np
import onnxruntime as ort
from kokoro_onnx import Kokoro
from kokoro_onnx.config import MAX_PHONEME_LENGTH, SAMPLE_RATE
from reply_text import spoken

class FractionalSpeedKokoro(Kokoro):
    def _create_audio(self, phonemes, voice, speed):
        # kokoro-onnx 0.4.7 casts this newer export's float speed to int32.
        tokens = self.tokenizer.tokenize(phonemes[:MAX_PHONEME_LENGTH])
        inputs = {'input_ids':np.asarray([[0,*tokens,0]],dtype=np.int64),
                  'style':np.asarray(voice[len(tokens)],dtype=np.float32),
                  'speed':np.asarray([speed],dtype=np.float32)}
        return self.sess.run(None,inputs)[0], SAMPLE_RATE

class HaloVoice:
    def __init__(self):
        root = Path(__file__).resolve().parents[1] / 'models/kokoro'
        options = ort.SessionOptions()
        options.intra_op_num_threads = 8  # 8 physical cores; Nice=10 keeps games ahead
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        session = ort.InferenceSession(str(root / 'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.engine = FractionalSpeedKokoro.from_session(session,str(root / 'voices.bin'))

    def synthesize(self,text):
        text = spoken(text)
        if not text:
            return b''
        return self._render(text)

    @lru_cache(maxsize=24)
    def _render(self,text):
        samples, rate = self.engine.create(text,voice='am_michael',speed=1.08,lang='en-us')
        audio = io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
        return audio.getvalue()
