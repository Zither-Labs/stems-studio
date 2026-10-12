"""
Stems Studio - update check.

When the app folder is a git checkout (it is when it was cloned from GitHub), this asks the
repository whether newer versions exist, and can bring them in with one click.

It never changes anything by itself: the check only *reads* (git fetch), and the update only runs
when you press the button, and only as a plain fast-forward (git pull --ff-only), so your own
edits are never overwritten. Set STEMS_STUDIO_NO_UPDATE_CHECK=1 to turn the check off.
"""

import os
import subprocess
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
RECHECK_SECONDS = 6 * 60 * 60        # while the app stays open
FIRST_CHECK_DELAY = 5                # let the window open first
MAX_CHANGES_LISTED = 12

_lock = threading.Lock()
_state = {"state": "idle", "checked_at": None}


def _git(*args, timeout=30):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")     # never wait for a password prompt nobody can see
    return subprocess.run(
        ["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout,
        env=env, **NO_WINDOW)


def _out(result):
    return (result.stdout or "").strip()


def enabled():
    return not os.environ.get("STEMS_STUDIO_NO_UPDATE_CHECK")


def get_state():
    with _lock:
        return dict(_state)


def _set(**values):
    with _lock:
        _state.clear()
        _state.update(values)


def check():
    """Ask the repository whether there is something newer. Returns the new state."""
    if not enabled():
        _set(state="off")
        return get_state()
    if not os.path.isdir(os.path.join(BASE_DIR, ".git")):
        _set(state="unsupported", reason="This copy was not installed with git, so it cannot update itself.")
        return get_state()
    try:
        if _git("--version").returncode != 0:
            raise FileNotFoundError("git")
    except (OSError, subprocess.SubprocessError):
        _set(state="unsupported", reason="Git is not installed, so updates cannot be checked.")
        return get_state()

    _set(state="checking")
    try:
        fetched = _git("fetch", "--quiet", timeout=40)
        if fetched.returncode != 0:
            raise RuntimeError((fetched.stderr or "git fetch failed").strip().splitlines()[-1])
        upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if upstream.returncode != 0:
            raise RuntimeError("This branch does not follow a branch on GitHub.")
        counts = _out(_git("rev-list", "--left-right", "--count", "HEAD...@{u}")).split()
        ahead, behind = int(counts[0]), int(counts[1])
        dirty = bool(_out(_git("status", "--porcelain", "--untracked-files=no")))
        changes = []
        if behind:
            log = _out(_git("log", "--format=%s", f"-{MAX_CHANGES_LISTED}", "HEAD..@{u}"))
            changes = [line for line in log.splitlines() if line.strip()]
        _set(state="available" if behind else "current", behind=behind, ahead=ahead, dirty=dirty,
             changes=changes, branch=_out(_git("rev-parse", "--abbrev-ref", "HEAD")),
             current=_out(_git("rev-parse", "--short", "HEAD")), checked_at=time.time())
    except subprocess.TimeoutExpired:
        _set(state="error", reason="The check took too long (no internet?).", checked_at=time.time())
    except Exception as exc:
        _set(state="error", reason=str(exc), checked_at=time.time())
    return get_state()


def apply():
    """Bring in the newer versions. Returns {"ok": bool, "message": str, ...}."""
    info = check()
    if info["state"] != "available":
        return {"ok": False, "message": "Already up to date." if info["state"] == "current"
                else info.get("reason", "Cannot update right now.")}
    if info.get("dirty"):
        return {"ok": False, "message": "This copy has changes of its own that are not saved in git, "
                                        "so it was not updated. Commit or undo them first."}
    if info.get("ahead"):
        return {"ok": False, "message": "This copy has versions of its own that are not on GitHub, "
                                        "so it cannot be fast-forwarded. Update it by hand with git."}
    try:
        before = _out(_git("rev-parse", "HEAD"))
        pulled = _git("pull", "--ff-only", "--quiet", timeout=120)
        if pulled.returncode != 0:
            raise RuntimeError((pulled.stderr or pulled.stdout or "git pull failed").strip().splitlines()[-1])
        changed = _out(_git("diff", "--name-only", before, "HEAD")).splitlines()
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "The update took too long. Nothing was changed; try again."}
    except Exception as exc:
        return {"ok": False, "message": f"The update failed: {exc}"}
    check()
    return {"ok": True, "message": "Updated. Close Stems Studio and open it again to use the new version.",
            "run_install": any(name.lower() in ("install.bat", "install.command") for name in changed)}


def start_background_checks():
    """Check shortly after start-up, then now and then while the app stays open."""
    if not enabled():
        return

    def loop():
        time.sleep(FIRST_CHECK_DELAY)
        while True:
            check()
            time.sleep(RECHECK_SECONDS)

    threading.Thread(target=loop, daemon=True).start()
