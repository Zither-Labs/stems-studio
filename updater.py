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


def update_plan(branch, head, remote, ahead, dirty):
    """What Update should do. The published copy is origin/main, not whatever branch is checked out.

    ahead is how many commits on main are not on origin/main. Commits on some other branch do not
    count: switching to main leaves them where they are.
    """
    if dirty:
        return "dirty"
    if branch == "main" and ahead:
        return "ahead"
    if head != remote or branch != "main":
        return "update"
    return "current"


def check():
    """Ask GitHub whether origin/main is newer than this copy. Returns the new state."""
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
        fetched = _git("fetch", "origin", "main", "--quiet", timeout=40)
        if fetched.returncode != 0:
            raise RuntimeError((fetched.stderr or "git fetch failed").strip().splitlines()[-1])
        branch = _out(_git("rev-parse", "--abbrev-ref", "HEAD"))
        head = _out(_git("rev-parse", "HEAD"))
        remote = _out(_git("rev-parse", "origin/main"))
        if not remote:
            raise RuntimeError("The main copy was not found on GitHub.")
        ahead = 0
        if branch == "main":
            ahead = int(_out(_git("rev-list", "--count", "origin/main..HEAD")) or "0")
        behind = int(_out(_git("rev-list", "--count", "HEAD..origin/main")) or "0")
        dirty = bool(_out(_git("status", "--porcelain", "--untracked-files=no")))
        plan = update_plan(branch, head, remote, ahead, dirty)
        changes = []
        if behind:
            log = _out(_git("log", "--format=%s", f"-{MAX_CHANGES_LISTED}", "HEAD..origin/main"))
            changes = [line for line in log.splitlines() if line.strip()]
        # A dirty folder only matters when there is actually something to bring in.
        newer = plan == "update" or (plan == "dirty" and (head != remote or branch != "main"))
        state = "available" if newer else "current"
        _set(state=state, behind=behind, ahead=ahead, dirty=dirty, plan=plan,
             changes=changes, branch=branch,
             current=_out(_git("rev-parse", "--short", "HEAD")), checked_at=time.time())
    except subprocess.TimeoutExpired:
        _set(state="error", reason="The check took too long (no internet?).", checked_at=time.time())
    except Exception as exc:
        _set(state="error", reason=str(exc), checked_at=time.time())
    return get_state()


def apply():
    """Bring in origin/main, the same copy Update Stems Studio downloads. Returns {"ok": bool, ...}."""
    info = check()
    plan = info.get("plan")
    if info["state"] != "available":
        return {"ok": False, "message": "Already up to date." if info["state"] == "current"
                else info.get("reason", "Cannot update right now.")}
    if plan == "dirty" or info.get("dirty"):
        return {"ok": False, "message": "This copy has changes of its own that are not saved in git, "
                                        "so it was not updated. Commit or undo them first."}
    if plan == "ahead" or (info.get("branch") == "main" and info.get("ahead")):
        return {"ok": False, "message": "This copy has versions of its own that are not on GitHub, "
                                        "so it cannot be fast-forwarded. Update it by hand with git."}
    try:
        before = _out(_git("rev-parse", "HEAD"))
        if info.get("branch") != "main":
            if _git("rev-parse", "--verify", "main").returncode != 0:
                switched = _git("checkout", "-b", "main", "origin/main")
            else:
                switched = _git("checkout", "main")
            if switched.returncode != 0:
                detail = (switched.stderr or switched.stdout or "could not switch to the main copy").strip()
                raise RuntimeError(detail.splitlines()[-1])
        ahead_now = int(_out(_git("rev-list", "--count", "origin/main..HEAD")) or "0")
        if ahead_now:
            return {"ok": False, "message": "This copy has versions of its own that are not on GitHub, "
                                            "so it cannot be fast-forwarded. Update it by hand with git."}
        pulled = _git("pull", "--ff-only", "origin", "main", "--quiet", timeout=120)
        if pulled.returncode != 0:
            raise RuntimeError((pulled.stderr or pulled.stdout or "git pull failed").strip().splitlines()[-1])
        changed = _out(_git("diff", "--name-only", before, "HEAD")).splitlines()
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "The update took too long. Nothing was changed; try again."}
    except Exception as exc:
        return {"ok": False, "message": f"The update failed: {exc}"}
    return {"ok": True, "message": "Updated. Reopening Stems Studio.",
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
