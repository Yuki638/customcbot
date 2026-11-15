"""Command line entry point: start the server and open the browser."""

from __future__ import annotations

import argparse
import os
import socket
import threading
import webbrowser

from . import __version__, config


def _free_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name != "nt":
                # As the server itself does: a port the app used a moment ago counts as free.
                # (On Windows this option would also allow a port another program is using.)
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue
    return preferred


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="customcbot", description="Chat with your own PDFs, videos and notes, locally."
    )
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--reset-password", action="store_true", help="remove the password set in Settings, then start"
    )
    args = parser.parse_args()

    import uvicorn

    from .api.main import create_app

    app = create_app()
    if args.reset_password:
        # For a forgotten password. Whoever can start the app on this computer owns the data anyway.
        config.set_many({"password_hash": None})
        print("\n  The password has been removed.")
    port = _free_port(args.host, args.port)
    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    url = f"http://{shown_host}:{port}"
    print(f"\n  customcbot {__version__} is running at {url}")
    print(f"  Your data is stored in {config.data_dir()}")
    print("  Press Ctrl+C to stop.\n")
    if args.host not in ("127.0.0.1", "localhost"):
        from .api import auth

        if not auth.required():
            print("  Warning: no password is set. Anyone who can reach this address can use the app.")
            print("  Set one in Settings, or start with CUSTOMCBOT_PASSWORD=...\n")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
