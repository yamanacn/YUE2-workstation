import hashlib
import unittest

from .abc_processor import ABCReferenceProcessor


ABC = """X:1
T:Strength test
M:4/4
L:1/8
K:C
C D E F G A B c | c B A G F E D C ||
"""


class ReferenceStrengthTests(unittest.TestCase):
    def test_supported_strengths_differ_and_are_deterministic(self):
        processor = ABCReferenceProcessor()
        outputs = {}
        output_notes = {}
        for name in ("free", "balanced", "faithful"):
            outputs[name] = processor.process(ABC, name)
            output_notes[name] = processor.last_stats["outputNotes"]
        self.assertNotEqual(outputs["free"], outputs["balanced"])
        self.assertNotEqual(outputs["balanced"], outputs["faithful"])
        self.assertLess(output_notes["free"], output_notes["balanced"])
        self.assertLess(output_notes["balanced"], output_notes["faithful"])
        self.assertEqual(outputs["free"], processor.process(ABC, "free"))
        self.assertEqual(outputs["balanced"], processor.process(ABC, "balanced"))
        self.assertEqual(outputs["faithful"], ABC)

    def test_header_default_length_and_explicit_durations_are_validated(self):
        raw = """M:4/4
L:1/8
K:C
C2 D/2 E/2 F G A B c |
"""
        processor = ABCReferenceProcessor()
        parsed = processor.parser.parse_document(raw).measures[0]
        self.assertEqual(sum(event.duration for event in parsed.events), 1)
        self.assertEqual(parsed.events[0].duration, 1 / 4)
        self.assertEqual(parsed.events[1].duration, 1 / 16)
        result = processor.process(raw, "balanced")
        self.assertEqual(
            sum(event.duration for event in processor.parser.parse_document(result).measures[0].events),
            1,
        )

    def test_transforms_preserve_bar_duration_and_phrase_boundaries(self):
        processor = ABCReferenceProcessor()
        raw_measures = processor.parser.parse_document(ABC).measures
        for strength in ("free", "balanced"):
            result = processor.process(ABC, strength)
            parsed = processor.parser.parse_document(result).measures
            self.assertEqual(len(parsed), len(raw_measures))
            self.assertEqual(
                [measure.is_phrase_end for measure in parsed],
                [measure.is_phrase_end for measure in raw_measures],
            )
            for raw_measure, output_measure in zip(raw_measures, parsed):
                self.assertEqual(
                    sum(event.duration for event in raw_measure.events),
                    sum(event.duration for event in output_measure.events),
                )
            self.assertTrue(processor.last_stats["durationPreserved"])
            self.assertEqual(processor.last_stats["outputMeasures"], 2)

    def test_unsupported_constructs_fall_back_with_explicit_reason(self):
        unsupported = (
            ABC.replace("C D E F", '"C" z2 D E')
            , ABC.replace("C D E F", "[CEG] z2 D E")
            , ABC.replace("C D E F", "(3CDE F")
            , ABC.replace("C D E F", "C D E F |: G A B c ||")
            , ABC.replace("C D E F", "C D E F :|")
            , ABC.replace("K:C\n", "V:Voice\nK:C\n")
            , ABC.replace("M:4/4", "M:not/4")
            , ABC.replace("C D E F", "C D E")
        )
        processor = ABCReferenceProcessor()
        for raw in unsupported:
            self.assertEqual(processor.process(raw, "balanced"), raw)
            self.assertTrue(processor.last_stats["degraded"])
            self.assertTrue(processor.last_stats["unchanged"])
            self.assertTrue(processor.last_stats["durationPreserved"])
            self.assertEqual(processor.last_stats["reason"], "unsupported_construct")

    def test_faithful_is_byte_identical_for_supported_and_unsupported_input(self):
        processor = ABCReferenceProcessor()
        self.assertEqual(processor.process(ABC, "faithful"), ABC)
        self.assertEqual(
            hashlib.sha256(processor.process(ABC, "faithful").encode("utf-8")).digest(),
            hashlib.sha256(ABC.encode("utf-8")).digest(),
        )
        raw = ABC.replace("C D E F", "[CEG] z2 D E")
        self.assertEqual(processor.process(raw, "faithful"), raw)
        self.assertTrue(processor.last_stats["degraded"])
        self.assertEqual(processor.last_stats["reason"], "unsupported_construct")

    def test_legacy_third_argument_is_ignored_without_filtering(self):
        processor = ABCReferenceProcessor()
        self.assertEqual(processor.process(ABC, "faithful", {"m0_n0": 0}), ABC)
        self.assertFalse(processor.last_stats["degraded"])

    def test_invalid_strength_falls_back_to_balanced(self):
        processor = ABCReferenceProcessor()
        self.assertEqual(processor.normalize_strength("unknown"), "balanced")
        self.assertEqual(
            processor.process(ABC, "unknown"),
            processor.process(ABC, "balanced"),
        )


if __name__ == "__main__":
    unittest.main()
