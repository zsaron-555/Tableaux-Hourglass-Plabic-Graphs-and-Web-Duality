#!/usr/bin/env python3
"""Start every local repository interface from one collaborator command.

This launcher starts the authoritative exact tagged checker (which supplies
the combined Pairing Explorer), the standalone Web Explorer, and a
small home page linking the two distinct entry points.
"""

from __future__ import annotations

import argparse
import errno
import html
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable

from web_explorer_app import find_web_explorer


REPO_ROOT = Path(__file__).resolve().parent
EXACT_APP = REPO_ROOT / "python_exact_tree" / "exact_checker_tree_app_20260826.py"
WEB_EXPLORER_APP = REPO_ROOT / "web_explorer_app.py"
PYTHON_REQUIREMENTS = REPO_ROOT / "python_exact_tree" / "requirements.txt"
REPOSITORY_TITLE = "Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality"
GRAPH_DATA_DOWNLOAD_URL = (
    "https://github.com/zsaron-555/"
    "Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality/releases/download/"
    "sl4-web-data-v1/4x4_All_graph_data_260815.zip"
)
GRAPH_DIRECTORY_NAMES = (
    "4x4_All_graph_data",
    "hourglass_disk_4x4_all_graph_data",
)


class LaunchError(RuntimeError):
    """A collaborator-facing startup problem."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help=(
            "Extracted 4x4_All_graph_data folder, or the folder containing it. "
            "Defaults to PROBLEM3_ROOT or an automatically discovered folder."
        ),
    )
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--home-port", type=int, default=8764)
    result.add_argument("--exact-port", type=int, default=8765)
    result.add_argument("--web-port", type=int, default=8766)
    result.add_argument("--no-browser", action="store_true")
    result.add_argument(
        "--skip-install",
        action="store_true",
        help="Check existing dependencies without installing missing ones.",
    )
    result.add_argument(
        "--check-only",
        action="store_true",
        help="Validate data and dependencies, then exit without starting servers.",
    )
    return result


def _contains_graph_data(path: Path) -> bool:
    return path.is_dir() and any(path.glob("*.json"))


def resolve_project_root(value: Path | None) -> Path:
    candidates: list[Path] = []
    if value is not None:
        candidates.append(value)
    environment_root = os.environ.get("PROBLEM3_ROOT", "").strip()
    if environment_root:
        candidates.append(Path(environment_root))
    candidates.extend(
        [
            REPO_ROOT,
            REPO_ROOT.parent,
            Path.cwd(),
            Path.home() / "Downloads",
            Path.home() / "Documents",
            Path.home() / "Desktop",
        ]
    )

    seen: set[Path] = set()
    for raw in candidates:
        candidate = raw.expanduser().resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.name in GRAPH_DIRECTORY_NAMES and _contains_graph_data(candidate):
            return candidate
        for name in GRAPH_DIRECTORY_NAMES:
            graph_dir = candidate / name
            if _contains_graph_data(graph_dir):
                return candidate

    requested = value.expanduser().resolve() if value is not None else None
    suffix = f" at {requested}" if requested is not None else ""
    raise LaunchError(
        "Could not find the extracted 4x4 graph data"
        f"{suffix}. Download and extract {GRAPH_DATA_DOWNLOAD_URL}, then pass "
        "--project-root with either the graph folder or its containing folder."
    )


def _python_has_requirements(executable: Path) -> bool:
    check = subprocess.run(
        [str(executable), "-c", "import numpy"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return check.returncode == 0


def ensure_python_runtime(skip_install: bool) -> Path:
    current = Path(sys.executable).resolve()
    if _python_has_requirements(current):
        return current
    if skip_install:
        raise LaunchError(
            f"Python dependencies are missing. Run without --skip-install so {Path(__file__).name} can install them."
        )

    environment = REPO_ROOT / ".problem3-venv"
    if os.name == "nt":
        environment_python = environment / "Scripts" / "python.exe"
    else:
        environment_python = environment / "bin" / "python"
    if not environment_python.is_file():
        print("Preparing the local Python environment (first run only)...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    if not _python_has_requirements(environment_python):
        subprocess.run(
            [
                str(environment_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(PYTHON_REQUIREMENTS),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
    if not _python_has_requirements(environment_python):
        raise LaunchError("The local Python dependency installation did not complete.")
    return environment_python


def ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                message = f"Port {port} is already in use. Stop the other app or choose a different port."
            else:
                message = f"Could not use {host}:{port}: {exc}"
            raise LaunchError(message) from exc


def wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LaunchError(f"A required app stopped during startup with exit code {process.returncode}.")
        try:
            with opener.open(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise LaunchError(f"Timed out waiting for {url}: {last_error}")


def _process_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def home_page(exact_url: str, web_url: str, _project_root: Path) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{REPOSITORY_TITLE} — Tools</title><style>
body{{margin:0;background:#f5f6f8;color:#17202a;font-family:Arial,sans-serif}}main{{max-width:880px;margin:60px auto;padding:0 24px}}
h1{{font-size:32px;margin-bottom:8px}}p{{color:#667481}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-top:28px}}
a.card{{display:block;padding:22px;background:#fff;border:1px solid #d8dee6;border-radius:10px;color:#17202a;text-decoration:none}}a.card:hover{{border-color:#2586d8;box-shadow:0 5px 20px #17202a12}}a.card b{{display:block;font-size:19px;margin-bottom:8px}}code{{font-size:11px;overflow-wrap:anywhere}}
</style></head><body><main><h1>{REPOSITORY_TITLE} — Tools</h1><p>Choose the authoritative Pairing Explorer or the separate Web Explorer.</p>
<div class="grid">
<a class="card" href="{html.escape(exact_url)}/branch"><b>Pairing Explorer</b>Compute a pairing, inspect its complete tree, and step through every highlighted branch.</a>
<a class="card" href="{html.escape(web_url)}"><b>Web Explorer</b>Browse webs, transposes, survivors, and presentation-dependent catalogue graphs.</a>
</div><p><a href="{GRAPH_DATA_DOWNLOAD_URL}">Download the 4x4 graph data from GitHub</a>. Extract it anywhere on your laptop before starting these tools.</p></main></body></html>"""


def make_home_handler(exact_url: str, web_url: str, project_root: Path):
    body = home_page(exact_url, web_url, project_root).encode("utf-8")

    class HomeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/health"}:
                self.send_error(404)
                return
            payload = b'{"status":"ready"}' if self.path == "/health" else body
            content_type = "application/json" if self.path == "/health" else "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return HomeHandler


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(list(argv) if argv is not None else None)
    try:
        if not EXACT_APP.is_file() or not WEB_EXPLORER_APP.is_file():
            raise LaunchError("Run this launcher from an intact clone of the GitHub repository.")
        project_root = resolve_project_root(args.project_root)
        python_runtime = ensure_python_runtime(args.skip_install)
        web_explorer_html = find_web_explorer(project_root)
        if args.check_only:
            print("Ready: graph data found")
            print("Ready: Pairing Explorer and Web Explorer")
            return 0

        for port in (args.home_port, args.exact_port, args.web_port):
            ensure_port_available(args.host, port)
        exact_url = f"http://{args.host}:{args.exact_port}"
        web_url = f"http://{args.host}:{args.web_port}"
        home_url = f"http://{args.host}:{args.home_port}"
        environment = os.environ.copy()
        environment["PROBLEM3_ROOT"] = str(project_root)
        environment["PROBLEM3_WEB_EXPLORER_URL"] = web_url
        environment["BROWSER"] = "none"

        exact = subprocess.Popen(
            [
                str(python_runtime),
                str(EXACT_APP),
                "--project-root",
                str(project_root),
                "--host",
                args.host,
                "--port",
                str(args.exact_port),
            ],
            cwd=REPO_ROOT / "python_exact_tree",
            env=environment,
            **_process_options(),
        )
        web = subprocess.Popen(
            [
                str(python_runtime),
                str(WEB_EXPLORER_APP),
                "--project-root",
                str(project_root),
                "--html",
                str(web_explorer_html),
                "--branch-url",
                f"{exact_url}/branch",
                "--host",
                args.host,
                "--port",
                str(args.web_port),
            ],
            cwd=REPO_ROOT,
            env=environment,
            **_process_options(),
        )
        processes = [exact, web]
        try:
            wait_for_http(f"{exact_url}/health", exact, timeout=120)
            wait_for_http(f"{web_url}/health", web, timeout=180)
            server = ThreadingHTTPServer(
                (args.host, args.home_port),
                make_home_handler(exact_url, web_url, project_root),
            )
            print(f"{REPOSITORY_TITLE} tools are ready: {home_url}")
            print("Press Ctrl-C once to stop every app.")
            if not args.no_browser:
                webbrowser.open(home_url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        finally:
            for process in reversed(processes):
                stop_process(process)
        return 0
    except KeyboardInterrupt:
        print("Stopped all repository tools.")
        return 0
    except (LaunchError, subprocess.CalledProcessError) as exc:
        print(f"Could not start repository tools: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
