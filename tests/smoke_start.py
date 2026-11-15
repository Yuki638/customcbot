"""Starts the app the way a new user does, then uses it.

Run with the system Python (it needs nothing installed):

    python tests/smoke_start.py

What it does:

1. Unpacks the repository into a fresh folder, as the ZIP download from GitHub
   would, in a folder whose name has a space and brackets.
2. Runs the start file there (start.bat on Windows, start.sh elsewhere) and
   waits until the app answers.
3. Connects the app to the stand-in online service, adds a PDF and a text
   file, asks a question and makes a quiz and flashcards. The search model is
   the real one, so this also checks that it downloads and runs.
4. Stops the app, starts it again and checks that the data is still there.

Options: --port N, --data-dir PATH (default: the app's normal data folder),
--like-new-pc (take uv off PATH so the start file has to install it, and make
uv download its own Python instead of using one that is already installed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
FIRST_START_LIMIT = 25 * 60  # the first start downloads about 1 GB
TEXT = (
    "The Roman Republic was founded in 509 BC after the last king, Tarquin the Proud, was expelled. "
    "Two consuls were elected each year and shared power. "
    "Notes in other scripts must survive too: café, naïve, Ελληνικά, 日本語."
)


def say(message: str) -> None:
    print(message, flush=True)


# -- starting and stopping ---------------------------------------------------


def unpack() -> Path:
    """The repository as GitHub's ZIP download delivers it: no .git, no checkout settings."""
    folder = Path(tempfile.mkdtemp(prefix="customcbot-smoke-")) / "customcbot-main (1)"
    folder.mkdir()
    archive = folder.parent / "repo.tar"
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=REPO,
        check=True,
    )
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(folder, filter="data")
        except TypeError:  # Python older than 3.12
            tar.extractall(folder)
    return folder


def uv_command() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / ("uv.exe" if WINDOWS else "uv")
    return str(local) if local.exists() else None


def path_without_uv() -> str:
    names = ("uv.exe", "uv") if WINDOWS else ("uv",)
    keep = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and not any((Path(entry) / name).exists() for name in names)
    ]
    return os.pathsep.join(keep)


def spawn(command: list[str], folder: Path, env: dict, log: Path | None = None) -> subprocess.Popen:
    """Start a program in its own process group, so that stop() also ends what it starts."""
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    output = open(log, "ab") if log else None
    return subprocess.Popen(
        command, cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, **options
    )


def start(folder: Path, port: int, env: dict, log: Path) -> subprocess.Popen:
    arguments = ["--no-browser", "--port", str(port)]
    command = ["cmd", "/c", "start.bat", *arguments] if WINDOWS else ["./start.sh", *arguments]
    return spawn(command, folder, env, log)


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()


def wait_until_up(base: str, process: subprocess.Popen, limit: float) -> float:
    began = time.time()
    while time.time() - began < limit:
        if process.poll() is not None:
            raise SystemExit(f"The start file ended early with code {process.returncode}.")
        try:
            with urllib.request.urlopen(base + "/api/setup", timeout=5) as response:
                if response.status == 200:
                    return time.time() - began
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    raise SystemExit(f"The app did not answer within {int(limit)} s.")


def wait_for_standin(address: str, process: subprocess.Popen) -> None:
    for _ in range(90):
        if process.poll() is not None:
            raise SystemExit(f"The stand-in service ended early with code {process.returncode}.")
        try:
            urllib.request.urlopen(address, timeout=5).close()
            return
        except urllib.error.HTTPError:
            return  # it answered, if only to refuse a request without a key
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise SystemExit("The stand-in service did not start.")


def show(log: Path) -> None:
    say(f"--- output of the start file ({log}) ---")
    say(log.read_text(encoding="utf-8", errors="replace")[-6000:])
    say("--- end ---")


def launch(args: argparse.Namespace) -> None:
    folder = unpack()
    endings = "CRLF" if b"\r\n" in (folder / "start.bat").read_bytes() else "LF"
    say(f"Unpacked into: {folder}")
    say(f"start.bat line endings: {endings}")

    env = dict(os.environ)
    if args.data_dir:
        env["CUSTOMCBOT_DATA_DIR"] = args.data_dir
    if args.like_new_pc:
        env["PATH"] = path_without_uv()
        env["UV_PYTHON_PREFERENCE"] = "only-managed"
    hidden = " (hidden from the start file)" if args.like_new_pc else ""
    say(f"uv before the first start: {uv_command() or 'not installed'}{hidden}")

    base = f"http://127.0.0.1:{args.port}"
    log = folder.parent / "start.log"
    helper_port = args.port + 1
    app = standin = None
    try:
        app = start(folder, args.port, env, log)
        say(f"First start: the app answered after {wait_until_up(base, app, FIRST_START_LIMIT):.0f} s")
        show(log)

        uv = uv_command()
        if uv is None:
            raise SystemExit("The app is running but uv cannot be found afterwards.")
        standin = spawn([uv, "run", "--no-dev", "python", "-m", "tests.standin", str(helper_port)], folder, env)
        wait_for_standin(f"http://127.0.0.1:{helper_port}/v1/models", standin)
        subprocess.run(
            [uv, "run", "--no-dev", "python", "-m", "tests.smoke_start", "--use", base,
             "--service", f"http://127.0.0.1:{helper_port}/v1"],
            cwd=folder, env=env, check=True,
        )

        stop(app)
        log.write_bytes(b"")
        app = start(folder, args.port, env, log)
        say(f"Second start: the app answered after {wait_until_up(base, app, 180):.0f} s")
        with urllib.request.urlopen(base + "/api/collections", timeout=10) as response:
            kept = json.load(response)
        if not any(c["name"] == COLLECTION for c in kept):
            raise SystemExit(f"The collection was not kept across a restart: {kept}")
        say("Data was kept across the restart.")
        say("\nAll checks passed.")
    except BaseException:
        if log.exists():
            show(log)
        raise
    finally:
        for process in (app, standin):
            if process is not None:
                stop(process)


# -- using the app (runs inside the project's own Python) --------------------

COLLECTION = "Smoke test"


def use(base: str, service: str) -> None:
    import httpx

    from tests.helpers import text_pdf

    client = httpx.Client(base_url=base, timeout=600)

    def check(response: httpx.Response) -> dict | list:
        if response.status_code != 200:
            raise SystemExit(f"{response.request.method} {response.request.url} gave {response.status_code}: {response.text}")
        return response.json()

    status = check(client.get("/api/setup"))
    say(f"Computer as the app sees it: {status['hardware']}")
    say(f"Recommended: {status['recommended_mode']} mode, local size {status['recommended']}")

    # Connect the stand-in service through the same route the setup page uses.
    online = {"service": "custom", "base_url": service, "api_key": "test-key"}
    models = check(client.post("/api/setup/online/models", json=online))
    check(client.post("/api/setup/online", json={**online, "model": models["suggested"]}))
    began = time.time()
    while True:
        status = check(client.get("/api/setup"))
        if not status["pull"].get("active"):
            break
        time.sleep(2)
    if status["pull"].get("error"):
        raise SystemExit(f"Setup failed: {status['pull']['error']}")
    check(client.post("/api/setup/finish"))
    if not status["ready"] or status["mode"] != "online":
        raise SystemExit(f"Setup did not finish: ready={status['ready']} mode={status['mode']}")
    if "test-key" in json.dumps(status):
        raise SystemExit("The key was sent back to the browser.")
    say(f"Online setup done with model {models['suggested']}; search model ready after {time.time() - began:.0f} s")

    collection = check(client.post("/api/collections", json={"name": COLLECTION}))["id"]
    pdf = text_pdf([
        "Cellular respiration has three stages: glycolysis, the Krebs cycle and the electron transport chain.",
        "Glycolysis happens in the cytoplasm and makes two ATP. The Krebs cycle happens in the mitochondria.",
    ])
    files = [
        ("files", ("Lecture 4 - Cellular Respiration.pdf", pdf, "application/pdf")),
        ("files", ("Roman Republic notes.txt", TEXT.encode("utf-8"), "text/plain")),
    ]
    added = check(client.post(f"/api/collections/{collection}/sources/files", files=files))
    if added["rejected"]:
        raise SystemExit(f"Files were rejected: {added['rejected']}")
    began = time.time()
    while True:
        sources = check(client.get(f"/api/collections/{collection}/sources"))
        if all(s["status"] in ("ready", "error") for s in sources):
            break
        if time.time() - began > 600:
            raise SystemExit(f"Reading the files took too long: {sources}")
        time.sleep(1)
    problems = [(s["title"], s["error"]) for s in sources if s["status"] != "ready"]
    if problems:
        raise SystemExit(f"Files could not be read: {problems}")
    say(f"Read {len(sources)} files in {time.time() - began:.0f} s")

    notes = next(s for s in sources if s["kind"] != "pdf")
    stored = json.dumps(check(client.get(f"/api/sources/{notes['id']}/units")), ensure_ascii=False)
    for word in ("café", "Ελληνικά", "日本語"):
        if word not in stored:
            raise SystemExit(f"Text was damaged on the way in: {word!r} is missing from the stored notes.")
    say("Accented and non-Latin text was stored intact.")

    chat = check(client.post(f"/api/collections/{collection}/chats"))["id"]
    events = []
    with client.stream("POST", f"/api/chats/{chat}/messages", json={"content": "What are the stages of cellular respiration?"}) as reply:
        name = None
        for line in reply.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    errors = [data for name, data in events if name == "error"]
    answer = "".join(data["text"] for name, data in events if name == "token")
    cited = next((data["citations"] for name, data in events if name == "sources"), [])
    if errors or not answer.strip() or not cited:
        raise SystemExit(f"Chat failed: errors={errors} answer={answer!r} passages={len(cited)}")
    say(f"Chat answered (passages found: {len(cited)}): {answer.strip()[:120]!r}")

    def finish(job: dict, what: str) -> None:
        began = time.time()
        while job["status"] in ("queued", "running"):
            if time.time() - began > 600:
                raise SystemExit(f"{what} took too long: {job}")
            time.sleep(1)
            job = check(client.get(f"/api/jobs/{job['id']}"))
        if job["status"] != "done":
            raise SystemExit(f"{what} failed: {job}")

    finish(check(client.post(f"/api/collections/{collection}/quizzes", json={"count": 3})), "The quiz")
    quizzes = check(client.get(f"/api/collections/{collection}/quizzes"))
    if not quizzes or not quizzes[0]["question_count"]:
        raise SystemExit(f"No quiz questions were written: {quizzes}")
    say(f"Quiz made with {quizzes[0]['question_count']} questions")

    finish(check(client.post(f"/api/collections/{collection}/flashcards", json={"count": 4})), "The flashcards")
    cards = check(client.get(f"/api/collections/{collection}/flashcards"))
    if not cards:
        raise SystemExit("No flashcards were written.")
    say(f"Flashcards made: {len(cards)}")

    finish(check(client.post(f"/api/collections/{collection}/summary", json={})), "The summary")
    summary = check(client.get(f"/api/collections/{collection}/summary"))
    if not (summary.get("summary") or "").strip():
        raise SystemExit("No summary was written.")
    say("Summary written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--data-dir")
    parser.add_argument("--like-new-pc", action="store_true")
    parser.add_argument("--use", metavar="ADDRESS", help=argparse.SUPPRESS)
    parser.add_argument("--service", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.use:
        use(args.use, args.service)
    else:
        launch(args)


if __name__ == "__main__":
    main()
