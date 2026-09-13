"""Safe Phase 1 reference-strength transforms for a small ABC subset.

The transformer intentionally accepts only simple monophonic ABC. A score
that needs constructs outside that subset is returned byte-for-byte so a
best-effort rewrite can never silently change its timing or meaning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterable


STRENGTH_ALIASES = {
    "free": "free",
    "loose": "free",
    "balanced": "balanced",
    "faithful": "faithful",
}

_FIELD_RE = re.compile(r"^\s*([A-Za-z]):(.*)$")
_NOTE_RE = re.compile(
    r"^(?P<accidental>[_^=]*)(?P<name>[A-Ga-g])(?P<octave>[,']*)(?P<duration>.*)$"
)
_REST_RE = re.compile(r"^(?P<name>[zx])(?P<duration>.*)$")
_METER_RE = re.compile(r"^(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+)$")
_BOUNDARY_TOKENS = ("||", "|]", "[|", "|")


class ABCParseError(ValueError):
    """Raised when the input is outside the audited simple ABC subset."""

    def __init__(self, message: str, *, input_notes: int = 0, input_measures: int = 0):
        super().__init__(message)
        self.input_notes = input_notes
        self.input_measures = input_measures


@dataclass
class ABCNote:
    """A melodic note in a parsed ABC measure."""

    pitch: str
    octave: int
    duration: float
    position: float
    measure_idx: int
    is_strong_beat: bool
    original_text: str

    @property
    def midi_pitch(self) -> int:
        """Convert the written pitch to a stable MIDI-like integer."""
        base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
        pitch_class = re.sub(r"[^A-G]", "", self.pitch.upper())
        if pitch_class not in base:
            return 60
        accidental = self.pitch.count("^") - self.pitch.count("_")
        return 60 + base[pitch_class] + accidental + self.octave * 12


@dataclass
class ABCMeasure:
    """One complete bar from a parsed simple ABC score."""

    notes: list[ABCNote]
    time_signature: str
    is_phrase_end: bool
    original_text: str
    events: list["_ABCEvent"] = field(default_factory=list, repr=False)


@dataclass
class _ABCEvent:
    text: str
    duration: Fraction
    multiplier: Fraction
    is_rest: bool
    position: Fraction
    note: ABCNote | None = None
    generated: bool = False


@dataclass
class _ABCBar:
    events: list[_ABCEvent]
    marker: str
    measure_idx: int
    time_signature: str
    expected_duration: Fraction

    @property
    def is_phrase_end(self) -> bool:
        return self.marker in {"||", "|]", "[|"}


@dataclass
class _ABCMusicLine:
    leading: str
    trailing: str
    leading_markers: list[str]
    bars: list[_ABCBar]


@dataclass
class _ABCLine:
    content: str
    newline: str
    music: _ABCMusicLine | None = None


@dataclass
class _ABCScore:
    lines: list[_ABCLine]
    measures: list[ABCMeasure]


def _parse_fraction(value: str, *, label: str) -> Fraction:
    match = _METER_RE.fullmatch(value.strip())
    if not match:
        raise ABCParseError(f"invalid {label}")
    numerator = int(match.group("numerator"))
    denominator = int(match.group("denominator"))
    if numerator <= 0 or denominator <= 0:
        raise ABCParseError(f"invalid {label}")
    return Fraction(numerator, denominator)


def _parse_meter(value: str) -> tuple[int, int, str]:
    match = _METER_RE.fullmatch(value.strip())
    if not match:
        raise ABCParseError("invalid meter")
    numerator = int(match.group("numerator"))
    denominator = int(match.group("denominator"))
    if numerator <= 0 or denominator <= 0:
        raise ABCParseError("invalid meter")
    return numerator, denominator, f"{numerator}/{denominator}"


def _parse_multiplier(value: str) -> Fraction:
    """Parse an ABC duration suffix into a multiplier of ``L:``."""
    if value == "":
        return Fraction(1)
    if value.isdigit():
        result = Fraction(int(value), 1)
        if result <= 0:
            raise ABCParseError("zero duration")
        return result
    match = re.fullmatch(r"(\d*)(/+)(\d*)", value)
    if not match:
        raise ABCParseError("unsupported duration")
    numerator_text, slash_text, denominator_text = match.groups()
    numerator = int(numerator_text) if numerator_text else 1
    denominator = int(denominator_text) if denominator_text else 2 ** len(slash_text)
    if numerator <= 0 or denominator <= 0:
        raise ABCParseError("zero duration")
    return Fraction(numerator, denominator)


def _duration_suffix(multiplier: Fraction) -> str:
    if multiplier == 1:
        return ""
    if multiplier.denominator == 1:
        return str(multiplier.numerator)
    if multiplier.numerator == 1 and multiplier.denominator == 2:
        return "/"
    if multiplier.numerator == 1:
        return f"/{multiplier.denominator}"
    return f"{multiplier.numerator}/{multiplier.denominator}"


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


class ABCParser:
    """Parser and validator for simple monophonic ABC."""

    def parse(self, abc_text: str, _ignored: Any = None) -> list[ABCMeasure]:
        return self.parse_document(abc_text).measures

    def parse_document(self, abc_text: str) -> _ABCScore:
        if not isinstance(abc_text, str):
            raise TypeError("abc_text must be a string")

        lines: list[_ABCLine] = []
        measures: list[ABCMeasure] = []
        meter_numerator, meter_denominator, meter_text = 4, 4, "4/4"
        default_length = Fraction(1, 8)
        saw_music = False
        measure_idx = 0

        for raw_line in abc_text.splitlines(keepends=True):
            content, newline = _split_line_ending(raw_line)
            line = _ABCLine(content=content, newline=newline)
            stripped = content.strip()

            if not stripped or stripped.startswith("%"):
                lines.append(line)
                continue

            field = _FIELD_RE.match(content)
            if field:
                key, value = field.groups()
                if key == "V":
                    raise ABCParseError("voices are unsupported")
                if saw_music and key in {"M", "L"}:
                    raise ABCParseError("mid-score timing changes are unsupported")
                if key == "M":
                    meter_numerator, meter_denominator, meter_text = _parse_meter(value)
                elif key == "L":
                    default_length = _parse_fraction(value, label="default length")
                lines.append(line)
                continue

            if "V:" in content:
                raise ABCParseError("voices are unsupported")
            try:
                music, new_measures = self._parse_music_line(
                    content,
                    meter_numerator,
                    meter_denominator,
                    meter_text,
                    default_length,
                    measure_idx,
                )
            except ABCParseError as exc:
                if exc.input_notes == 0:
                    exc.input_notes = len(re.findall(r"[_^=]{0,2}[A-Ga-g]", content))
                if exc.input_measures == 0:
                    exc.input_measures = measure_idx
                raise
            line.music = music
            lines.append(line)
            measures.extend(new_measures)
            measure_idx += len(new_measures)
            saw_music = True

        if not measures:
            raise ABCParseError("no supported music events")
        return _ABCScore(lines=lines, measures=measures)

    def _parse_music_line(
        self,
        content: str,
        meter_numerator: int,
        meter_denominator: int,
        meter_text: str,
        default_length: Fraction,
        measure_start: int,
    ) -> tuple[_ABCMusicLine, list[ABCMeasure]]:
        leading_match = re.match(r"\s*", content)
        trailing_match = re.search(r"\s*$", content)
        leading = leading_match.group(0)
        trailing = trailing_match.group(0)
        body_end = len(content) - len(trailing) if trailing else len(content)
        body = content[len(leading):body_end]
        if not body:
            raise ABCParseError("empty music line")

        tokens = self._tokenize(body)
        bars: list[_ABCBar] = []
        leading_markers: list[str] = []
        current: list[_ABCEvent] = []

        for kind, value in tokens:
            if kind == "event":
                current.append(
                    self._make_event(
                        value,
                        default_length,
                        measure_start + len(bars),
                    )
                )
                continue

            if current:
                bars.append(
                    _ABCBar(
                        events=current,
                        marker=value,
                        measure_idx=measure_start + len(bars),
                        time_signature=meter_text,
                        expected_duration=Fraction(meter_numerator, meter_denominator),
                    )
                )
                current = []
            elif not bars:
                leading_markers.append(value)
            else:
                raise ABCParseError("empty bar")

        if current:
            bars.append(
                _ABCBar(
                    events=current,
                    marker="",
                    measure_idx=measure_start + len(bars),
                    time_signature=meter_text,
                    expected_duration=Fraction(meter_numerator, meter_denominator),
                )
            )
        if not bars:
            raise ABCParseError("no events in music line")

        parsed_measures: list[ABCMeasure] = []
        for bar in bars:
            self._finalize_bar(bar, meter_numerator, meter_denominator)
            notes = [event.note for event in bar.events if event.note is not None]
            parsed_measures.append(
                ABCMeasure(
                    notes=notes,
                    time_signature=meter_text,
                    is_phrase_end=bar.is_phrase_end,
                    original_text=" ".join(event.text for event in bar.events),
                    events=bar.events,
                )
            )
        return (
            _ABCMusicLine(
                leading=leading,
                trailing=trailing,
                leading_markers=leading_markers,
                bars=bars,
            ),
            parsed_measures,
        )

    def _tokenize(self, body: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        index = 0
        while index < len(body):
            if body[index].isspace():
                index += 1
                continue

            boundary = next(
                (
                    candidate
                    for candidate in _BOUNDARY_TOKENS
                    if body.startswith(candidate, index)
                ),
                None,
            )
            if boundary is not None:
                tokens.append(("bar", boundary))
                index += len(boundary)
                continue

            start = index
            accidental_count = 0
            while index < len(body) and body[index] in "_^=":
                accidental_count += 1
                index += 1
            if accidental_count > 2:
                raise ABCParseError("unsupported accidental")
            if index >= len(body) or body[index] not in "ABCDEFGabcdefgzx":
                raise ABCParseError("unsupported construct")
            is_rest = body[index] in "zx"
            index += 1
            if not is_rest:
                while index < len(body) and body[index] in ",'":
                    index += 1

            if index < len(body) and body[index].isdigit():
                while index < len(body) and body[index].isdigit():
                    index += 1
                if index < len(body) and body[index] == "/":
                    while index < len(body) and body[index] == "/":
                        index += 1
                    while index < len(body) and body[index].isdigit():
                        index += 1
            elif index < len(body) and body[index] == "/":
                while index < len(body) and body[index] == "/":
                    index += 1
                while index < len(body) and body[index].isdigit():
                    index += 1

            tokens.append(("event", body[start:index]))
        return tokens

    def _make_event(self, token: str, default_length: Fraction, measure_idx: int) -> _ABCEvent:
        rest_match = _REST_RE.fullmatch(token)
        if rest_match:
            multiplier = _parse_multiplier(rest_match.group("duration"))
            return _ABCEvent(
                text=token,
                duration=default_length * multiplier,
                multiplier=multiplier,
                is_rest=True,
                position=Fraction(0),
            )

        note_match = _NOTE_RE.fullmatch(token)
        if not note_match or len(note_match.group("accidental")) > 2:
            raise ABCParseError("unsupported note construct")
        accidental = note_match.group("accidental")
        name = note_match.group("name")
        octave_marks = note_match.group("octave")
        multiplier = _parse_multiplier(note_match.group("duration"))
        duration = default_length * multiplier
        octave = (1 if name.islower() else 0) + octave_marks.count("'") - octave_marks.count(",")
        pitch = accidental + name.upper()
        note = ABCNote(
            pitch=pitch,
            octave=octave,
            duration=float(duration),
            position=0.0,
            measure_idx=measure_idx,
            is_strong_beat=False,
            original_text=token,
        )
        return _ABCEvent(
            text=token,
            duration=duration,
            multiplier=multiplier,
            is_rest=False,
            position=Fraction(0),
            note=note,
        )

    def _finalize_bar(
        self,
        bar: _ABCBar,
        meter_numerator: int,
        meter_denominator: int,
    ) -> None:
        position = Fraction(0)
        for event in bar.events:
            event.position = position
            if event.note is not None:
                event.note.position = float(position)
                event.note.is_strong_beat = self._is_strong_beat(
                    position,
                    meter_numerator,
                    meter_denominator,
                )
            position += event.duration
        if position != bar.expected_duration:
            raise ABCParseError(
                f"bar duration {position} does not match {bar.expected_duration}"
            )

    def _parse_duration(self, duration_text: str) -> float:
        return float(_parse_multiplier(duration_text))

    def _is_strong_beat(
        self,
        position: Fraction,
        beats_per_measure: int,
        beat_denominator: int = 4,
    ) -> bool:
        beat = Fraction(1, beat_denominator)
        if position == 0:
            return True
        if beats_per_measure == 4 and beat_denominator == 4:
            return position == 2 * beat
        if beats_per_measure in {6, 9, 12} and beat_denominator in {8, 16}:
            return position % (3 * beat) == 0
        return False


class ABCReferenceProcessor:
    """Deterministic reference-strength processing at the ABC layer."""

    def __init__(self):
        self.parser = ABCParser()
        self.last_stats: dict[str, Any] = {}

    @staticmethod
    def normalize_strength(strength: str) -> str:
        return (
            STRENGTH_ALIASES.get(strength, "balanced")
            if isinstance(strength, str)
            else "balanced"
        )

    def process(self, abc_text: str, strength: str, _ignored: Any = None) -> str:
        if not isinstance(abc_text, str):
            raise TypeError("abc_text must be a string")
        strength = self.normalize_strength(strength)
        try:
            score = self.parser.parse_document(abc_text)
        except ABCParseError as exc:
            input_notes = exc.input_notes or self._rough_note_count(abc_text)
            self.last_stats = {
                "strength": strength,
                "inputNotes": input_notes,
                "outputNotes": input_notes,
                "retention": 1.0 if input_notes else 0.0,
                "inputMeasures": exc.input_measures,
                "outputMeasures": exc.input_measures,
                "unchanged": True,
                "degraded": True,
                "durationPreserved": True,
                "reason": "unsupported_construct",
            }
            return abc_text

        input_notes = len([note for measure in score.measures for note in measure.notes])
        input_measures = len(score.measures)
        if strength == "faithful":
            self.last_stats = {
                "strength": strength,
                "inputNotes": input_notes,
                "outputNotes": input_notes,
                "retention": 1.0 if input_notes else 0.0,
                "inputMeasures": input_measures,
                "outputMeasures": input_measures,
                "unchanged": True,
                "degraded": False,
                "durationPreserved": True,
            }
            return abc_text

        transformed, output_notes, duration_preserved = self._transform(score, strength)
        unchanged = transformed == abc_text
        self.last_stats = {
            "strength": strength,
            "inputNotes": input_notes,
            "outputNotes": output_notes,
            "retention": output_notes / input_notes if input_notes else 0.0,
            "inputMeasures": input_measures,
            "outputMeasures": input_measures,
            "unchanged": unchanged,
            "degraded": True,
            "durationPreserved": duration_preserved,
            "reason": "simplified",
        }
        return transformed

    def _transform(self, score: _ABCScore, strength: str) -> tuple[str, int, bool]:
        output_parts: list[str] = []
        output_notes = 0
        duration_preserved = True
        for line in score.lines:
            if line.music is None:
                output_parts.append(line.content + line.newline)
                continue
            music = line.music
            transformed_bars: list[_ABCBar] = []
            line_changed = False
            for bar in music.bars:
                simplified = self._simplify_bar(bar, strength)
                transformed_bars.append(simplified)
                output_notes += sum(not event.is_rest for event in simplified.events)
                duration_preserved = duration_preserved and (
                    sum(event.duration for event in simplified.events) == bar.expected_duration
                )
                if not self._same_events(bar.events, simplified.events):
                    line_changed = True
            if not line_changed:
                output_parts.append(line.content + line.newline)
                continue
            output_parts.append(self._render_music_line(music, transformed_bars) + line.newline)
        return "".join(output_parts), output_notes, duration_preserved

    def _simplify_bar(self, bar: _ABCBar, strength: str) -> _ABCBar:
        note_indices = [index for index, event in enumerate(bar.events) if not event.is_rest]
        if not note_indices:
            return bar
        keep = {note_indices[0]}
        if bar.is_phrase_end:
            keep.add(note_indices[-1])

        beat_length = Fraction(1, int(bar.time_signature.split("/")[1]))
        default_length = min(
            (event.duration / event.multiplier for event in bar.events if event.multiplier),
            default=Fraction(1, 8),
        )
        long_threshold = max(default_length * 2, beat_length)
        if strength == "balanced":
            for index in note_indices:
                event = bar.events[index]
                strong = event.note.is_strong_beat if event.note is not None else False
                if strong or event.duration >= long_threshold:
                    keep.add(index)
        else:
            for index in note_indices:
                event = bar.events[index]
                if event.duration >= long_threshold * 2:
                    keep.add(index)

        simplified_events: list[_ABCEvent] = []
        for index, event in enumerate(bar.events):
            if event.is_rest or index in keep:
                simplified_events.append(event)
            else:
                simplified_events.append(
                    _ABCEvent(
                        text="z" + _duration_suffix(event.duration / default_length),
                        duration=event.duration,
                        multiplier=event.duration / default_length,
                        is_rest=True,
                        position=event.position,
                        generated=True,
                    )
                )
        simplified_events = self._merge_rests(simplified_events, default_length)
        return _ABCBar(
            events=simplified_events,
            marker=bar.marker,
            measure_idx=bar.measure_idx,
            time_signature=bar.time_signature,
            expected_duration=bar.expected_duration,
        )

    @staticmethod
    def _merge_rests(events: Iterable[_ABCEvent], default_length: Fraction) -> list[_ABCEvent]:
        merged: list[_ABCEvent] = []
        for event in events:
            if merged and event.is_rest and merged[-1].is_rest:
                merged[-1].duration += event.duration
                merged[-1].multiplier = merged[-1].duration / default_length
                merged[-1].text = "z" + _duration_suffix(merged[-1].multiplier)
                merged[-1].generated = True
            else:
                merged.append(event)
        return merged

    @staticmethod
    def _same_events(left: list[_ABCEvent], right: list[_ABCEvent]) -> bool:
        if len(left) != len(right):
            return False
        return all(
            a.text == b.text
            and a.duration == b.duration
            and a.is_rest == b.is_rest
            for a, b in zip(left, right)
        )

    @staticmethod
    def _render_music_line(music: _ABCMusicLine, bars: list[_ABCBar]) -> str:
        rendered_tokens: list[str] = list(music.leading_markers)
        for bar in bars:
            rendered_tokens.extend(event.text for event in bar.events)
            if bar.marker:
                rendered_tokens.append(bar.marker)
        body = " ".join(rendered_tokens)
        return music.leading + body + music.trailing

    @staticmethod
    def _rough_note_count(abc_text: str) -> int:
        count = 0
        for line in abc_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("%") or _FIELD_RE.match(line):
                continue
            count += len(re.findall(r"[_^=]{0,2}[A-Ga-g]", line))
        return count


if __name__ == "__main__":
    sample_abc = """X:1
T:Test Melody
M:4/4
L:1/8
K:C
C D E F G A B c | c B A G F E D C ||
"""
    processor = ABCReferenceProcessor()
    print("原始 ABC:")
    print(sample_abc)
    for strength in ("free", "balanced", "faithful"):
        result = processor.process(sample_abc, strength)
        print(f"\n{strength}:")
        print(result)
        print(processor.last_stats)
