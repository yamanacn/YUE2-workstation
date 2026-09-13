import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from .instrumental import mute_vocal,generate,compensate_melody,abc_tools,recover_score,normalize_instrumental_score


def score(vocal='"C"C16-"Am7"C16|', ins='E32|'):
    return ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=88\n'
        'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
        'V: Ins clef=treble name="Ins Melody" snm="Inst."\n'
        'K:C\n% verse\nV: Vocal\n'+vocal+'\nV: Ins\n'+ins+'\n')

class InstrumentalTests(unittest.TestCase):
    def test_provided_score_normalizes_voice_headers_and_long_groups(self):
        before=('X:1\nT:\nM:4/4\nL:1/16\nQ:1/4=104\n'
            'V: Vocal clef=treble snm=Vocal\nV: Ins clef=treble snm=Inst.\nK:Fm\n'
            '% verse\nV: Vocal\nF16|G16|A16|B16|c16|B16|A16|G16|\nV: Ins\nZ8|\n')
        normalized,audit=normalize_instrumental_score(before)
        parsed=abc_tools().parse(normalized)
        self.assertEqual(len(parsed.voices['Vocal'].bars),8)
        self.assertEqual(len(parsed.voices['Ins'].bars),8)
        self.assertIn('name="Vocal Melody"',normalized)
        self.assertNotIn('Z8|',normalized)
        self.assertTrue(audit['voiceHeadersNormalized'])
        self.assertEqual(audit['groupsRechunked'],1)
        self.assertEqual(audit['expandedRestMeasures'],7)

    def test_provided_score_removes_only_mismatched_ties(self):
        before=('X:1\nT:\nM:4/4\nL:1/16\nQ:1/4=104\n'
            'V: Vocal clef=treble snm=Vocal\nV: Ins clef=treble snm=Inst.\nK:Fm\n'
            '% chorus\nV: Vocal\nF8-F8|F2- A2 F4 z8|\nV: Ins\nZ2|\n')
        normalized,audit=normalize_instrumental_score(before)
        self.assertIn('F8-F8|',normalized)
        self.assertIn('F2 A2',normalized)
        self.assertEqual(audit['invalidTiesRemoved'],1)
        abc_tools().parse(normalized)

    def test_provided_instrumental_score_reaches_native_generation(self):
        provided=('X:1\nT:\nM:4/4\nL:1/16\nQ:1/4=104\n'
            'V: Vocal clef=treble snm=Vocal\nV: Ins clef=treble snm=Inst.\nK:Fm\n'
            '% verse\nV: Vocal\nF16|G16|A16|B16|c16|B16|A16|G16|\nV: Ins\nZ8|\n')
        with tempfile.TemporaryDirectory() as tmp:
            pipe=Mock();pipe.plan.return_value=SimpleNamespace(abc=provided,truncated=False,timing={})
            generate(pipe,{'style':'instrumental','lyrics':'','abc':provided,'cot':'melody'},'instrumental',Path(tmp),Mock(),Mock())
            output=pipe.call_args.kwargs['abc']
            self.assertEqual(abc_tools().parse(output).voices['Vocal'].notes,[])
            self.assertEqual(len(abc_tools().parse(output).voices['Ins'].notes),8)
            audit=(Path(tmp)/'instrumental-transform.json').read_text(encoding='utf-8')
            self.assertIn('"scoreNormalization":"canonicalized"',audit)

    def test_ties_chords_and_instrumental_preserved(self):
        before=score(); after,audit=mute_vocal(before)
        self.assertEqual(after,before.replace('"C"C16-"Am7"C16|','"C"z16"Am7"z16|'))
        self.assertEqual(audit['vocalNotesAfter'],0)
        self.assertEqual(audit['chordsPreserved'],2)
    def test_accidentals_crossbar_ties_and_compressed_rests(self):
        after,_=mute_vocal(score('^F32-|F8F24|','Z2|'))
        self.assertIn('z32|z8z24|', after); self.assertIn('Z2|', after)
    def test_invalid_score_rejected(self):
        with self.assertRaises(ValueError): mute_vocal(score('C16|'))
    def test_explicit_selection_and_off_bypass(self):
        for mode,cot in [('male','full'),('female','melody'),(None,'full'),('instrumental','off')]:
            pipe=Mock();kwargs={'cot':cot,'lyrics':''}
            generate(pipe,kwargs,mode,None,Mock(),Mock())
            pipe.plan.assert_not_called();pipe.assert_called_once_with(**kwargs)
    def test_external_abc_and_lyrics_preserved(self):
        for cot in ('full','melody'):
            with tempfile.TemporaryDirectory() as tmp:
                pipe=Mock(); pipe.plan.return_value=SimpleNamespace(abc=score(),truncated=False,timing={})
                kwargs={'style':'piano','lyrics':'[Intro] 钢琴独奏','cot':cot,'seed':42,'cfg_scale':1,'id':'test','semantic_sampling':{'max_tokens':200}}
                generate(pipe,kwargs,'instrumental',Path(tmp),Mock(),Mock())
                call=pipe.call_args.kwargs
                self.assertEqual(call['lyrics'],kwargs['lyrics']);self.assertEqual(call['cot'],cot)
                self.assertIn('"C"z16',call['abc'])
                self.assertIn('V: Ins\nC16-C16|',call['abc'])
                self.assertEqual(abc_tools().parse(call['abc']).voices['Vocal'].notes,[])
                self.assertTrue((Path(tmp)/'instrumental-transform.json').exists())
    def test_complete_truncated_plan_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe=Mock();pipe.plan.return_value=SimpleNamespace(abc=score(),truncated=True,timing={})
            generate(pipe,{'style':'piano','lyrics':'','cot':'full'},'instrumental',Path(tmp),Mock(),Mock())
            pipe.assert_called_once()
            self.assertTrue((Path(tmp)/'recovered-score.abc').exists())

    def test_partial_tail_recovers_aligned_group(self):
        original=score()
        recovered,audit=recover_score(original+'% outro\nV: Vocal\nC32|\nV: Ins\nE8',True)
        self.assertEqual(recovered,original)
        self.assertTrue(audit['tailRecovered'])
        self.assertEqual(audit['retainedMeasures'],1)

    def test_recovery_retreats_across_ties(self):
        original=score()
        text=original+'V: Vocal\nC32-|\nV: Ins\nE32|\nV: Vocal\nC32|\nV: Ins\nE8'
        self.assertEqual(recover_score(text,True)[0],original)

    def test_recovery_rejects_invalid_middle_or_empty_prefix(self):
        for text in (score('C8|')+'V: Vocal\nC8', score()[:100]):
            with self.assertRaises(ValueError): recover_score(text,True)
        with self.assertRaises(ValueError): recover_score(score()+'V: Vocal\nC8',False)

    def test_fragmented_rests_merge_and_are_idempotent(self):
        before=score('"Dm"z3z12z|').replace('L:1/32','L:1/16').replace('E32|','E16|')
        after,audit=mute_vocal(before)
        self.assertIn('"Dm"z3z12z|',after)
        self.assertEqual(mute_vocal(after)[0],after)
        self.assertEqual(audit['restNormalizedLines'],0)
    def test_chord_and_key_onsets_preserved(self):
        after,_=mute_vocal(score('"C"z3z z4[K:D]"D"z8z16|','z8[K:D]E24|'))
        self.assertIn('"C"z3z z4[K:D]"D"z8z16|',after)
    def test_unsupported_combined_duration_is_split(self):
        after,_=mute_vocal(score('"C"z8z2"G"z16z6|'))
        self.assertIn('"C"z8z2"G"z16z6|',after)
        self.assertNotIn('z10',after)
    def test_meter_changes_and_sections_preserved(self):
        before=score('z16z16|')+'% outro\nV: Vocal\nM:3/4\nz12z12|\nV: Ins\nM:3/4\nE24|\n'
        after,_=mute_vocal(before)
        self.assertIn('V: Vocal\nM:3/4\nz12z12|',after)
        self.assertIn('% outro\nV: Vocal\nM:3/4\nz12z12|'.encode().decode('unicode_escape'),after)

    def test_compensation_replaces_overlap_and_preserves_interlude(self):
        before=score('"C"C16-"Am7"C16|','E32|')+'% interlude\nV: Vocal\n"G"Z|\nV: Ins\nG32|\n'
        before=before.replace('"G"Z|','"G"z32|')
        out,audit=compensate_melody(before)
        self.assertIn('V: Ins\nC16-C16|',out)
        self.assertTrue(out.endswith('V: Ins\nG32|\n'))
        self.assertEqual(audit['transferredVocalNotes'],1)
        muted,_=mute_vocal(out)
        self.assertEqual(abc_tools().parse(muted).voices['Ins'].notes,abc_tools().parse(out).voices['Ins'].notes)
    def test_compensation_preserves_both_resting_groups(self):
        before=score('Z|','Z|')
        self.assertEqual(compensate_melody(before)[0],before)
    def test_compensation_extends_across_instrumental_tie(self):
        before=score('C32|','^F32-|')+'V: Vocal\nZ|\nV: Ins\nF32|\n'
        out,audit=compensate_melody(before)
        self.assertEqual(audit['compensatedGroups'],2)
        self.assertEqual(abc_tools().parse(out).voices['Ins'].notes,abc_tools().parse(before).voices['Vocal'].notes)
    def test_compensation_preserves_key_change_and_vocal_tie(self):
        before=score('^F32-|','E32|')+'V: Vocal\nF8F24|\nV: Ins\nZ|\n'
        out,_=compensate_melody(before)
        self.assertEqual(abc_tools().parse(out).voices['Ins'].notes,abc_tools().parse(before).voices['Vocal'].notes)
