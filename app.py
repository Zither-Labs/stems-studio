"""
Stems Studio - desktop app entry point.

Starts the local engine and opens it in its own window (Chrome or Edge in "app mode":
no tabs, no address bar). Closing the window quits the app.

Double-click the Stems Studio shortcut made by Install.bat, or run:  python app.py
"""

import faulthandler
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser

# If launched with an external Python, re-exec inside the app's private .venv
_ROOT = os.path.dirname(os.path.abspath(__file__))
_VENV = os.path.join(_ROOT, ".venv")
if os.path.isdir(_VENV) and os.path.normcase(sys.prefix) != os.path.normcase(_VENV):
    if os.name == "nt":
        _is_gui = "pythonw" in sys.executable.lower()
        _target_py = os.path.join(_VENV, "Scripts", "pythonw.exe" if _is_gui else "python.exe")
        if not os.path.isfile(_target_py):
            _target_py = os.path.join(_VENV, "Scripts", "python.exe")
    else:
        _target_py = os.path.join(_VENV, "bin", "python")
    if os.path.isfile(_target_py) and os.path.normcase(sys.executable) != os.path.normcase(_target_py):
        sys.exit(subprocess.call([_target_py] + sys.argv))

import server

LOG_PATH = os.path.join(server.DATA_DIR, "stems-studio.log")
PROFILE_DIR = os.path.join(server.DATA_DIR, "window-profile")


def route_output_to_log():
    """pythonw.exe has no console; keep messages in a log file instead of losing them."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        if os.path.isfile(LOG_PATH) and os.path.getsize(LOG_PATH) > 512 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        # A crash inside a compiled library ends the process without a Python traceback.
        faulthandler.enable(log)
    except OSError:
        pass


def show_error(message):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Stems Studio", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def find_browser():
    """Chrome first, then Edge (always present on Windows 10/11)."""
    candidates = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
            root = os.environ.get(var)
            if not root:
                continue
            candidates += [
                os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    return next((path for path in candidates if os.path.isfile(path)), None)


def window_url(url, build):
    """A different address every build, so a window that is already open still loads the new page.

    Opening the same address again only brings that window forward, and it keeps the page it already has.
    """
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}build={build}"


def open_window(url, fresh=False):
    if fresh:
        url = window_url(url, server.APP_BUILD)
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return
    os.makedirs(PROFILE_DIR, exist_ok=True)
    subprocess.Popen(
        [
            browser,
            f"--app={url}",
            f"--user-data-dir={PROFILE_DIR}",
            "--window-size=1440,900",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **server.NO_WINDOW,
    )


def _listener_pids(port):
    """Process ids listening on this TCP port. Empty when the lookup tool is missing."""
    try:
        listed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in (listed.stdout or "").splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)
    return pids


def _stop_listener(port):
    """Stop whatever is still holding the app port after it was asked to quit."""
    if os.name == "nt":
        command = (
            "$conns = Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue;"
            "foreach ($conn in $conns) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }"
        ) % port
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **server.NO_WINDOW,
        )
        return
    pids = _listener_pids(port)
    if not pids:
        try:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    time.sleep(0.4)
    for pid in pids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _close_app_window():
    """Close the private app window. A second window with the same profile just wakes the old one."""
    if os.name == "nt":
        command = (
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.ProcessId -ne $PID -and $_.CommandLine -and "
            "$_.CommandLine.Contains($env:STEMS_PROFILE) "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, STEMS_PROFILE=PROFILE_DIR), **server.NO_WINDOW,
        )
        return
    try:
        listed = subprocess.run(
            ["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return
    for line in (listed.stdout or "").splitlines():
        pid_text, _, args = line.strip().partition(" ")
        if PROFILE_DIR not in args:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def replace_old_copy():
    """Stop an older engine so this launch is the one on screen.

    Returns False when that older engine is still answering. The open window keeps sending
    heartbeats, which cancels a polite quit, so the port is closed directly after a short wait.
    """
    info = server.probe_instance()
    if not info or server.same_build(info.get("version")):
        return True
    print(f"Stopping an older Stems Studio ({info.get('version')}) so this copy can open.")
    try:
        request = urllib.request.Request(info["url"] + "/api/closing", data=b"", method="POST")
        urllib.request.urlopen(request, timeout=2).read()
    except Exception:
        pass
    deadline = time.time() + 1.2
    while time.time() < deadline and server.probe_instance() is not None:
        time.sleep(0.2)
    if server.probe_instance() is not None:
        _stop_listener(server.PORT)
        deadline = time.time() + 4
        while time.time() < deadline and server.probe_instance() is not None:
            time.sleep(0.3)
    if server.probe_instance() is not None:
        return False
    _close_app_window()
    time.sleep(0.4)
    return True


def main():
    route_output_to_log()

    running = server.find_running_instance()
    if running:
        open_window(running, fresh=True)
        return

    if not replace_old_copy():
        show_error(
            "An older Stems Studio is still running, so this update did not open.\n\n"
            "Close every Stems Studio window, then double-click Update Stems Studio again."
        )
        return

    httpd = server.create_server()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"Stems Studio is ready at {url}")
    open_window(url, fresh=True)
    server.serve(httpd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        route_output_to_log()
        traceback.print_exc()
        show_error(f"Stems Studio could not start.\n\nDetails were saved to:\n{LOG_PATH}")
        sys.exit(1)
