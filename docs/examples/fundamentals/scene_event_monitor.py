"""DAZ Studio Script Server example: stream real-time scene-change events via SSE.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It connects to the GET /scene/events endpoint and streams
Server-Sent Events (SSE) as DAZ Studio reports them — node additions,
selection changes, time scrubs, renders starting and finishing, and more —
without polling or modifying the scene.

It is an *example*, not a production event-bus client.  A full production
integration would add reconnect backoff, structured logging, and per-event
callbacks.  The goal here is to show that the script server lets Python react
to live DAZ Studio activity in real time.

WHAT IT DEMONSTRATES
--------------------
  - Connecting to GET /scene/events with requests (stream=True)
  - Parsing raw Server-Sent Events from a chunked HTTP response
  - Filtering event categories with the ?filter= query parameter
  - Graceful Ctrl+C shutdown
  - Three usage modes:
      monitor  — pretty-print events to the terminal as they arrive
      log      — write a timestamped JSONL log file
      wait-for — block until one matching event arrives, then exit

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Start DAZ Studio with a scene loaded, then run one of:

       python docs/examples/fundamentals/scene_event_monitor.py monitor
       python docs/examples/fundamentals/scene_event_monitor.py monitor --filter node,selection
       python docs/examples/fundamentals/scene_event_monitor.py log --out events.jsonl
       python docs/examples/fundamentals/scene_event_monitor.py wait-for --type node.added

Usage:
    python scene_event_monitor.py monitor [--filter CATEGORIES] [--quiet]
    python scene_event_monitor.py log --out FILE [--filter CATEGORIES]
    python scene_event_monitor.py wait-for --type EVENT_TYPE [--timeout SECS]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterator

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_HOST  = "127.0.0.1"
DEFAULT_PORT  = 18811
TOKEN_FILE    = Path.home() / ".daz3d" / "dazscriptserver_token.txt"

# SSE event categories accepted by ?filter=
VALID_CATEGORIES = {
    "node", "skeleton", "light", "camera",
    "selection", "scene", "time", "render",
}

# Terminal colours (disabled on Windows without ANSI support)
_USE_COLOUR = sys.stdout.isatty() and sys.platform != "win32"

def _colour(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

TYPE_COLOURS = {
    "node":        "32",   # green
    "skeleton":    "32",
    "light":       "33",   # yellow
    "camera":      "36",   # cyan
    "selection":   "35",   # magenta
    "scene":       "34",   # blue
    "time":        "90",   # dark grey
    "playback":    "90",
    "render":      "31",   # red
}

# ── Token loading ──────────────────────────────────────────────────────────────

def load_token() -> str | None:
    """Return the API token from the default token file, or None if absent."""
    try:
        return TOKEN_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


# ── SSE parser ─────────────────────────────────────────────────────────────────

def _iter_sse_lines(response: requests.Response) -> Iterator[str]:
    """Yield text lines from a streaming SSE response, decoded from UTF-8."""
    buf = b""
    for chunk in response.iter_content(chunk_size=None):
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")


def iter_events(response: requests.Response) -> Generator[dict, None, None]:
    """Parse SSE frames from *response* and yield each event as a dict.

    Comment lines (starting with ':') and keepalive frames are silently
    skipped.  Malformed data lines are also skipped with a warning.
    """
    for line in _iter_sse_lines(response):
        if not line.startswith("data:"):
            continue  # keepalive comment or blank line
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError as exc:
            print(f"[WARN] Could not parse SSE payload: {exc}", file=sys.stderr)


# ── SSE connection ─────────────────────────────────────────────────────────────

def connect(host: str, port: int, token: str | None,
            categories: list[str] | None) -> requests.Response:
    """Open the /scene/events SSE stream and return the streaming Response."""
    url = f"http://{host}:{port}/scene/events"
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["X-API-Token"] = token

    params: dict[str, str] = {}
    if categories:
        params["filter"] = ",".join(categories)

    response = requests.get(url, headers=headers, params=params,
                            stream=True, timeout=None)
    response.raise_for_status()
    return response


# ── Formatting ─────────────────────────────────────────────────────────────────

def _format_event(event: dict) -> str:
    """Return a one-line human-readable representation of an SSE event."""
    event_type: str = event.get("type", "unknown")
    ts_ms: int      = event.get("ts", 0)
    data: dict      = event.get("data", {})

    ts_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%H:%M:%S")

    # Colour the event type by category prefix
    category = event_type.split(".")[0]
    coloured_type = _colour(TYPE_COLOURS.get(category, "0"), event_type)

    # Build a short summary of the payload
    parts: list[str] = []
    if "node_name" in data:
        parts.append(data["node_name"])
    if "node_type" in data:
        parts.append(f"({data['node_type']})")
    if "time_secs" in data:
        parts.append(f"{data['time_secs']:.3f}s")
    if "filename" in data:
        parts.append(Path(data["filename"]).name)

    summary = "  " + "  ".join(parts) if parts else ""
    return f"{ts_str}  {coloured_type}{summary}"


# ── Subcommand: monitor ────────────────────────────────────────────────────────

def cmd_monitor(args: argparse.Namespace) -> None:
    """Print scene events to the terminal as they arrive."""
    categories = args.filter.split(",") if args.filter else None
    token = load_token()

    filter_label = f"filter={args.filter}" if args.filter else "all categories"
    print(f"Connecting to {args.host}:{args.port}/scene/events  [{filter_label}]")
    print("Press Ctrl+C to stop.\n")

    try:
        with connect(args.host, args.port, token, categories) as response:
            for event in iter_events(response):
                if not args.quiet:
                    print(_format_event(event), flush=True)
                else:
                    print(event.get("type", "?"), flush=True)
    except KeyboardInterrupt:
        print("\nStopped.")
    except requests.HTTPError as exc:
        sys.exit(f"HTTP error: {exc.response.status_code} {exc.response.text}")
    except requests.ConnectionError:
        sys.exit(f"Could not connect to {args.host}:{args.port}. "
                 "Is DAZ Studio running with the plugin active?")


# ── Subcommand: log ────────────────────────────────────────────────────────────

def cmd_log(args: argparse.Namespace) -> None:
    """Append events to a JSONL file as they arrive."""
    categories = args.filter.split(",") if args.filter else None
    token = load_token()
    out_path = Path(args.out)

    filter_label = f"filter={args.filter}" if args.filter else "all categories"
    print(f"Logging {args.host}:{args.port}/scene/events [{filter_label}] → {out_path}")
    print("Press Ctrl+C to stop.\n")

    count = 0
    try:
        with (
            connect(args.host, args.port, token, categories) as response,
            out_path.open("a", encoding="utf-8") as fh,
        ):
            for event in iter_events(response):
                fh.write(json.dumps(event) + "\n")
                fh.flush()
                count += 1
                print(f"\r{count} events logged", end="", flush=True)
    except KeyboardInterrupt:
        print(f"\nStopped.  {count} events written to {out_path}.")
    except requests.HTTPError as exc:
        sys.exit(f"HTTP error: {exc.response.status_code} {exc.response.text}")
    except requests.ConnectionError:
        sys.exit(f"Could not connect to {args.host}:{args.port}. "
                 "Is DAZ Studio running with the plugin active?")


# ── Subcommand: wait-for ───────────────────────────────────────────────────────

def cmd_wait_for(args: argparse.Namespace) -> None:
    """Block until a matching event arrives, print its data, then exit.

    Useful in shell scripts that need to wait for a render to finish or a
    scene to finish loading before taking the next action.

    Exit code 0 on match, 1 on timeout.
    """
    token = load_token()
    # Derive the minimum filter category from the requested event type so we
    # don't receive unnecessary noise while waiting.
    category = args.type.split(".")[0]
    categories = [category] if category in VALID_CATEGORIES else None

    print(f"Waiting for '{args.type}' on {args.host}:{args.port} "
          f"(timeout: {args.timeout}s)…")

    deadline = time.monotonic() + args.timeout
    try:
        with connect(args.host, args.port, token, categories) as response:
            for event in iter_events(response):
                if event.get("type") == args.type:
                    print(json.dumps(event, indent=2))
                    sys.exit(0)
                if time.monotonic() > deadline:
                    break
    except KeyboardInterrupt:
        pass
    except requests.HTTPError as exc:
        sys.exit(f"HTTP error: {exc.response.status_code} {exc.response.text}")
    except requests.ConnectionError:
        sys.exit(f"Could not connect to {args.host}:{args.port}. "
                 "Is DAZ Studio running with the plugin active?")

    print(f"Timed out after {args.timeout}s — '{args.type}' never arrived.")
    sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub = parser.add_subparsers(dest="command", required=True)

    # monitor
    p_monitor = sub.add_parser("monitor", help="Print events to the terminal")
    p_monitor.add_argument(
        "--filter", metavar="CATEGORIES",
        help=f"Comma-separated subset to subscribe to: {', '.join(sorted(VALID_CATEGORIES))}",
    )
    p_monitor.add_argument(
        "--quiet", action="store_true",
        help="Print only event types, not full formatted lines",
    )
    p_monitor.set_defaults(func=cmd_monitor)

    # log
    p_log = sub.add_parser("log", help="Append events to a JSONL file")
    p_log.add_argument("--out", required=True, metavar="FILE",
                       help="Output file (appended, not overwritten)")
    p_log.add_argument(
        "--filter", metavar="CATEGORIES",
        help="Comma-separated subset to subscribe to",
    )
    p_log.set_defaults(func=cmd_log)

    # wait-for
    p_wait = sub.add_parser(
        "wait-for",
        help="Block until one matching event arrives, then exit 0 (or 1 on timeout)",
    )
    p_wait.add_argument("--type", required=True, metavar="EVENT_TYPE",
                        help="Exact event type to wait for, e.g. render.finished")
    p_wait.add_argument("--timeout", type=float, default=300.0, metavar="SECS",
                        help="Maximum seconds to wait (default: 300)")
    p_wait.set_defaults(func=cmd_wait_for)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
