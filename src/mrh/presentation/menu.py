"""Arrow-key menu with a plain numbered fallback for pipes and tests."""
from __future__ import annotations

import os
import select as io_select
import textwrap

from mrh.presentation.terminal import render_choices, sanitize_text


class Cancelled(Exception):
    pass


class Back(Exception):
    pass


def initial_focus(items, current):
    """Start on the current value; with none, on the first item (never on a `None`-valued Quit)."""
    return next((i for i, (_, v) in enumerate(items) if current is not None and v == current), 0)


class Menu:
    def __init__(self, stdin, stdout, width, color):
        self.stdin, self.stdout, self.width, self.color = stdin, stdout, max(24, min(140, width)), color

    def note(self, text):
        self.stdout.write(textwrap.fill(sanitize_text(text), width=self.width - 4,
                                        initial_indent="  ", subsequent_indent="  ") + "\n")

    def text(self, prompt):
        """One line of free text. `back` / `cancel` navigate."""
        self.note(prompt + "（輸入 back 返回、cancel 取消）")
        self.stdout.write("  > "); self.stdout.flush()
        raw = self.stdin.readline(1026)
        self.stdout.write("\n")
        if not raw or raw.strip().lower() in ("cancel", "取消"):
            raise Cancelled()
        if raw.strip().lower() in ("back", "返回"):
            raise Back()
        return raw.strip()

    def _tty_fd(self):
        try:
            fd = self.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return None
        return fd if os.isatty(fd) else None

    def pick(self, title, items, current=None):
        """Return the value of the chosen (label, value) pair."""
        items = list(items)
        fd = self._tty_fd()
        if fd is None:
            self.stdout.write(render_choices(title, [f"{i + 1}. {label}" + (" [目前]" if current is not None and value == current else "")
                                                     for i, (label, value) in enumerate(items)], width=self.width, color=self.color, heading="控制中心"))
            while True:
                answer = self.text("請輸入編號")
                if answer.isdigit() and 1 <= int(answer) <= len(items):
                    return items[int(answer) - 1][1]
                self.note("請輸入列表中的編號。")
        import termios
        import tty
        focus = initial_focus(items, current)
        before = termios.tcgetattr(fd)

        def draw(replace=False):
            rows = [("> " if i == focus else "  ") + f"{i + 1}. {label}" + (" [目前]" if current is not None and value == current else "")
                    for i, (label, value) in enumerate(items)]
            frame = render_choices(title, rows, width=self.width, color=self.color, heading="控制中心")
            if replace:
                self.stdout.write("\r\x1b[" + str(frame.count("\n")) + "A")
            self.stdout.write(frame); self.stdout.write("  > "); self.stdout.flush()

        self.note("↑↓ 選擇　Enter 確認　← 返回　Esc 取消　也可直接按數字")
        try:
            tty.setcbreak(fd); draw(); digits = ""
            while True:
                key = os.read(fd, 1)
                if not key or key == b"\x03":
                    raise Cancelled()
                if key in (b"\r", b"\n"):
                    if digits:
                        number = int(digits)
                        if not 1 <= number <= len(items):
                            digits = ""; continue
                        focus = number - 1
                    return items[focus][1]
                if key.isdigit():
                    digits = (digits + key.decode())[-3:]; continue
                digits = ""
                if key != b"\x1b":
                    continue
                if not io_select.select([fd], [], [], .15)[0]:
                    raise Cancelled()
                if os.read(fd, 1) not in (b"[", b"O") or not io_select.select([fd], [], [], .15)[0]:
                    raise Cancelled()
                code = os.read(fd, 1)
                if code == b"D":
                    raise Back()
                if code in (b"A", b"B"):
                    focus = (focus + (-1 if code == b"A" else 1)) % len(items); draw(True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, before)
            self.stdout.write("\n")
