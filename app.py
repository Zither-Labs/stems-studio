"""
Stems Studio - desktop app entry point.

Starts the local engine and opens it in its own window (Chrome or Edge in "app mode":
no tabs, no address bar). Closing the window quits the app.

Double-click the Stems Studio shortcut made by Install.bat, or run:  python app.py
"""

import os
import shutil
import subprocess
import sys
import traceback
import webbrowser

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


def open_window(url):
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


def main():
    route_output_to_log()

    running = server.find_running_instance()
    if running:
        open_window(running)
        return

    httpd = server.create_server()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"Stems Studio is ready at {url}")
    open_window(url)
    server.serve(httpd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        route_output_to_log()
        traceback.print_exc()
        show_error(f"Stems Studio could not start.\n\nDetails were saved to:\n{LOG_PATH}")
        sys.exit(1)
