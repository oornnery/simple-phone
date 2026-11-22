import array
import math
import random
import unittest

from simple_phone.core.amd import Detector

RATE, FRAME = 8000, 160  # 20 ms frames, as PJSIP delivers them


def tone(freq, ms, amplitude=8000):
    return [
        int(amplitude * math.sin(2 * math.pi * freq * i / RATE))
        for i in range(RATE * ms // 1000)
    ]


def speech(ms, seed=1):
    # Broadband noise: loud like speech, but no single frequency.
    rng = random.Random(seed)
    return [int(rng.gauss(0, 3000)) for _ in range(RATE * ms // 1000)]


def silence(ms):
    return [0] * (RATE * ms // 1000)


def feed(detector, samples):
    for i in range(0, len(samples), FRAME):
        detector.feed(array.array("h", samples[i : i + FRAME]).tobytes())
    return (detector.result or {}).get("result")


def answered(answer_seconds=4.0, ringing=True):
    detector = Detector()
    detector.answered(answer_seconds, ringing, early_media=False)
    return detector


class DetectorTest(unittest.TestCase):
    def test_short_hello_then_waiting_is_human(self):
        self.assertEqual(feed(answered(), speech(600) + silence(1000)), "human")

    def test_long_greeting_is_machine(self):
        detector = answered()
        self.assertEqual(feed(detector, speech(2000)), "machine")
        self.assertIn("greeting", detector.result["reason"])

    def test_many_short_words_is_machine(self):
        words = (speech(200) + silence(100)) * 4
        detector = answered()
        self.assertEqual(feed(detector, words), "machine")
        self.assertEqual(detector.result["words"], 3)

    def test_nobody_speaks(self):
        self.assertEqual(feed(answered(), silence(3000)), "silence")

    def test_sit_in_early_media(self):
        detector = Detector()  # not answered yet
        sit = tone(913.8, 274) + tone(1370.6, 274) + tone(1776.7, 380) + silence(100)
        self.assertEqual(feed(detector, sit), "sit")
        self.assertTrue(detector.done)

    def test_beep_after_greeting_is_voicemail(self):
        audio = speech(2000) + silence(500) + tone(1000, 500) + silence(300)
        self.assertEqual(feed(answered(), audio), "voicemail")

    def test_ringback_before_answer_is_not_a_beep(self):
        detector = Detector()
        feed(detector, tone(425, 1000) + silence(200))
        detector.answered(4.0, ringing=True, early_media=True)
        self.assertEqual(feed(detector, speech(600) + silence(1000)), "human")

    def test_speech_is_not_a_tone(self):
        detector = answered()
        feed(detector, speech(600, seed=7) + silence(1000))
        self.assertEqual(detector.segments, [])

    def test_fast_answer_hint(self):
        detector = Detector()
        detector.answered(0.3, ringing=False, early_media=False)
        self.assertTrue(detector.hints["fast_answer"])
        self.assertFalse(answered(4.0).hints["fast_answer"])


if __name__ == "__main__":
    unittest.main()
