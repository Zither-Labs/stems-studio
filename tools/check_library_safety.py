"""Checks the library changes: missing songs stay listed, a new split replaces that row,
clean-vocals backups restore, practice is stored beside the song, and the folder setting sticks.

Run:  python tools/check_library_safety.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


def main():
    tmp = tempfile.mkdtemp(prefix="stems-library-")
    old = {
        "DATA_DIR": server.DATA_DIR,
        "SETTINGS_PATH": server.SETTINGS_PATH,
        "OUTPUT_DIR": server.OUTPUT_DIR,
        "DB_PATH": server.DB_PATH,
        "LIBRARY_NOTE": server.LIBRARY_NOTE,
    }
    locked = os.environ.pop("STEMS_STUDIO_LIBRARY", None)
    try:
        server.DATA_DIR = tmp
        server.SETTINGS_PATH = os.path.join(tmp, "settings.json")
        library = os.path.join(tmp, "library")
        os.makedirs(library)
        assert server.use_library_dir(library) == ""
        server.init_library()

        song_id = "abcd1234"
        folder = os.path.join(library, song_id)
        os.makedirs(folder)
        vocals = os.path.join(folder, "vocals.wav")
        with open(vocals, "wb") as handle:
            handle.write(b"old-vocal")
        stems = [{"id": "vocals", "name": "Vocals", "url": f"/api/stems/{song_id}/vocals.wav", "empty": False}]
        server.save_song(song_id, "Test Song", "file", "test.wav", "file:abc", "htdemucs_6s", "standard", stems)

        listed = server.list_songs()
        assert len(listed) == 1 and listed[0]["missing"] is False, listed
        os.remove(vocals)
        listed = server.list_songs()
        assert len(listed) == 1 and listed[0]["missing"] is True, listed
        assert server.find_cached_song("file:abc", "htdemucs_6s", "standard") is None
        assert len(server.list_songs()) == 1, "a missing song must stay in the library"

        song2 = "abcd1235"
        folder2 = os.path.join(library, song2)
        os.makedirs(folder2)
        with open(os.path.join(folder2, "vocals.wav"), "wb") as handle:
            handle.write(b"new-vocal")
        stems2 = [{"id": "vocals", "name": "Vocals", "url": f"/api/stems/{song2}/vocals.wav", "empty": False}]
        server.save_song(song2, "Test Song", "file", "test.wav", "file:abc", "htdemucs_6s", "standard", stems2)
        ids = {row["id"] for row in server.list_songs()}
        assert ids == {song2}, ids

        guitar = os.path.join(folder2, "guitar.wav")
        with open(guitar, "wb") as handle:
            handle.write(b"old-guitar")
        with open(os.path.join(folder2, "vocals.wav"), "wb") as handle:
            handle.write(b"old-vocal")
        backups = {
            "vocals": server.keep_backup(folder2, "vocals", os.path.join(folder2, "vocals.wav")),
            "guitar": server.keep_backup(folder2, "guitar", guitar),
        }
        with open(os.path.join(folder2, "vocals.wav"), "wb") as handle:
            handle.write(b"cleaned")
        with open(guitar, "wb") as handle:
            handle.write(b"with-leftover")
        again = server.keep_backup(folder2, "vocals", os.path.join(folder2, "vocals.wav"))
        assert again == backups["vocals"]
        with open(os.path.join(folder2, backups["vocals"]), "rb") as handle:
            assert handle.read() == b"old-vocal"
        with open(os.path.join(folder2, server.CLEANED_VOCALS_MARKER), "w", encoding="utf-8") as handle:
            server.json.dump({"model": "test", "leftover_went_to": "guitar", "backups": backups}, handle)
        summary = server.list_songs()[0]
        assert summary["vocals_can_undo"] is True, summary
        server.restore_clean_backups(folder2)
        with open(os.path.join(folder2, "vocals.wav"), "rb") as handle:
            assert handle.read() == b"old-vocal"
        with open(guitar, "rb") as handle:
            assert handle.read() == b"old-guitar"
        assert not os.path.isfile(os.path.join(folder2, server.CLEANED_VOCALS_MARKER))
        assert os.path.isfile(os.path.join(folder2, backups["vocals"]))

        assert server.write_practice(song2, {
            "coach_history": [{"date": 10, "score": 80, "level": "medium"}, {"score": "nope"}, {"date": 11, "score": 140, "level": "nope"}],
            "lyrics_offset": 12.34,
        })
        practice = server.read_practice(song2)
        assert practice["stored"] is True
        assert practice["lyrics_offset"] == 12.3
        assert practice["coach_history"] == [
            {"date": 10, "score": 80, "level": "medium"},
            {"date": 11, "score": 100, "level": "beginner"},
        ], practice

        httpd = server.create_server(0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def ask(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}", data=data,
                headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(request) as resp:
                return json.load(resp)

        listing = ask("/api/library")
        assert listing["songs"] and listing["songs"][0]["id"] == song2, listing
        assert listing["folder_locked"] is False
        saved = ask(f"/api/library/{song2}/practice", {"coach_history": [{"date": 3, "score": 70, "level": "beginner"}], "lyrics_offset": -0.5})
        assert saved["lyrics_offset"] == -0.5 and saved["coach_history"][0]["score"] == 70, saved
        prefs = ask("/api/preferences", {"voice_type": "alto"})
        assert prefs["voice_type"] == "alto"
        assert ask("/api/preferences")["voice_type"] == "alto"
        httpd.shutdown()

        for song_id, artist, track in (
            ("aa000001", "Zebra", "Apple"),
            ("aa000002", "adele", "Hello"),
            ("aa000003", "Adele", "Skyfall"),
        ):
            folder = os.path.join(library, song_id)
            os.makedirs(folder)
            with open(os.path.join(folder, "vocals.wav"), "wb") as handle:
                handle.write(b"x")
            with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
                json.dump({"artist": artist, "title": track}, handle)
            stems = [{"id": "vocals", "name": "Vocals", "url": f"/api/stems/{song_id}/vocals.wav", "empty": False}]
            server.save_song(song_id, "raw", "file", "t.wav", f"file:{song_id}", "htdemucs_6s", "standard", stems)
        titles = [row["title"] for row in server.list_songs()]
        assert titles == ["adele - Hello", "Adele - Skyfall", "Test Song", "Zebra - Apple"], titles

        assert server.set_voice_type("tenor")
        other = os.path.join(tmp, "other")
        assert server.set_library_folder(other) == ""
        assert os.path.normcase(server.OUTPUT_DIR) == os.path.normcase(other)
        settings = server.read_settings()
        assert settings["voice_type"] == "tenor", settings
        assert os.path.normcase(settings["library_dir"]) == os.path.normcase(other)
        assert "full path" in server.set_library_folder("not-a-full-path")
        os.environ["STEMS_STUDIO_LIBRARY"] = library
        assert "STEMS_STUDIO_LIBRARY" in server.set_library_folder(other)
        print("library safety checks passed")
    finally:
        server.DATA_DIR = old["DATA_DIR"]
        server.SETTINGS_PATH = old["SETTINGS_PATH"]
        server.OUTPUT_DIR = old["OUTPUT_DIR"]
        server.DB_PATH = old["DB_PATH"]
        server.LIBRARY_NOTE = old["LIBRARY_NOTE"]
        if locked is None:
            os.environ.pop("STEMS_STUDIO_LIBRARY", None)
        else:
            os.environ["STEMS_STUDIO_LIBRARY"] = locked
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
