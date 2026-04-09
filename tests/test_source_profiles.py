import unittest

import numpy as np

from realtime_translator import LATENCY_PROFILES
from rtxlator.source_profiles import apply_source_profile, prepare_audio_for_asr


class SourceProfileTests(unittest.TestCase):
    def test_system_profile_is_more_forgiving_than_default(self):
        tuned = apply_source_profile(LATENCY_PROFILES["ultra"], "system")
        self.assertGreater(tuned.buffer_min_s, LATENCY_PROFILES["ultra"].buffer_min_s)
        self.assertGreaterEqual(tuned.silence_chunks, LATENCY_PROFILES["ultra"].silence_chunks)
        self.assertTrue(tuned.whisper_vad)

    def test_system_audio_normalization_boosts_low_signal(self):
        audio = np.full(1600, 0.02, dtype=np.float32)
        boosted = prepare_audio_for_asr(audio, "system")
        self.assertGreater(float(np.max(np.abs(boosted))), float(np.max(np.abs(audio))))


if __name__ == "__main__":
    unittest.main()
