"""Instrumental score conditioning, enabled only by the explicit vocal selection."""
import importlib.util
import sys
import re
from functools import lru_cache
from .common import ROOT, write_json

_NATIVE_VOICE_HEADERS = (
    'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
    'V: Ins clef=treble name="Ins Melody" snm="Inst."',
)


@lru_cache(maxsize=1)
def abc_tools():
    path = ROOT / 'vendor/yue2/skills/yue2-music/scripts/abc_tools.py'
    spec = importlib.util.spec_from_file_location('_yue2_instrumental_abc_tools', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_rests(line, tools):
    """Normalize validated Vocal music only, never crossing an event or bar."""
    lengths = sorted(tools.DURATIONS, reverse=True)
    def merged(match):
        units = sum(int(n or '1') for n in re.findall(r'z([0-9]*)', match.group(0)))
        chunks = []
        for length in lengths:
            count, units = divmod(units, length)
            chunks.extend(('z' + (str(length) if length != 1 else '')) for _ in range(count))
        return ''.join(chunks)
    bars = line.split('|')
    for index, bar in enumerate(bars[:-1]):
        # A fully resting, event-free bar can use the meter-relative Z notation.
        if re.fullmatch(r'\s*(?:z[0-9]*\s*)+', bar):
            bars[index] = 'Z'
        else:
            # Chord and inline-key strings are opaque boundaries, even if they
            # contain letters that resemble notes or rests.
            parts = re.split(r'("[^"\n]*"|\[K:[^\]\n]+\])', bar)
            bars[index] = ''.join(part if i % 2 else re.sub(
                r'z[0-9]*(?:[ \t]*z[0-9]*)*', merged, part)
                for i, part in enumerate(parts))
    return '|'.join(bars)


def remove_mismatched_ties(music, tools):
    """Drop only ties whose next event cannot be the same written pitch."""
    events = [match for match in tools.TOKEN.finditer(music)
              if match.group('note') is not None]
    remove = set()
    for index, match in enumerate(events):
        if match.group('tie') != '-':
            continue
        following = events[index + 1] if index + 1 < len(events) else None
        same_written = following is not None and following.group('note') != 'z' and (
            (match.group('note'), match.group('oct')) ==
            (following.group('note'), following.group('oct')))
        explicit_conflict = same_written and following.group('acc') is not None and (
            match.group('acc') or '') != following.group('acc')
        if not same_written or explicit_conflict:
            remove.add(match.end() - 1)
    if not remove:
        return music, 0
    return ''.join(character for index, character in enumerate(music) if index not in remove), len(remove)


def normalize_instrumental_score(text):
    """Canonicalize valid two-voice ABC variants before instrumental editing.

    AI-edited and imported scores often preserve the required Vocal/Ins IDs but
    omit the display names, or compress more than four empty measures as Z8,
    Z12, and so on. YuE2 can consume those scores, while the conservative edit
    parser intentionally accepts only native headers and 1-4-measure groups.
    Normalize only those representational differences; notes, chords, keys,
    meters, and bar order remain unchanged.
    """
    tools = abc_tools()
    try:
        tools.parse(text)
        return text, {'scoreNormalization': 'native', 'voiceHeadersNormalized': False,
                      'groupsRechunked': 0, 'expandedRestMeasures': 0,
                      'invalidTiesRemoved': 0}
    except ValueError:
        pass
    lines = text.splitlines()
    if len(lines) < 8:
        raise ValueError('Incomplete two-voice ABC')
    for index, voice in ((5, 'Vocal'), (6, 'Ins')):
        if not re.fullmatch(rf'V:\s*{voice}(?:\s+[^\n]+)?', lines[index].strip()):
            raise ValueError('Expected Vocal and Ins voice definitions in the native order')
    output = [*lines[:5], *_NATIVE_VOICE_HEADERS, lines[7]]
    cursor = 8
    groups_rechunked = 0
    expanded_rest_measures = 0
    invalid_ties_removed = 0
    while cursor < len(lines):
        comments = []
        while cursor < len(lines) and lines[cursor].startswith('%'):
            comments.append(lines[cursor])
            cursor += 1
        if cursor >= len(lines):
            raise ValueError('Dangling section comment without music')
        blocks = {}
        for voice in tools.VOICES:
            if lines[cursor].strip() != f'V: {voice}':
                raise ValueError(f'Expected V: {voice} in paired score group')
            cursor += 1
            fields = []
            while cursor < len(lines) and lines[cursor].startswith(('M:', 'K:')):
                fields.append(lines[cursor])
                cursor += 1
            if cursor >= len(lines):
                raise ValueError(f'Missing music line for {voice}')
            music_lines = []
            while cursor < len(lines):
                line = lines[cursor].strip()
                if line.startswith('V:') or line.startswith('%'):
                    break
                cursor += 1
                if not line:
                    continue
                if not line.endswith('|'):
                    raise ValueError(f'{voice} music line must end with a plain barline')
                music_lines.append(line)
            if not music_lines:
                raise ValueError(f'Missing music line for {voice}')
            music, removed = remove_mismatched_ties(''.join(music_lines), tools)
            invalid_ties_removed += removed
            bars = []
            for bar in music[:-1].split('|'):
                bar = bar.strip()
                if not bar:
                    raise ValueError(f'{voice} contains an empty measure')
                rest = re.fullmatch(r'Z([1-9][0-9]*)?', bar)
                if rest:
                    count = int(rest.group(1) or '1')
                    if count > 256:
                        raise ValueError('Compressed rest exceeds 256 measures')
                    bars.extend(['Z'] * count)
                    expanded_rest_measures += max(0, count - 1)
                else:
                    bars.append(bar)
            blocks[voice] = (fields, bars)
        vocal_bars = blocks['Vocal'][1]
        ins_bars = blocks['Ins'][1]
        if len(vocal_bars) != len(ins_bars):
            raise ValueError('Vocal and Ins voices have different measure counts')
        if len(vocal_bars) > 4:
            groups_rechunked += 1
        for start in range(0, len(vocal_bars), 4):
            if start == 0:
                output.extend(comments)
            for voice in tools.VOICES:
                fields, bars = blocks[voice]
                output.append(f'V: {voice}')
                if start == 0:
                    output.extend(fields)
                output.append('|'.join(bars[start:start + 4]) + '|')
    normalized = '\n'.join(output) + ('\n' if text.endswith(('\n', '\r')) else '')
    tools.parse(normalized)
    return normalized, {
        'scoreNormalization': 'canonicalized',
        'voiceHeadersNormalized': tuple(lines[5:7]) != _NATIVE_VOICE_HEADERS,
        'groupsRechunked': groups_rechunked,
        'expandedRestMeasures': expanded_rest_measures,
        'invalidTiesRemoved': invalid_ties_removed,
    }


def compensate_melody(text):
    """Prefer Vocal themes by native 1-4-bar group, extending across ties.

    Groups are notation boundaries, not inferred musical phrases. Whole groups
    preserve articulation and rests; we never interleave individual notes.
    """
    tools = abc_tools()
    before = tools.parse(text)
    lines = text.splitlines(keepends=True)
    entries = list(before.music_lines.items())
    groups = [(entries[i][0], entries[i + 1][0]) for i in range(0, len(entries), 2)]
    units = []
    current = []
    for vocal, ins in groups:
        current.append((vocal, ins))
        tied = any(lines[index].rstrip().endswith('-|') for index in (vocal, ins))
        if not tied:
            units.append(current)
            current = []
    if current:
        raise ValueError('Unresolved tie at compensation boundary')
    selected = set()
    for unit in units:
        # When Vocal carries a theme, move the complete native group to Ins.
        # If Vocal is resting, preserve the existing instrumental passage.
        has_theme = any(match.group('note') not in (None, 'z')
                        for vocal, _ in unit for match in tools.TOKEN.finditer(lines[vocal]))
        if has_theme:
            for vocal, ins in unit:
                selected.add(ins)
                lines[ins] = tools.TOKEN.sub(
                    lambda match: '' if match.group('chord') is not None else match.group(0),
                    lines[vocal])
    output = ''.join(lines)
    after = tools.parse(output)
    for name in tools.VOICES:
        a, b = before.voices[name], after.voices[name]
        if (a.bars, a.keys, a.chords, a.time) != (b.bars, b.keys, b.chords, b.time):
            raise ValueError('Theme compensation changed timeline or harmony: ' + name)
    # Compare exact sounding events against the selected source for every group.
    expected = []
    bar_offset = 0
    transferred = 0
    for vocal, ins in groups:
        line = text.splitlines()[vocal].strip()
        bars = sum(int(bar.strip()[1:] or '1') if re.fullmatch(r'Z[2-4]?', bar.strip()) else 1
                   for bar in line[:-1].split('|'))
        start = before.voices['Vocal'].bars[bar_offset][0]
        end_bar = before.voices['Vocal'].bars[bar_offset + bars - 1]
        end = end_bar[0] + end_bar[1]
        source = before.voices['Vocal' if ins in selected else 'Ins']
        events = [note for note in source.notes if start <= note[0] < end]
        expected.extend(events)
        if ins in selected:
            transferred += len(events)
        bar_offset += bars
    if after.voices['Ins'].notes != expected:
        raise ValueError('Theme compensation changed selected melody events')
    return output, {'compensation': 'vocal_theme_by_native_group',
        'compensatedGroups': len(selected), 'transferredVocalNotes': transferred,
        'originalInstrumentalNotes': len(before.voices['Ins'].notes),
        'compensatedInstrumentalNotes': len(after.voices['Ins'].notes)}


def mute_vocal(text):
    tools = abc_tools()
    before = tools.parse(text)
    lines = text.splitlines(keepends=True)
    normalized_lines = 0
    for index, voice in before.music_lines.items():
        if voice == 'Vocal':
            def replace(match):
                if match.group('note') not in (None, 'z'):
                    return 'z' + match.group('duration')
                return match.group(0)
            muted = tools.TOKEN.sub(replace, lines[index])
            # Preserve the original rest fragmentation and ABC token boundaries.
            # Equivalent duration compression can change model conditioning.
            lines[index] = muted
    output = ''.join(lines)
    after = tools.parse(output)
    if after.voices['Vocal'].notes:
        raise ValueError('Instrumental score still contains vocal notes')
    for name in tools.VOICES:
        a, b = before.voices[name], after.voices[name]
        if (a.bars, a.keys, a.chords, a.time) != (b.bars, b.keys, b.chords, b.time):
            raise ValueError('Instrumental conversion changed timing or harmony: ' + name)
    if before.voices['Ins'].notes != after.voices['Ins'].notes:
        raise ValueError('Instrumental conversion changed instrumental notes')
    return output, {'validation': 'passed',
        'restNormalization': False, 'restNormalizedLines': 0,
        'vocalNotesBefore': len(before.voices['Vocal'].notes), 'vocalNotesAfter': 0,
        'instrumentalNotesPreserved': len(after.voices['Ins'].notes),
        'chordsPreserved': len(after.voices['Vocal'].chords),
        'measures': len(after.voices['Vocal'].bars)}


def recover_score(text, truncated):
    """Recover only a truncated tail at native paired-group boundaries.

    Never rewrite notes or fabricate a cadence. Invalid retained content fails
    closed; only unresolved end ties permit retreat through earlier groups.
    """
    tools = abc_tools()
    try:
        parsed = tools.parse(text)
        return text, {'planTruncated': bool(truncated), 'tailRecovered': False,
                      'retainedMeasures': len(parsed.voices['Vocal'].bars)}
    except ValueError:
        if not truncated:
            raise
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == 'V: Vocal']
    for start in reversed(starts):
        end = start
        while end > 8 and lines[end - 1].startswith('% '):
            end -= 1
        if end <= 8:
            break
        candidate = ''.join(lines[:end])
        try:
            parsed = tools.parse(candidate)
        except ValueError as error:
            # A malformed earlier group is not a tail-recovery opportunity.
            if 'unresolved tie at end of score' in str(error):
                continue
            raise ValueError('Invalid score before truncated tail: ' + str(error)) from error
        return candidate, {'planTruncated': True, 'tailRecovered': True,
                           'removedCharacters': len(text) - len(candidate),
                           'retainedMeasures': len(parsed.voices['Vocal'].bars),
                           'warning': '谱曲达到上限，已保留完整部分；长度可能缩短，结尾可能不自然。'}
    raise ValueError('Truncated score has no complete aligned group without dangling ties')


def generate(pipe, kwargs, vocal_mode, run_dir, check, progress):
    # Ordinary songs and unplanned generation retain the exact native call path.
    if vocal_mode != 'instrumental' or kwargs['cot'] == 'off':
        return pipe(**kwargs)
    from yue2.protocol import SongRequest
    check()
    request_fields = {k: v for k, v in kwargs.items()
                      if k not in ('semantic_sampling', 'cancelled', 'on_token', 'abc_sampling')}
    original = pipe.plan(request=SongRequest(**request_fields),
                         cancelled=kwargs.get('cancelled'), abc_sampling=kwargs.get('abc_sampling'))
    check()
    (run_dir / 'original-score.abc').write_text(original.abc or '', encoding='utf-8')
    try:
        if original.truncated:
            recovered, recovery = recover_score(original.abc, True)
            recovered, normalization = normalize_instrumental_score(recovered)
        else:
            recovered, normalization = normalize_instrumental_score(original.abc)
            recovered, recovery = recover_score(recovered, False)
        (run_dir / 'recovered-score.abc').write_text(recovered, encoding='utf-8')
        write_json(run_dir / 'score-recovery.json', recovery)
        if recovery.get('warning'):
            progress(recovery['warning'])
        progress('正在将主旋律转为器乐并处理人声休止')
        compensated, compensation = compensate_melody(recovered)
        (run_dir / 'compensated-score.abc').write_text(compensated, encoding='utf-8')
        abc, audit = mute_vocal(compensated)
        audit.update(compensation)
        audit.update(recovery)
        audit.update(normalization)
    except ValueError as error:
        write_json(run_dir / 'instrumental-transform.json', {'validation': 'failed', 'error': str(error)})
        raise ValueError('纯音乐乐谱处理失败：' + str(error)) from error
    (run_dir / 'instrumental-score.abc').write_text(abc, encoding='utf-8')
    write_json(run_dir / 'instrumental-transform.json', {
        **audit, 'cot': kwargs['cot'], 'originalPlanTiming': original.timing,
        'lyricsPreserved': True, 'source': 'reference' if kwargs.get('abc') else 'generated'})
    check()
    # Native __call__ rebuilds the request, prefix and artifact identity using external ABC.
    return pipe(**{**kwargs, 'abc': abc})
