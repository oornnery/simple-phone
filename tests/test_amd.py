import unittest

from simple_phone.core.amd import Detector, by_words, words_verdict
from simple_phone.media import noise, silence, tone

FRAME = 320  # bytes in 20 ms at 8 kHz, as PJSIP delivers them


def feed(detector, pcm):
    for i in range(0, len(pcm), FRAME):
        detector.feed(pcm[i : i + FRAME])
    return (detector.result or {}).get("result")


def answered(answer_seconds=4.0, ringing=True, **limits):
    detector = Detector(**limits)
    detector.answered(answer_seconds, ringing, early_media=False)
    return detector


def decisions(detector, pcm):
    """Every result the detector published while it heard `pcm`, in order."""
    seen = []
    for i in range(0, len(pcm), FRAME):
        detector.feed(pcm[i : i + FRAME])
        result = (detector.result or {}).get("result")
        if result and (not seen or seen[-1] != result):
            seen.append(result)
    return seen


class DetectorTest(unittest.TestCase):
    def test_short_hello_then_waiting_is_human(self):
        self.assertEqual(feed(answered(), noise(0.6) + silence(1)), "human")

    def test_long_greeting_is_machine(self):
        detector = answered()
        self.assertEqual(feed(detector, noise(2)), "machine")
        self.assertIn("greeting", detector.result["reason"])

    def test_many_short_words_is_machine(self):
        words = (noise(0.2) + silence(0.1)) * 7
        detector = answered()
        self.assertEqual(feed(detector, words), "machine")
        self.assertEqual(detector.result["words"], 6)

    def test_a_quick_hello_who_is_it_is_human(self):
        # "Alo? Quem fala?": four short bursts, then waiting
        words = (noise(0.15) + silence(0.1)) * 4 + silence(1)
        self.assertEqual(feed(answered(), words), "human")

    def test_nobody_speaks(self):
        self.assertEqual(feed(answered(), silence(3)), "silence")

    def test_sit_in_early_media(self):
        detector = Detector()  # not answered yet
        sit = (
            tone(913.8, 0.274) + tone(1370.6, 0.274) + tone(1776.7, 0.38) + silence(0.1)
        )
        self.assertEqual(feed(detector, sit), "sit")
        self.assertTrue(detector.done)

    def test_beep_after_greeting_is_voicemail(self):
        audio = noise(2.5) + silence(0.5) + tone(1000, 0.5) + silence(1.2)
        self.assertEqual(feed(answered(), audio), "voicemail")

    def test_busy_tone_after_a_person_is_not_a_beep(self):
        # 425 Hz, 250 ms on and off: the far end hung up, no voicemail
        busy = (tone(425, 0.25) + silence(0.25)) * 6
        detector = answered()
        self.assertEqual(
            decisions(detector, noise(0.6) + silence(1.5) + busy), ["human"]
        )

    def test_a_long_hello_then_waiting_is_human(self):
        # "Alo, boa tarde, quem fala?": about 1.8 s with short gaps, then a pause
        hello = (noise(0.35) + silence(0.08)) * 5 + silence(2)
        self.assertEqual(feed(answered(), hello), "human")

    def test_ringback_before_answer_is_not_a_beep(self):
        detector = Detector()
        feed(detector, tone(425, 1) + silence(0.2))
        detector.answered(4.0, ringing=True, early_media=True)
        self.assertEqual(feed(detector, noise(0.6) + silence(1)), "human")

    def test_speech_is_not_a_tone(self):
        detector = answered()
        feed(detector, noise(0.6, seed=7) + silence(1))
        self.assertEqual(detector.segments, [])

    def test_fast_answer_hint(self):
        detector = Detector()
        detector.answered(0.3, ringing=False, early_media=False)
        self.assertTrue(detector.hints["fast_answer"])
        self.assertFalse(answered(4.0).hints["fast_answer"])


class LateVoiceTest(unittest.TestCase):
    """An IVR that answers mute and speaks seconds later: "silence" is
    provisional and the voice pattern starts over at the first voice."""

    def test_long_greeting_after_silence_is_machine(self):
        detector = answered()
        self.assertEqual(
            decisions(detector, silence(3) + noise(6)), ["silence", "machine"]
        )
        self.assertAlmostEqual(detector.result["leading_silence_ms"], 3000, delta=40)
        self.assertIn("after 3.0 s of silence", detector.result["reason"])

    def test_short_hello_after_silence_is_human(self):
        detector = answered()
        audio = silence(3) + noise(0.8) + silence(1.5)
        self.assertEqual(decisions(detector, audio), ["silence", "human"])

    def test_silence_to_the_end_stays_silence(self):
        detector = answered()
        self.assertEqual(decisions(detector, silence(10)), ["silence"])

    def test_a_longer_initial_silence_decides_once(self):
        detector = answered(initial_silence_ms=5000)
        self.assertEqual(decisions(detector, silence(3) + noise(6)), ["machine"])
        self.assertAlmostEqual(detector.result["leading_silence_ms"], 3000, delta=40)

    def test_limits_change_while_listening(self):
        detector = answered()
        detector.configure(greeting_ms=3000, voice_rms=200)
        self.assertEqual(decisions(detector, noise(2) + silence(1)), ["human"])

    def test_definite_results_do_not_start_over(self):
        detector = answered()
        audio = noise(0.6) + silence(1) + silence(2) + noise(3)
        self.assertEqual(decisions(detector, audio), ["human"])
        self.assertEqual(detector.result["leading_silence_ms"], 0)


class AnnouncementTest(unittest.TestCase):
    """Speech in early media, then a failure: the network played the error."""

    def test_early_speech_then_a_failure_is_an_announcement(self):
        detector = Detector()  # never answered
        feed(detector, noise(2))
        detector.unanswered(404, "Not Found")
        self.assertEqual(detector.result["result"], "sit")
        self.assertIn("then 404 Not Found", detector.result["reason"])

    def test_ringback_then_a_failure_is_not(self):
        detector = Detector()
        feed(detector, tone(425, 1) + silence(4) + tone(425, 1))
        detector.unanswered(486, "Busy Here")
        self.assertIsNone(detector.result)

    def test_a_click_is_not_an_announcement(self):
        detector = Detector()
        feed(detector, noise(0.3))
        detector.unanswered(480, "Temporarily Unavailable")
        self.assertIsNone(detector.result)


class WordsTest(unittest.TestCase):
    def test_phrases_in_portuguese_and_english(self):
        for text, result in (
            ("Deixe sua mensagem após o sinal.", "voicemail"),
            ("Please leave a message after the tone.", "voicemail"),
            ("O número chamado não existe.", "sit"),
            ("The number you have dialed is not in service.", "sit"),
            ("Para segunda via, digite 1.", "ivr"),
            ("For billing, press 1.", "ivr"),
        ):
            with self.subTest(text):
                self.assertEqual(words_verdict(text)[0], result)

    def test_voicemail_wins_over_not_available(self):
        text = "Não estou disponível agora, deixe seu recado."
        self.assertEqual(words_verdict(text)[0], "voicemail")

    def test_words_correct_the_sound_but_not_tones(self):
        machine = {"result": "machine", "reason": "3 words", "after_ms": 2960}
        better = by_words(machine, "Deixe sua mensagem após o sinal.")
        self.assertEqual((better["result"], better["after_ms"]), ("voicemail", 2960))
        self.assertIsNone(by_words(machine, "Alô?"))
        sit = {"result": "sit", "reason": "SIT tones"}
        self.assertIsNone(by_words(sit, "Digite 1"))

    def test_whole_words_only(self):
        self.assertIsNone(words_verdict("Sua impressão foi enviada."))  # not "press"
        self.assertIsNone(words_verdict("Alô, quem fala?"))


if __name__ == "__main__":
    unittest.main()
