"""
Stems Studio - update check.

Checks GitHub to see if newer versions exist and brings them in with 1-click:
- If installed via Git: uses fast, safe 'git fetch' and 'git pull --ff-only'.
- If installed via ZIP or setup installer (no git): queries GitHub API for the latest
  main branch commit, and on 1-click update, fetches the update archive and safely
  updates the project files without touching virtual environments, models, or user libraries.

Set STEMS_STUDIO_NO_UPDATE_CHECK=1 to turn the check off.
"""

import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
RECHECK_SECONDS = 6 * 60 * 60        # while the app stays open
FIRST_CHECK_DELAY = 5                # let the window open first
MAX_CHANGES_LISTED = 12
USER_AGENT = "StemsStudio/1.0 (local desktop app)"
DEFAULT_REPO = "Zither-Labs/stems-studio"

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


def get_repo_slug():
    """Detect GitHub repo owner/name from git remotes or settings, defaulting to DEFAULT_REPO."""
    try:
        rem = _out(_git("remote", "get-url", "origin"))
        if rem:
            match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", rem, re.IGNORECASE)
            if match:
                return match.group(1)
    except Exception:
        pass
    settings_file = os.path.join(BASE_DIR, "settings.json")
    if os.path.isfile(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("github_repo"):
                    return data["github_repo"]
        except Exception:
            pass
    return DEFAULT_REPO


def get_local_version():
    """Returns the current short commit SHA or version string."""
    try:
        sha = _out(_git("rev-parse", "--short", "HEAD"))
        if sha:
            return sha
    except Exception:
        pass
    vfile = os.path.join(BASE_DIR, "version.json")
    if os.path.isfile(vfile):
        try:
            with open(vfile, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("version"):
                    return str(data["version"])
        except Exception:
            pass
    return None


def fetch_github_latest(repo_slug):
    """Fetch the latest commit info from GitHub API. Returns (sha, message)."""
    api_url = f"https://api.github.com/repos/{repo_slug}/commits/main"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        sha = data.get("sha", "")
        msg = data.get("commit", {}).get("message", "Updated Stems Studio")
        return sha, msg.splitlines()[0]


def update_plan(branch, head, remote, ahead, dirty):
    """What Update should do for a git checkout."""
    if dirty:
        return "dirty"
    if branch == "main" and ahead:
        return "ahead"
    if head != remote or branch != "main":
        return "update"
    return "current"


def check():
    """Ask GitHub whether main is newer than this copy. Returns the new state."""
    if not enabled():
        _set(state="off")
        return get_state()

    has_git = os.path.isdir(os.path.join(BASE_DIR, ".git"))
    git_working = False
    if has_git:
        try:
            git_working = (_git("--version").returncode == 0)
        except Exception:
            git_working = False

    _set(state="checking")

    # 1. Try Git update check if this is a working git clone
    if git_working:
        try:
            fetched = _git("fetch", "origin", "main", "--quiet", timeout=40)
            if fetched.returncode == 0:
                branch = _out(_git("rev-parse", "--abbrev-ref", "HEAD"))
                head = _out(_git("rev-parse", "HEAD"))
                remote = _out(_git("rev-parse", "origin/main"))
                if remote:
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
                    newer = plan == "update" or (plan == "dirty" and (head != remote or branch != "main"))
                    state = "available" if newer else "current"
                    _set(state=state, behind=behind, ahead=ahead, dirty=dirty, plan=plan,
                         changes=changes, branch=branch, method="git",
                         current=_out(_git("rev-parse", "--short", "HEAD")), checked_at=time.time())
                    return get_state()
        except Exception:
            # Fall back to HTTP API check if git fails
            pass

    # 2. HTTP API check (for ZIP downloads, installer copies, or offline git)
    try:
        repo_slug = get_repo_slug()
        latest_sha, commit_msg = fetch_github_latest(repo_slug)
        local_ver = get_local_version()
        remote_short = latest_sha[:7] if latest_sha else ""

        if local_ver and latest_sha.startswith(local_ver):
            _set(state="current", current=local_ver, remote=remote_short, method="zip", checked_at=time.time())
        else:
            _set(state="available", plan="update", behind=1, changes=[commit_msg],
                 current=local_ver or "installed", remote=remote_short, target_sha=latest_sha,
                 repo_slug=repo_slug, method="zip", checked_at=time.time())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # Private repo without auth or not found
            _set(state="current", reason="Repository is private or cannot be reached anonymously.", checked_at=time.time())
        else:
            _set(state="error", reason=f"GitHub check error: HTTP {exc.code}", checked_at=time.time())
    except Exception as exc:
        _set(state="error", reason=str(exc), checked_at=time.time())

    return get_state()


def apply_zip_update(target_sha=None, repo_slug=None):
    """Download the newest main zip archive and update project files safely."""
    slug = repo_slug or get_repo_slug()
    zip_url = f"https://github.com/{slug}/archive/refs/heads/main.zip"

    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            zip_bytes = resp.read()

        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        namelist = zf.namelist()
        if not namelist:
            return {"ok": False, "message": "The downloaded update archive was empty."}

        root_folder = namelist[0].split('/')[0] + '/'

        PROTECTED = {
            ".venv", ".venv-roformer", ".chord-tools", "__pycache__",
            "library.db", "settings.json", "practice.json", ".git"
        }

        changed_files = []
        for member in zf.infolist():
            if not member.filename.startswith(root_folder):
                continue
            rel = member.filename[len(root_folder):]
            if not rel or rel.endswith('/'):
                continue

            first_segment = rel.split('/')[0]
            if first_segment in PROTECTED or rel in PROTECTED:
                continue

            dest_path = os.path.join(BASE_DIR, rel.replace('/', os.sep))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            with zf.open(member) as src, open(dest_path, "wb") as dst:
                dst.write(src.read())
            changed_files.append(rel)

        # Update local version.json marker
        if target_sha:
            vfile = os.path.join(BASE_DIR, "version.json")
            try:
                with open(vfile, "w", encoding="utf-8") as f:
                    json.dump({"version": target_sha[:7], "sha": target_sha, "updated_at": time.time()}, f, indent=2)
            except Exception:
                pass

        run_install = any(name.lower() in ("install.bat", "install.command", "separator/requirements.txt") for name in changed_files)
        return {"ok": True, "message": "Updated. Reopening Stems Studio.", "run_install": run_install, "restart": True}
    except Exception as exc:
        return {"ok": False, "message": f"Update failed: {exc}"}


def apply():
    """Bring in the newest version. Returns {"ok": bool, ...}."""
    info = check()
    plan = info.get("plan")
    if info["state"] != "available":
        return {"ok": False, "message": "Already up to date." if info["state"] == "current"
                else info.get("reason", "Cannot update right now.")}

    if info.get("method") == "zip":
        return apply_zip_update(target_sha=info.get("target_sha"), repo_slug=info.get("repo_slug"))

    # Git update flow
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
            "run_install": any(name.lower() in ("install.bat", "install.command") for name in changed),
            "restart": True}


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
