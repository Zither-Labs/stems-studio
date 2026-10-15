"""Two passes for chords.

The first pass is a published chord chart the app looks up from the song's name (or a sheet
someone pasted). It is often written in a different key. The second pass is the app listening
to the stems. A chord is kept when its root is the note the bass holds for that stretch.
Anything else is left off the highway.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

KARALYR = "https://www.karalyr.com/api"
JAMMING = "https://www.startjamming.com/api/songs"
USER_AGENT = "StemsStudio/1.0 (local app; https://github.com/Zither-Labs/stems-studio)"
TIMEOUT = 8

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PITCH = {}
for _i, _name in enumerate(SHARP):
    PITCH[_name.upper()] = _i
for _i, _name in enumerate(FLAT):
    PITCH[_name.upper()] = _i

_SYMBOL = re.compile(
    r"^([A-G])([b#])?(m|min|maj|dim|aug|sus2|sus4|sus)?(maj7|m7|add9|7|9|6)?(?:/([A-G][b#]?))?$",
    re.IGNORECASE,
)
_SKIP = {"verse", "chorus", "bridge", "intro", "outro", "capo", "n.c.", "nc", "n", "x", "%", "-"}


def spell(root, quality, flats=False):
    name = FLAT[root % 12] if flats else SHARP[root % 12]
    return name + (quality or "")


def _quality(raw_quality, extension):
    quality = (raw_quality or "").lower()
    extension = (extension or "").lower()
    minor = quality in ("m", "min")
    if minor and extension in ("7", "m7"):
        return "m7"
    if extension == "maj7" or (quality == "maj" and extension == "7"):
        return "maj7"
    if extension == "m7":
        return "m7"
    if quality in ("dim", "aug", "sus", "sus2", "sus4"):
        return quality
    if extension in ("7", "9", "6", "add9"):
        return extension
    if minor:
        return "m"
    return ""


def parse_symbol(token):
    """One chord name, or None when the word is not a chord."""
    text = (token or "").strip()
    if not text or text.lower() in _SKIP:
        return None
    if ":" in text:
        root_text, _, rest = text.partition(":")
        root = PITCH.get(root_text.strip().upper())
        if root is None or rest.upper() in ("N", "X", ""):
            if rest.upper() in ("N", "X"):
                return None
        else:
            rest = rest.split("(")[0].split("/")[0].strip().lower()
            mapped = {
                "maj": "", "major": "", "min": "m", "minor": "m", "min7": "m7", "m7": "m7",
                "maj7": "maj7", "7": "7", "dim": "dim", "aug": "aug", "sus4": "sus4", "sus2": "sus2",
                "": "",
            }.get(rest, rest if rest in ("m", "m7", "7", "maj7", "9") else "")
            return {"root": root, "quality": mapped, "flats": "b" in root_text}
    match = _SYMBOL.match(text)
    if not match:
        return None
    letter, accidental, quality, extension, _slash = match.groups()
    root_name = letter.upper() + (accidental or "")
    root = PITCH.get(root_name.upper())
    if root is None:
        return None
    return {"root": root, "quality": _quality(quality, extension), "flats": (accidental or "").lower() == "b"}


_SECTION_WORDS = {
    "verse", "chorus", "bridge", "intro", "outro", "refrain", "prechorus", "hook", "interlude",
}


def _sheet_tokens(text):
    """Words from a pasted sheet. A slash or a blank line starts a new part."""
    lines = []
    for line in (text or "").replace("|", " ").splitlines():
        tokens = []
        for token in re.split(r"[\s,]+", line):
            token = token.strip().strip("[]().:")
            if not token or token.lower().startswith("capo") or token.isdigit():
                continue
            if token in {"/", "//"}:
                tokens.append("/")
                continue
            tokens.append(token)
        if tokens:
            lines.append(tokens)
    return lines


def parse_sheet(text):
    """Chords in the order they were written. Returns (chords, prefers_flats)."""
    sections, flats = parse_sections(text)
    chords = [chord for section in sections for chord in section["chords"]]
    return chords, flats


def parse_sections(text):
    """Parts of a sheet, in order. 'verse G Em' and 'chorus C G# F#' stay separate.

    A slash or a new line can split parts too. Returns (sections, prefers_flats).
    Each section is {"name", "chords"}.
    """
    sections = []
    current = {"name": "", "chords": []}
    flats = False

    def push():
        nonlocal current
        if current["chords"]:
            sections.append(current)
        current = {"name": "", "chords": []}

    for tokens in _sheet_tokens(text):
        for token in tokens:
            if token == "/":
                push()
                continue
            word = token.lower().replace("-", "")
            if word in _SECTION_WORDS:
                push()
                current["name"] = word
                continue
            parsed = parse_symbol(token)
            if not parsed:
                continue
            flats = flats or parsed["flats"]
            current["chords"].append({"root": parsed["root"], "quality": parsed["quality"]})
        # A line that named a part ends that part, so the next line can be the next part.
        if current["name"] and current["chords"]:
            push()
    push()
    return sections, flats


def dominant_root(runs, start, end):
    """The bass note that fills most of this stretch, or None when the bass is quiet or changing."""
    weights = {}
    heard = 0.0
    for run in runs:
        overlap = min(end, run["end"]) - max(start, run["start"])
        if overlap <= 0 or run.get("root") is None:
            continue
        root = int(run["root"]) % 12
        weights[root] = weights.get(root, 0.0) + overlap
        heard += overlap
    span = end - start
    if span <= 0 or heard < 0.5 * span or not weights:
        return None
    root = max(weights, key=weights.get)
    if weights[root] < 0.6 * heard:
        return None
    return root


def _collapse(pieces):
    merged = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if last and last["root"] == piece["root"] and last["quality"] == piece["quality"] \
                and piece["start"] - last["end"] < 0.25:
            last["end"] = piece["end"]
        else:
            merged.append(piece)
    return merged


def align_sections(sections, runs, flats, source):
    """Place each part wherever the bass plays it, for as many repeats as the bass does.

    Inside a part the chords can come back in any order and any number of times. The part
    changes when the bass lands on a chord from a later part. The number of lines does not matter.
    """
    sections = [section for section in sections if section.get("chords")]
    if not sections or not runs:
        return []
    bass_time = sum(run["end"] - run["start"] for run in runs)
    if bass_time <= 0:
        return []
    best = None
    for shift in range(12):
        tables = []
        for section in sections:
            table = {}
            for chord in section["chords"]:
                table.setdefault((chord["root"] + shift) % 12, chord["quality"])
            tables.append(table)
        index = 0
        matched = []
        score = 0.0
        for run in runs:
            root = int(run["root"]) % 12
            duration = run["end"] - run["start"]
            if root in tables[index]:
                matched.append((run, root, tables[index][root]))
                score += duration
                continue
            found = None
            for step in range(1, len(tables)):
                nxt = (index + step) % len(tables)
                if root in tables[nxt]:
                    found = nxt
                    break
            if found is None:
                continue
            index = found
            matched.append((run, root, tables[index][root]))
            score += duration
        if best is None or score > best[0] or (score == best[0] and shift < best[1]):
            best = (score, shift, matched)
    # Most of the bass has to be one of these chords. A long outro of other chords can stay blank
    # and the verse and chorus still show. A sheet for a different song does not.
    if best is None or best[0] < 0.45 * bass_time:
        return []
    pieces = []
    for run, root, quality in best[2]:
        pieces.append({
            "start": round(run["start"], 2),
            "end": round(run["end"], 2),
            "root": root,
            "quality": quality,
            "name": spell(root, quality, flats),
            "source": source,
            "sure": True,
        })
    return _collapse(pieces)


def align_cycle(chords, runs, flats, source):
    """A sheet with no times. Slide it through all twelve keys until it follows the bass."""
    if not chords or not runs:
        return []
    bass_time = sum(run["end"] - run["start"] for run in runs)
    if bass_time <= 0:
        return []
    best = None
    count = len(chords)
    for shift in range(12):
        roots = [(chord["root"] + shift) % 12 for chord in chords]
        qualities = [chord["quality"] for chord in chords]
        for start_at in range(count):
            order = roots[start_at:] + roots[:start_at]
            quals = qualities[start_at:] + qualities[:start_at]
            index = 0
            matched = []
            score = 0.0
            for run in runs:
                if run["root"] == order[index]:
                    matched.append((run, index))
                    score += run["end"] - run["start"]
                    continue
                nxt = (index + 1) % count
                if run["root"] == order[nxt]:
                    index = nxt
                    matched.append((run, index))
                    score += run["end"] - run["start"]
            if best is None or score > best[0]:
                best = (score, matched, order, quals)
    # Most of the bass has to follow the sheet. A couple of lucky notes is not a match.
    if best is None or best[0] < 0.6 * bass_time:
        return []
    _, matched, order, quals = best
    pieces = []
    for run, index in matched:
        root = order[index]
        quality = quals[index]
        pieces.append({
            "start": round(run["start"], 2),
            "end": round(run["end"], 2),
            "root": root,
            "quality": quality,
            "name": spell(root, quality, flats),
            "source": source,
            "sure": True,
        })
    return _collapse(pieces)


def align_timed(chords, runs, flats, source):
    """A timed chart. Try all twelve keys, then keep only the chords the bass agrees with."""
    total = sum(max(0.0, chord["end"] - chord["start"]) for chord in chords)
    if total <= 0 or not runs:
        return []
    best_shift, best_score = 0, -1.0
    for shift in range(12):
        score = 0.0
        for chord in chords:
            bass = dominant_root(runs, chord["start"], chord["end"])
            if bass is not None and (chord["root"] + shift) % 12 == bass:
                score += chord["end"] - chord["start"]
        if score > best_score:
            best_shift, best_score = shift, score
    if best_score < 0.4 * total:
        return []
    pieces = []
    for chord in chords:
        root = (chord["root"] + best_shift) % 12
        if dominant_root(runs, chord["start"], chord["end"]) != root:
            continue
        quality = chord.get("quality") or ""
        pieces.append({
            "start": round(chord["start"], 2),
            "end": round(chord["end"], 2),
            "root": root,
            "quality": quality,
            "name": spell(root, quality, flats),
            "source": source,
            "sure": True,
        })
    return _collapse(pieces)


def _covered(spans, start, end):
    return sum(max(0.0, min(end, stop) - max(start, begin)) for begin, stop in spans)


def add_app_chords(app_chords, runs, kept):
    """Second pass: the app's own chords, only where the bass agrees and the sheet said nothing."""
    spans = [(chord["start"], chord["end"]) for chord in kept]
    for chord in app_chords or []:
        start, end = float(chord["start"]), float(chord["end"])
        duration = end - start
        if duration <= 0 or _covered(spans, start, end) > 0.5 * duration:
            continue
        root = int(chord["root"]) % 12
        if dominant_root(runs, start, end) != root:
            continue
        quality = chord.get("quality") or ""
        kept.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "root": root,
            "quality": quality,
            "name": chord.get("name") or spell(root, quality),
            "source": "app",
            "sure": True,
        })
        spans.append((start, end))
    kept.sort(key=lambda chord: chord["start"])
    return kept


def combine(external, app_chords, runs, timed, source, flats=False):
    if external and timed:
        first = align_timed(external, runs, flats, source)
    elif external:
        first = align_cycle(external, runs, flats, source)
    else:
        first = []
    return add_app_chords(app_chords, runs, first)


def from_chart(chords, runs, timed, source, flats=False):
    """The first pass on its own: a chart lined up with the bass, with no app chords mixed in."""
    if not chords:
        return []
    if timed:
        return align_timed(chords, runs, flats, source)
    return align_cycle(chords, runs, flats, source)


def explain(sheet_text, sheet_used, chart_used, karalyr_used, count, chart_label=""):
    if (sheet_text or "").strip() and not sheet_used:
        return "That sheet did not line up with the bass, so it was not used."
    if count <= 0:
        return "No published chord chart matched this song, and the bass was not sure enough on its own."
    if sheet_used:
        return f"Showing {count} chords from the sheet you pasted, checked against the bass."
    if chart_used:
        name = chart_label or "a published chart"
        return f"Showing {count} chords from {name}, checked against the bass."
    if karalyr_used:
        return f"Showing {count} chords from an automatic chart, checked against the bass."
    return f"No published chart matched. Showing {count} chords the bass agreed with."


# --- published charts (looked up by song name; the app does not ask you to find them) ------

def _norm(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\bthe\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def pick_hit(payload, artist, title):
    """One search result whose title is this song. A different artist is left out."""
    want = _norm(title)
    who = _norm(artist)
    if not want or not isinstance(payload, dict):
        return None
    pool = []
    if payload.get("match_type") == "title_exact" and _norm(payload.get("title")) == want:
        pool.append(payload)
    for item in payload.get("results") or []:
        if not isinstance(item, dict) or item.get("match_type") in ("lyrics", "lyric"):
            continue
        if _norm(item.get("title")) != want:
            continue
        if item.get("match_type") != "title_exact" and float(item.get("score") or 0) < 0.9:
            continue
        pool.append(item)

    def rank(item):
        got = _norm(item.get("artist"))
        if who and got and (who == got or who in got or got in who):
            return 2
        if who and got:
            return 0
        return 1

    ranked = [item for item in pool if rank(item) > 0]
    if not ranked:
        return None
    ranked.sort(key=rank, reverse=True)
    return ranked[0]


def chords_from_chart(payload):
    """Chord changes from a Start Jamming arrangement, in the order they are played."""
    arrangement = payload.get("arrangement") if isinstance(payload, dict) else None
    measures = (arrangement or {}).get("backing_track_progression") or []
    tokens = []
    flats = False
    for measure in measures:
        current = None
        for part in str(measure).replace("—", " ").replace("–", " ").split():
            if part in {"/", "-", ".", "%", "|"}:
                if current:
                    tokens.append(current)
                continue
            parsed = parse_symbol(part.strip("[]().,"))
            if not parsed:
                continue
            current = {"root": parsed["root"], "quality": parsed["quality"]}
            flats = flats or parsed["flats"]
            tokens.append(current)
    chords = []
    for item in tokens:
        if chords and chords[-1] == item:
            continue
        chords.append(dict(item))
    return chords, flats


def fetch_jamming(artist, title):
    """A published chart for this title, or None. Raises on a network failure."""
    title = (title or "").strip()
    if not title:
        return None
    query = urllib.parse.urlencode({"for": "agent", "q": title, "limit": 8})
    hit = pick_hit(_get_json(f"{JAMMING}/search?{query}"), artist, title)
    if not hit:
        return None
    full = hit
    api_url = hit.get("api_url")
    if api_url and "arrangement" not in (hit if isinstance(hit, dict) else {}):
        if "for=agent" not in api_url:
            api_url += ("&" if "?" in api_url else "?") + "for=agent"
        full = _get_json(api_url)
    chords, flats = chords_from_chart(full if isinstance(full, dict) else {})
    if len(chords) < 2:
        return None
    label = (full or {}).get("title") or hit.get("title") or title
    who = (full or {}).get("artist") or hit.get("artist")
    if who:
        label = f"{who} — {label}"
    return {
        "chords": chords,
        "flats": flats,
        "label": label,
        "url": (full or {}).get("url") or hit.get("url") or "",
    }


# --- Karalyr (a public chord feed; often empty, and always a computer's guess) -----------

def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def segments_from_payload(data):
    """Timed chords from a Karalyr-style response. Unknown shapes return []."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("segments") or data.get("chords") or data.get("chart") or []
    else:
        return []
    chords = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("start_ms", item.get("start"))
        end = item.get("end_ms", item.get("end"))
        if start is None or end is None:
            continue
        start, end = float(start), float(end)
        if "start_ms" in item or "end_ms" in item or start > 1000 or end > 1000:
            start, end = start / 1000.0, end / 1000.0
        if end <= start:
            continue
        confidence = item.get("confidence")
        if confidence is not None and float(confidence) < 0.35:
            continue
        label = item.get("label") or item.get("harte") or item.get("name") or ""
        root = item.get("root_pc")
        quality = item.get("quality") or ""
        if root is None:
            parsed = parse_symbol(str(label))
            if not parsed:
                continue
            root, quality = parsed["root"], parsed["quality"]
        else:
            root = int(root) % 12
            quality = {"min": "m", "minor": "m", "maj": "", "major": "", "min7": "m7", "m7": "m7",
                       "maj7": "maj7", "7": "7", "dim": "dim", "aug": "aug"}.get(str(quality).lower(), quality or "")
        chords.append({"start": start, "end": end, "root": root, "quality": quality or ""})
    return chords


def fetch_karalyr(youtube_id=None, artist=None, title=None):
    """Timed chords for this recording, or [] when Karalyr has none. Raises on a network failure."""
    if youtube_id:
        try:
            data = _get_json(f"{KARALYR}/chords?{urllib.parse.urlencode({'youtube_id': youtube_id})}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            data = None
        found = segments_from_payload(data)
        if found:
            return found
    if not (artist and title):
        return []
    query = urllib.parse.urlencode({"artist_name": artist, "track_name": title})
    try:
        hits = _get_json(f"{KARALYR}/search?{query}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        return []
    if isinstance(hits, dict):
        hits = hits.get("results") or hits.get("tracks") or []
    for hit in (hits or [])[:3]:
        if not isinstance(hit, dict):
            continue
        nested = hit.get("karalyr") if isinstance(hit.get("karalyr"), dict) else {}
        if hit.get("has_chords") is False or nested.get("has_chords") is False:
            continue
        track_id = hit.get("track_id") or hit.get("id")
        if not track_id:
            continue
        try:
            data = _get_json(f"{KARALYR}/chords?{urllib.parse.urlencode({'track_id': track_id})}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        found = segments_from_payload(data)
        if found:
            return found
    return []
