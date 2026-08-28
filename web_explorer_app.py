#!/usr/bin/env python3
"""Serve the standalone SL4 Web Explorer and its optional local graph data."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable


APP_ROOT = Path(__file__).resolve().parent
WEB_EXPLORER_NAME = "web_explorer_v4.html"
GRAPH_DIRECTORY_NAMES = ("4x4_All_graph_data", "hourglass_disk_4x4_all_graph_data")


class WebExplorerError(RuntimeError):
    """A collaborator-facing Web Explorer setup problem."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8766)
    result.add_argument(
        "--project-root",
        type=Path,
        default=Path(os.environ.get("PROBLEM3_ROOT", APP_ROOT)),
        help="Graph-data folder or a folder containing the downloaded graph data.",
    )
    result.add_argument(
        "--html",
        type=Path,
        default=None,
        help=f"Optional explicit {WEB_EXPLORER_NAME} file.",
    )
    result.add_argument(
        "--branch-url",
        default="http://127.0.0.1:8765/branch",
        help="Pairing Explorer URL used by the navigation button.",
    )
    return result


def _unique(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    output: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            output.append(resolved)
    return tuple(output)


def content_roots(project_root: Path) -> tuple[Path, ...]:
    root = project_root.expanduser().resolve()
    roots = [APP_ROOT, root]
    if root.name in GRAPH_DIRECTORY_NAMES:
        roots.append(root.parent)
    roots.extend((APP_ROOT.parent, root.parent))
    return _unique(roots)


def find_web_explorer(project_root: Path, explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit is not None else []
    candidates.extend(root / WEB_EXPLORER_NAME for root in content_roots(project_root))
    for candidate in candidates:
        if candidate is not None and candidate.expanduser().is_file():
            return candidate.expanduser().resolve()
    raise WebExplorerError(
        f"Could not find {WEB_EXPLORER_NAME}. Add that file to the GitHub repository root."
    )


def graph_directory(project_root: Path) -> Path | None:
    root = project_root.expanduser().resolve()
    if root.name in GRAPH_DIRECTORY_NAMES and root.is_dir():
        return root
    for name in GRAPH_DIRECTORY_NAMES:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return None


def safe_file_for_route(route: str, project_root: Path) -> Path | None:
    relative = Path(urllib.parse.unquote(route).lstrip("/"))
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    graph_dir = graph_directory(project_root)
    if graph_dir is not None and relative.parts[0] in GRAPH_DIRECTORY_NAMES:
        candidate = graph_dir.joinpath(*relative.parts[1:]).resolve()
        if candidate.is_relative_to(graph_dir.resolve()) and candidate.is_file():
            return candidate
    for root in content_roots(project_root):
        candidate = (root / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return None


def page_with_navigation(web_explorer: Path, branch_url: str) -> bytes:
    source = web_explorer.read_text(encoding="utf-8")
    navigation = (
        '<nav style="position:sticky;top:0;z-index:1000;display:flex;justify-content:flex-end;'
        'padding:8px 0;background:#f8f8f8;border-bottom:1px solid #ddd">'
        f'<a href="{html.escape(branch_url, quote=True)}" style="display:inline-block;padding:8px 14px;'
        'border-radius:5px;background:#17202a;color:white;text-decoration:none;'
        'font-family:Arial,sans-serif;font-weight:bold">Open Pairing Explorer</a></nav>'
    )
    if "<body>" in source:
        source = source.replace("<body>", "<body>" + navigation, 1)
    else:
        source = navigation + source
    return source.encode("utf-8")


def make_handler(web_explorer: Path, project_root: Path, branch_url: str):
    page = page_with_navigation(web_explorer, branch_url)

    class WebExplorerHandler(BaseHTTPRequestHandler):
        def _send(self, payload: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            route = urllib.parse.urlparse(self.path).path
            if route == "/health":
                payload = json.dumps({"status": "ready", "app": "web_explorer"}).encode("utf-8")
                self._send(payload, "application/json")
                return
            if route in {"/", f"/{WEB_EXPLORER_NAME}"}:
                self._send(page, "text/html; charset=utf-8")
                return
            file_path = safe_file_for_route(route, project_root)
            if file_path is None:
                self._send(b"Not found", "text/plain; charset=utf-8", status=404)
                return
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            self._send(file_path.read_bytes(), content_type)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return WebExplorerHandler


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(list(argv) if argv is not None else None)
    try:
        explorer = find_web_explorer(args.project_root, args.html)
        server = ThreadingHTTPServer(
            (args.host, args.port),
            make_handler(explorer, args.project_root, args.branch_url),
        )
        print(f"Web Explorer running at http://{args.host}:{args.port}/")
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except WebExplorerError as exc:
        print(f"Could not start Web Explorer: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
