"""Real pseudo-terminal check: Esc goes back ONE step; only Esc on the main menu leaves. Exit code 0 = pass."""
import fcntl, os, pty, re, select, struct, sys, tempfile, termios, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from mrh.infrastructure import settings_v2 as v2  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")
ESC = b"\x1b"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp).resolve() / "owned" / "settings.json"
        v2.init(settings)
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.update({"TERM": "xterm-256color", "PYTHONPATH": str(ROOT / "src")})
            os.execvp(sys.executable, [sys.executable, "-m", "mrh", "ctrl", "--settings", str(settings), "--width", "100"])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 110, 0, 0))
        seen = []

        def read(wait=1.0):
            end, chunk = time.time() + wait, ""
            while time.time() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        break
                    chunk += data.decode("utf-8", "replace")
            seen.append(ANSI.sub("", chunk))
            return seen[-1]

        read(1.5)
        steps = [("3\r", "要設定哪個難度"), ("\r", "主模型是在哪個工具"), (ESC, "要設定哪個難度"),   # platform -> back to tier
                 ("\r", "主模型是在哪個工具"), ("\r", "編輯候選清單"), (ESC, "主模型是在哪個工具"),    # list editor -> back to platform
                 (ESC, "要設定哪個難度"), (ESC, "要調整什麼？")]                                   # tier -> back to main menu
        ok = True
        for keys, expect in steps:
            os.write(fd, keys if isinstance(keys, bytes) else keys.encode())
            out = read(1.0)
            hit = expect in out
            ok &= hit
            print(("PASS " if hit else "FAIL ") + f"after {keys!r:8} expecting '{expect}'")
        os.write(fd, ESC)                      # Esc on the main menu leaves
        read(1.0)
        time.sleep(0.5)
        done, _ = os.waitpid(pid, os.WNOHANG)
        print(("PASS " if done else "FAIL ") + "Esc on the main menu exits")
        return 0 if ok and done else 1


if __name__ == "__main__":
    sys.exit(main())
