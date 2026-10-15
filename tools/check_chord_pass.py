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

print("chord pass ok")
