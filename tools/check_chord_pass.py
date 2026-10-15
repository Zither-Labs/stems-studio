"""The chord sheet lines up with the bass, and a chord the bass rejects is dropped."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import chord_pass as cp  # noqa: E402


def runs(*pairs):
    out = []
    t = 0.0
    for root, seconds in pairs:
        out.append({"start": t, "end": t + seconds, "root": root})
        t += seconds
    return out


def names(chords):
    return [chord["name"] for chord in chords]


# A sheet written in C (C G Am F) is the same song as G D Em C. The bass is in G.
bass = runs((7, 2), (2, 2), (4, 2), (0, 2))
sheet, flats = cp.parse_sheet("C G Am F")
lined = cp.combine(sheet, [], bass, timed=False, source="sheet", flats=flats)
assert names(lined) == ["G", "D", "Em", "C"], names(lined)

# The same shape again, for a second loop of the progression.
twice = cp.combine(sheet, [], bass + [{"start": 8, "end": 10, "root": 7}, {"start": 10, "end": 12, "root": 2},
                                       {"start": 12, "end": 14, "root": 4}, {"start": 14, "end": 16, "root": 0}],
                   timed=False, source="sheet", flats=flats)
assert names(twice) == ["G", "D", "Em", "C", "G", "D", "Em", "C"], names(twice)

# A sheet for a different song does not get forced onto the bass.
wrong, _ = cp.parse_sheet("B E F#")
assert cp.combine(wrong, [], bass, timed=False, source="sheet") == []

# Second pass: the app's Am over a G bass is dropped. Its D over a D bass is kept.
app = [
    {"start": 0, "end": 2, "root": 9, "quality": "m", "name": "Am"},
    {"start": 2, "end": 4, "root": 2, "quality": "", "name": "D"},
]
only_bass = cp.combine([], app, bass, timed=False, source="sheet")
assert names(only_bass) == ["D"], names(only_bass)

# A timed chart in the wrong key is slid until the bass agrees, and a mismatched bar is left out.
timed = [
    {"start": 0, "end": 2, "root": 0, "quality": ""},
    {"start": 2, "end": 4, "root": 7, "quality": ""},
    {"start": 4, "end": 6, "root": 9, "quality": "m"},
    {"start": 6, "end": 8, "root": 5, "quality": ""},
]
slid = cp.align_timed(timed, bass, flats=False, source="karalyr")
assert names(slid) == ["G", "D", "Em", "C"], names(slid)

# Verse and chorus can bounce for as many lines as the bass plays, then the verse can come back.
# An outro on some other note is left blank. The written key can be wrong.
# G Em C G# F# written from C is C Am F C# B.
song = runs(
    (7, 2), (4, 2), (7, 2), (4, 2),          # verse G Em G Em
    (0, 2), (8, 2), (6, 2),                  # chorus C G# F#
    (7, 2), (4, 2), (7, 2),                  # verse again
    (0, 2), (8, 2), (6, 2), (6, 2),          # chorus again, held
    (9, 4),                                  # outro on A, not in the sheet
)
sections, section_flats = cp.parse_sections("verse C Am\nchorus F C# B")
placed = cp.align_sections(sections, song, section_flats, "sheet")
assert names(placed) == ["G", "Em", "G", "Em", "C", "G#", "F#", "G", "Em", "G", "C", "G#", "F#"], names(placed)
assert placed[-1]["end"] <= 28

# The same parts on one line, in the right key, with the chords inside a part shuffled.
shuffled, shuffled_flats = cp.parse_sections("verse Em G chorus F# C G#")
shuffled_place = cp.align_sections(shuffled, song, shuffled_flats, "sheet")
assert names(shuffled_place) == names(placed)

# Words that are not chords are ignored. Flats stay flats.
parsed, uses_flats = cp.parse_sheet("Verse: Bb F C7  |  capo 3")
assert [cp.spell(c["root"], c["quality"], uses_flats) for c in parsed] == ["Bb", "F", "C7"]
assert uses_flats

# Karalyr's timed shape, including a low-confidence bar that is skipped.
payload = {"segments": [
    {"start_ms": 0, "end_ms": 2000, "root_pc": 0, "quality": "min", "confidence": 0.9},
    {"start_ms": 2000, "end_ms": 4000, "label": "G:7", "confidence": 0.2},
]}
segs = cp.segments_from_payload(payload)
assert len(segs) == 1 and segs[0]["root"] == 0 and segs[0]["quality"] == "m", segs

chart = {"arrangement": {"backing_track_progression": ["G / / /", "C / / /", "G / D /", "G / / /"]}}
changes, uses_flats = cp.chords_from_chart(chart)
assert [cp.spell(c["root"], c["quality"], uses_flats) for c in changes] == ["G", "C", "G", "D", "G"], changes

exact = {"match_type": "title_exact", "title": "Sitting On Top Of The World", "artist": None, "score": 1}
assert cp.pick_hit(exact, "Doc Watson", "Sitting on top of the world")["title"].startswith("Sitting")
low = {"results": [{"match_type": "title_contains", "title": "Wonderwall", "artist": "Oasis", "score": 0.5}]}
assert cp.pick_hit(low, "Oasis", "Wonderwall") is None
other = {"results": [{"match_type": "title_exact", "title": "Africa", "artist": "Toto", "score": 1}]}
assert cp.pick_hit(other, "Weezer", "Africa") is None

# No chart lined up: the highway still gets the app's own chord names.
guess = cp.app_chord_line([
    {"start": 0, "end": 2, "root": 7, "quality": "", "name": "G"},
    {"start": 2, "end": 4, "root": 4, "quality": "m", "name": "Em"},
])
assert names(guess) == ["G", "Em"], names(guess)
assert all(chord["source"] == "app" for chord in guess)

# A chart that only caught one bar does not hide the rest of the app's chords.
app = [
    {"start": 0, "end": 8, "root": 7, "quality": "", "name": "G"},
    {"start": 8, "end": 16, "root": 0, "quality": "", "name": "C"},
]
thin = [{"start": 0, "end": 2, "root": 7, "quality": "", "name": "G", "source": "chart", "sure": True}]
shown, app_only = cp.prefer_visible_line(app, thin)
assert app_only and names(shown) == ["G", "C"], names(shown)
covered = [{"start": 0, "end": 8, "root": 7, "quality": "", "name": "G", "source": "sheet", "sure": True},
           {"start": 8, "end": 16, "root": 0, "quality": "", "name": "C", "source": "sheet", "sure": True}]
shown, app_only = cp.prefer_visible_line(app, covered)
assert not app_only and all(chord["source"] == "sheet" for chord in shown)

print("chord pass ok")
