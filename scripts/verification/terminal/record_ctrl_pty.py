"""Drive `mrh ctrl` through a real pseudo-terminal with arrow keys and Enter; write a transcript.

Usage: python3 record_ctrl_pty.py OUT.txt   (uses a throw-away settings file; touches nothing else)
"""
import fcntl, os, pty, re, select, struct, sys, tempfile, termios, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from mrh.infrastructure import settings_v2 as v2  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")
KEYS = [("Routing screen", "\r"), ("Move to ON", "\x1b[A"), ("Choose ON", "\r"), ("Save", "\r"),
        ("Tier models", "3\r"), ("Light", "\r"), ("codex", "\r"), ("Type a model", "2\r")]


def main(out_path):
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp).resolve() / "owned" / "settings.json"
        v2.init(settings)
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.update({"TERM": "xterm-256color", "PYTHONPATH": str(ROOT / "src")})
            os.execvp(sys.executable, [sys.executable, "-B", "-m", "mrh", "ctrl", "--settings", str(settings), "--width", "100"])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 110, 0, 0))
        log = []

        def drain(wait):
            end = time.time() + wait
            while time.time() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        return
                    log.append(data.decode("utf-8", "replace"))

        drain(1.5)
        for label, keys in KEYS[:4]:
            log.append(f"\n<<< key: {label} >>>\n"); os.write(fd, keys.encode()); drain(1.0)
        log.append("\n<<< key: Quit (9) >>>\n"); os.write(fd, b"9\r"); drain(1.0)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        saved = v2.read(settings)
        log.append(f"\n<<< settings after: enabled={saved['enabled']} task_export={saved['task_export_permitted']} revision={saved['revision']} >>>\n")
        Path(out_path).write_text(ANSI.sub("", "".join(log)))
        return 0 if saved["enabled"] and saved["revision"] >= 1 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
