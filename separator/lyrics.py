"""
Lyrics for karaoke: from the song file's own tags, or from LRCLIB (https://lrclib.net), a free
lyrics database with time-synced lyrics.

A lyrics result always looks like this:
    {"source": "embedded" | "lrclib", "synced": bool, "lines": [{"t": seconds, "text": "..."}],
     "plain": "all the text", "matched": {...what was matched...}}
Un-synced lyrics have "synced": False and every "t" is None.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

LRCLIB = "https://lrclib.net/api"
USER_AGENT = "StemsStudio/1.0 (local app; https://github.com/Zither-Labs/stems-studio)"
TIMEOUT = 10

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[(ar|ti|al|by|offset|length|re|ve|au):(.*)\]$", re.IGNORECASE)
_WORD_TAG = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")      # enhanced LRC word times


# --- reading and parsing --------------------------------------------------------------

def parse_lrc(text):
    """Turn LRC text ("[01:23.45] words") into timed lines. Returns [] if it is not LRC."""
    lines = []
    offset = 0.0
    for raw in text.splitlines():
        raw = raw.strip()
        meta = _META_TAG.match(raw)
        if meta:
            if meta.group(1).lower() == "offset":
                try:
                    offset = int(meta.group(2).strip()) / 1000.0
                except ValueError:
                    pass
            continue
        stamps = list(_TIME_TAG.finditer(raw))
        if not stamps:
            continue
        words = _WORD_TAG.sub("", raw[stamps[-1].end():]).strip()
        for stamp in stamps:
            fraction = stamp.group(3) or "0"
            seconds = int(stamp.group(1)) * 60 + int(stamp.group(2)) + int(fraction) / (10 ** len(fraction))
            lines.append({"t": round(max(0.0, seconds - offset), 2), "text": words})
    lines.sort(key=lambda line: line["t"])
    return lines if len(lines) >= 3 else []


def make_result(text, source, matched=None):
    """Build a lyrics result from LRC or plain text."""
    text = (text or "").strip()
    if not text:
        return None
    timed = parse_lrc(text)
    if timed:
        plain = "\n".join(line["text"] for line in timed)
        return {"source": source, "synced": True, "lines": timed, "plain": plain, "matched": matched or {}}
    plain = _TIME_TAG.sub("", text)
    lines = [{"t": None, "text": line.rstrip()} for line in plain.splitlines()]
    return {"source": source, "synced": False, "lines": lines, "plain": plain, "matched": matched or {}}


def read_tags(path):
    """Read artist / title / album / duration and any lyrics from a song file's tags.

    Returns {"artist", "title", "album", "duration", "lyrics"}; missing things are None.
    """
    info = {"artist": None, "title": None, "album": None, "duration": None, "lyrics": None}
    try:
        import mutagen
    except ImportError:
        return info
    try:
        audio = mutagen.File(path)
    except Exception:
        return info
    if audio is None:
        return info
    if getattr(audio, "info", None) is not None and getattr(audio.info, "length", None):
        info["duration"] = round(float(audio.info.length), 1)
    tags = getattr(audio, "tags", None)
    if not tags:
        return info

    def first(value):
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return str(value).strip() if value not in (None, "") else None

    synced_from_tags = None
    plain_from_tags = None
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4Tags

    if not isinstance(tags, (ID3, MP4Tags)):               # FLAC, Ogg and Opus: Vorbis comments
        lowered = {}
        for key, value in tags.items():
            lowered.setdefault(key.lower(), value)
        info["artist"] = first(lowered.get("artist") or lowered.get("albumartist"))
        info["title"] = first(lowered.get("title"))
        info["album"] = first(lowered.get("album"))
        for key in ("syncedlyrics", "lyrics", "unsyncedlyrics", "unsynced lyrics", "lyrics-eng", "lyrics-xxx"):
            value = lowered.get(key)
            if value:
                text = first(value)
                if text and parse_lrc(text):
                    synced_from_tags = synced_from_tags or text
                elif text:
                    plain_from_tags = plain_from_tags or text
    elif isinstance(tags, ID3):
        info["artist"] = first(tags.get("TPE1").text if tags.get("TPE1") else None)
        info["title"] = first(tags.get("TIT2").text if tags.get("TIT2") else None)
        info["album"] = first(tags.get("TALB").text if tags.get("TALB") else None)
        for frame in tags.getall("USLT"):
            if frame.text:
                if parse_lrc(frame.text):
                    synced_from_tags = synced_from_tags or frame.text
                else:
                    plain_from_tags = plain_from_tags or frame.text
        for frame in tags.getall("SYLT"):
            rows = [(text, ms) for text, ms in frame.text]
            if rows and not synced_from_tags:
                synced_from_tags = "\n".join(f"[{int(ms // 60000):02d}:{(ms % 60000) / 1000:05.2f}]{text.strip()}" for text, ms in rows)
    else:                                                  # MP4 / M4A and others
        info["artist"] = first(tags.get("\xa9ART"))
        info["title"] = first(tags.get("\xa9nam"))
        info["album"] = first(tags.get("\xa9alb"))
        text = first(tags.get("\xa9lyr"))
        if text:
            if parse_lrc(text):
                synced_from_tags = text
            else:
                plain_from_tags = text

    info["lyrics"] = synced_from_tags or plain_from_tags
    return info


# --- LRCLIB ----------------------------------------------------------------------------------

def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def _clean_title(title):
    """Drop the '(Official Video)', '[HD]', 'ft. ...' kind of clutter YouTube titles have."""
    title = re.sub(r"[\(\[][^\)\]]*(official|video|audio|lyric|hd|hq|4k|remaster|live|visualizer)[^\)\]]*[\)\]]", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -_|")
    return title


def guess_artist_title(text):
    """'Artist - Title' (a YouTube title or a file name) -> (artist, title). Artist may be None."""
    text = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", text or "")
    text = _clean_title(text)
    text = re.sub(r"^\s*\d{1,3}\s*[-._)]\s+", "", text)           # a leading track number: "13 - "
    for separator in (" - ", " \u2013 ", " \u2014 ", " | "):
        if separator in text:
            artist, title = text.split(separator, 1)
            return artist.strip() or None, title.strip()
    return None, text.strip()


def _score(candidate, artist, title, duration):
    """Higher is a better match for what we asked about."""
    score = 0.0
    if duration and candidate.get("duration"):
        gap = abs(float(candidate["duration"]) - duration)
        score += 4 if gap <= 2 else 2 if gap <= 5 else 0 if gap <= 12 else -3
    name = (candidate.get("trackName") or "").lower()
    wanted = (title or "").lower()
    if wanted and (wanted == name or wanted in name or name in wanted):
        score += 3
    if artist and artist.lower() in (candidate.get("artistName") or "").lower():
        score += 3
    if candidate.get("syncedLyrics"):
        score += 2
    elif candidate.get("plainLyrics"):
        score += 0.5
    else:
        score -= 10                                        # instrumental / empty
    return score


def fetch_lrclib(artist, title, album=None, duration=None):
    """Look a song up on LRCLIB. Returns a lyrics result, or None if nothing was found."""
    title = _clean_title(title or "")
    if not title:
        return None
    candidates = []
    if artist:
        params = {"artist_name": artist, "track_name": title}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(round(duration))
        try:
            candidates.append(_get_json(f"{LRCLIB}/get?{urllib.parse.urlencode(params)}"))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    if not candidates or not (candidates[0].get("syncedLyrics") or candidates[0].get("plainLyrics")):
        query = {"track_name": title}
        if artist:
            query["artist_name"] = artist
        found = _get_json(f"{LRCLIB}/search?{urllib.parse.urlencode(query)}")
        if not found and artist:
            found = _get_json(f"{LRCLIB}/search?{urllib.parse.urlencode({'q': artist + ' ' + title})}")
        candidates = list(found or []) + candidates
    candidates = [c for c in candidates if c and (c.get("syncedLyrics") or c.get("plainLyrics"))]
    if not candidates:
        return None
    best = max(candidates, key=lambda c: _score(c, artist, title, duration))
    matched = {"artist": best.get("artistName"), "title": best.get("trackName"),
               "album": best.get("albumName"), "duration": best.get("duration"), "lrclib_id": best.get("id")}
    return make_result(best.get("syncedLyrics") or best.get("plainLyrics"), "lrclib", matched)


# --- one call for a freshly made song ------------------------------------------------------------

def find_for_song(tags=None, fallback_name=None, extra=None):
    """Lyrics for a song: the file's own tags first, then LRCLIB.

    tags: from read_tags(). fallback_name: a title or file name to guess artist/title from.
    extra: overrides, e.g. {"artist": ..., "title": ..., "duration": ...} from a YouTube lookup.
    Returns (lyrics result or None, metadata dict). Never raises: lyrics are a bonus.
    """
    meta = dict(artist=None, title=None, album=None, duration=None)
    for source in (tags or {}, extra or {}):
        for key in meta:
            if source.get(key):
                meta[key] = source[key]
    if not meta["title"] and fallback_name:
        guessed_artist, guessed_title = guess_artist_title(fallback_name)
        meta["title"] = guessed_title
        meta["artist"] = meta["artist"] or guessed_artist
    elif meta["title"] and not meta["artist"]:
        guessed_artist, guessed_title = guess_artist_title(meta["title"])
        if guessed_artist:
            meta["artist"], meta["title"] = guessed_artist, guessed_title

    if tags and tags.get("lyrics"):
        result = make_result(tags["lyrics"], "embedded", {"artist": meta["artist"], "title": meta["title"]})
        # Un-synced lyrics in the file: see whether LRCLIB has a synced version of the same song.
        if result and result["synced"]:
            return result, meta
        try:
            online = fetch_lrclib(meta["artist"], meta["title"], meta["album"], meta["duration"])
            if online and online["synced"]:
                return online, meta
        except Exception:
            pass
        return result, meta
    try:
        return fetch_lrclib(meta["artist"], meta["title"], meta["album"], meta["duration"]), meta
    except Exception:
        return None, meta
