import unittest
import threading
import time
try:
    from models import finish_generation
except ImportError:
    finish_generation=None
try:
    from models import checked_input, pcm16, non_silent_sample
except ImportError:
    checked_input = pcm16 = non_silent_sample = None


class ModelBoundaries(unittest.TestCase):
    def test_normal_stream_end_does_not_cancel_downstream_tts(self):
        self.assertIsNotNone(finish_generation)
        stop=threading.Event()
        thread=threading.Thread(target=lambda:time.sleep(.04))
        thread.start()
        finish_generation(thread,stop,exhausted=True)
        self.assertFalse(stop.is_set())
        self.assertFalse(thread.is_alive())

    def test_abandoned_stream_stops_generator_before_join(self):
        self.assertIsNotNone(finish_generation)
        stop=threading.Event();noticed=[]
        thread=threading.Thread(target=lambda:noticed.append(stop.wait(.5)))
        thread.start()
        finish_generation(thread,stop,exhausted=False)
        self.assertEqual(noticed,[True])
        self.assertFalse(thread.is_alive())

    def test_overlong_audio_cannot_be_silently_truncated(self):
        self.assertIsNotNone(checked_input)
        self.assertEqual(checked_input(b'\x00\x00'*16000),16000)
        for data in (b'\x00', b'', b'\x00\x00' * 240001):
            with self.assertRaises(ValueError):
                checked_input(data)

    def test_float_audio_is_clipped_before_pcm_conversion(self):
        self.assertIsNotNone(pcm16)
        import struct
        self.assertEqual(struct.unpack('<hhh',pcm16([-2.,0.,2.])),(-32767,0,32767))

    def test_leading_silence_not_audible_first_sample(self):
        self.assertIsNotNone(non_silent_sample)
        self.assertIsNone(non_silent_sample([0.,0.]))
        self.assertEqual(non_silent_sample([0.,.001,.02]),2)


if __name__ == '__main__': unittest.main()
