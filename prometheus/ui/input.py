"""Shared input handler with full keybinding support.

Replaces the REPL's ``msvcrt``-based ``_read_line()`` and the mission
prompt's ``console.input()`` loop with a single implementation.

Keybindings
-----------
  Enter          Submit the buffer (multiline or not)
  Tab            Trigger autocomplete callback
  Up / Down      Navigate input history
  Ctrl+R         Reverse history search (fuzzy-filter through past commands)
  Ctrl+E         Open external $EDITOR with current buffer
  Ctrl+S         Stash / restore current input buffer
  Ctrl+C         Abort (returns empty string)
  Ctrl+L         Clear screen, keep current buffer
  Ctrl+J         Insert newline (multiline mode only)
  Alt+Enter      Insert newline (multiline mode only)
  Backspace      Erase char before cursor
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from typing import Callable

from rich.console import Console
from rich.text import Text

from prometheus.ui.console import console as _default_console
from prometheus.ui.styles import Token

# Module-level stash: persists across read_input() calls so the user
# can Ctrl+S, run a command, then Ctrl+S to restore.
_stashed_buffer: str = ""


def read_input(
    prompt: str = "\u276f ",
    *,
    history: list[str] | None = None,
    multiline: bool = False,
    completer: Callable[[str], list[str]] | None = None,
    console: Console | None = None,
) -> str:
    """Read a line of input with full keybinding support.

    Parameters
    ----------
    prompt
        Prompt string displayed before the input area.
    history
        Mutable list used as a history ring.  The caller owns the list
        and can persist it between calls.
    multiline
        If True, Ctrl+J and Alt+Enter insert a newline.  Enter always
        submits, regardless of mode.
    completer
        Callable that receives the current line text and returns a list
        of completion candidates.  Pressing Tab with no candidates is a
        no-op; with exactly one candidate it auto-completes; with more
        it cycles.
    console
        Rich Console used for rendering.  Defaults to the shared console.
    """
    # ── Platform-independent input ──────────────────────────────────
    # When not connected to a real TTY (e.g. Click test runner, piped
    # stdin) fall back to the simpler line-oriented reader immediately
    # so we don't block on msvcrt.getwch().
    if not sys.stdin.isatty():
        return _fallback_input(prompt, multiline=multiline, console=console)

    try:
        import msvcrt as _m
    except ImportError:
        return _fallback_input(prompt, multiline=multiline, console=console)

    c = console or _default_console
    hist = history if history is not None else []
    hist_index = len(hist)  # Active index in history ring (len(hist) = fresh buffer)
    buf: list[str] = []
    cursor_pos: int = 0
    last_char: float = 0.0
    paste_window = 0.08
    tab_index: int = -1
    tab_candidates: list[str] = []
    tab_prefix: str = ""

    # Vim mode state
    vim_mode = "insert"  # "insert" | "normal" | "visual"
    undo_stack: list[str] = []
    visual_start = 0
    vim_pending: str = ""  # For multi-char commands (d→d, c→w)
    vim_pending_time = 0.0

    def _save_undo() -> None:
        undo_stack.append("".join(buf))

    def _vim_indicator() -> str:
        if vim_mode == "insert":
            return ""
        m = vim_mode[0].upper()
        return f"  [{Token.info}]\u2502 {m}[/]"

    _render_height = 0

    def _measure_height(text: str) -> int:
        """Count terminal lines a string occupies, handling wrapping."""
        cols = shutil.get_terminal_size().columns
        total = 0
        for line in text.split("\n"):
            visible = len(line)
            total += max(1, -(-visible // cols))
        return total

    def _repaint() -> None:
        nonlocal cursor_pos, _render_height
        old_h = _render_height
        up = max(0, old_h - 1)
        if up:
            sys.stdout.write(f"\x1b[{up}A")
        sys.stdout.write("\r")
        out = prompt + "".join(buf)
        if vim_mode != "insert":
            out += f"  \x1b[1m\u2502 {vim_mode[0].upper()}\x1b[0m"
        sys.stdout.write(out)
        sys.stdout.flush()
        _render_height = _measure_height(out)
        # Clear ghost lines left by the old taller render (text shrank on
        # backspace).  Avoid \x1b[J (clear-to-end-of-display) because it
        # blanks the whole screen below the cursor — visible pulse on
        # Windows Terminal.
        leftover = old_h - _render_height
        if leftover > 0:
            for _ in range(leftover):
                sys.stdout.write("\x1b[1B\r\x1b[K")
            sys.stdout.write(f"\x1b[{leftover}A")
        else:
            sys.stdout.write("\x1b[K")
        sys.stdout.flush()

    def _repaint_fast() -> None:
        """Overwrite from column 0 — no erase cycle, no cursor jumping.

        Forward typing always lengthens the buffer, so the new text
        is strictly longer and overwriting leaves no leftovers.
        A single ``\x1b[<N>A`` jump avoids the visible pulse of
        per-line ``\x1b[1A`` + clear cycles on every keystroke.
        """
        nonlocal _render_height
        up = max(0, _render_height - 1)
        if up:
            sys.stdout.write(f"\x1b[{up}A")
        sys.stdout.write("\r" + prompt + "".join(buf))
        sys.stdout.flush()
        _render_height = _measure_height(prompt + "".join(buf))

    import time as _t

    _repaint()

    while True:
        ch = _m.getwch()
        now = _t.monotonic()

        # ── Extended keys (arrows / function keys / Alt combos) ──
        if ch in ("\x00", "\xe0"):
            ext = _m.getwch()

            # Alt+Enter (detected as \x00 + \x1c on most Windows consoles)
            # In multiline mode, insert a newline.
            if multiline and ch == "\x00" and ext == "\x1c":
                buf.append("\n")
                cursor_pos = len(buf)
                _repaint()
                continue

            # ── Arrow keys (checked BEFORE Alt+letter to avoid scan-code
            #    conflicts — `\x00` + `H`/`P`/`K`/`M` on some Windows
            #    configurations looks like Alt+letter) ────────────────
            if ext == "H":  # Up arrow — history back
                if hist:
                    if hist_index > 0:
                        hist_index -= 1
                        buf = list(hist[hist_index]) if hist_index < len(hist) else []
                        cursor_pos = len(buf)
                        _repaint()
                continue

            if ext == "P":  # Down arrow — history forward
                if hist:
                    if hist_index < len(hist) - 1:
                        hist_index += 1
                        buf = list(hist[hist_index])
                    else:
                        hist_index = len(hist)
                        buf = []
                    cursor_pos = len(buf)
                    _repaint()
                continue

            if ext == "I":  # Page Up
                continue

            if ext == "Q":  # Page Down
                continue

            # Alt+letter command shortcuts (Alt+D → doctor, Alt+L → list, etc.)
            if ch == "\x00" and "A" <= ext <= "Z":
                _handle_command_shortcut(ext, buf, console=console)
                _repaint()
                continue

            # Any other extended key  →  ignore
            continue

        # ── Enter (always submits) ──────────────────────────────────
        if ch == "\r":
            # Paste detection: rapid \r in succession → treat as paste
            rapid = buf and (now - last_char < paste_window)
            if rapid:
                buf.append(" ")
                cursor_pos = len(buf)
                last_char = now
                _repaint()
                continue

            console.print()
            result = "".join(buf)
            if hist and result:
                if not hist or hist[-1] != result:
                    hist.append(result)
            return result

        # ── Shift+Enter detection (Windows Terminal / ConPTY) ──────
        # On modern Windows Terminal, Shift+Enter sends \x1b encoding.
        # We detect this in the `\x00`/`\xe0` branch above for NT
        # consoles.  For ConPTY-based terminals the sequence may not
        # arrive; Alt+Enter is the reliable alternative.

        # ── Backspace ──────────────────────────────────────────────
        if ch in ("\b", "\x7f"):
            if buf:
                buf.pop()
                cursor_pos = len(buf)
                # Fast backspace: write text first, then clear tail.
                # No pre-clearing cycle — avoids the visible pulse of
                # _repaint()'s multi-line leftover loop.
                old_h = _render_height
                display = prompt + "".join(buf)
                up = max(0, old_h - 1)
                if up:
                    sys.stdout.write(f"\x1b[{up}A")
                sys.stdout.write("\r" + display + "\x1b[J")
                sys.stdout.flush()
                _render_height = _measure_height(display)
            continue

        # ── Tab completion ─────────────────────────────────────────
        if ch == "\t" and completer is not None:
            line_text = "".join(buf)
            candidates = completer(line_text)

            if not candidates:
                continue

            if len(candidates) == 1:
                # Auto-complete: replace the last word with the match
                rest = candidates[0]
                buf = list(rest)
                cursor_pos = len(buf)
                _repaint()
                continue

            # Multiple candidates: cycle through them
            if candidates != tab_candidates:
                tab_candidates = candidates
                tab_index = 0
                tab_prefix = line_text
            else:
                tab_index = (tab_index + 1) % len(candidates)

            # Show candidates on a dedicated line below the prompt
            c = console or _default_console
            pick = candidates[tab_index]
            shown = "  ".join(
                f"[reverse]{opt}[/]" if i == tab_index else opt for i, opt in enumerate(candidates)
            )
            c.print(f"\r\x1b[K{shown}")
            # Restore prompt + buffer
            _repaint()
            continue

        # ── Ctrl+C (interrupt / cancel) ────────────────────────────
        if ch == "\x03":
            console.print()
            result = "".join(buf)
            # Don't append to history on interrupt
            return result

        # ── Ctrl+L (clear screen) ──────────────────────────────────
        if ch == "\x0c":
            os.system("cls" if os.name == "nt" else "clear")
            _repaint()
            continue

        # ── Ctrl+R (reverse history search) ───────────────────────
        if ch == "\x12" and hist:
            result = _reverse_search(hist, console=console)
            if result is not None:
                buf = list(result)
                cursor_pos = len(buf)
                hist_index = len(hist)
                _repaint()
            continue

        # ── Ctrl+E / Ctrl+\ (external editor) ────────────────────
        # Ctrl+E (0x05) is the primary binding.  Ctrl+\ (0x1c) is
        # an alternative for terminals that intercept Ctrl+E (e.g.
        # Windows Terminal's "Search" feature).
        if ch in ("\x05", "\x1c"):
            editor_text = _launch_editor("".join(buf), console=console)
            if editor_text is not None:
                buf = list(editor_text)
                cursor_pos = len(buf)
                _repaint()
            continue

        # ── Ctrl+S (stash / restore) ──────────────────────────────
        if ch == "\x13":
            global _stashed_buffer
            current = "".join(buf)
            if _stashed_buffer and not current:
                buf = list(_stashed_buffer)
                _stashed_buffer = ""
                cursor_pos = len(buf)
                sys.stdout.write("\r\x1b[K")
                console.print(f"  [{Token.success}]\u21c4 Restored stashed prompt[/]")
                _repaint()
            elif current:
                _stashed_buffer = current
                buf.clear()
                cursor_pos = 0
                sys.stdout.write("\r\x1b[K")
                console.print(f"  [{Token.info}]\u21c4 Prompt stashed ({len(current)} chars)[/]")
                _repaint()
            continue

        # ── Ctrl+Z (EOF) ──────────────────────────────────────────
        if ch == "\x1a":
            console.print()
            raise EOFError

        # ── Esc / Vim mode handling ───────────────────────────────
        if ch == "\x1b":
            # Reset multi-char pending command
            vim_pending = ""
            if vim_mode == "insert":
                vim_mode = "normal"
                _save_undo()
                _repaint()
            elif vim_mode == "visual":
                vim_mode = "normal"
                _repaint()
            # In normal mode, Esc is a no-op (we're already there)
            continue

        # ── Vim normal mode keys ───────────────────────────────────
        if vim_mode != "insert":
            key = ch.lower()

            # Multi-char command timeouts
            if vim_pending:
                if _t.monotonic() - vim_pending_time > 1.0:
                    vim_pending = ""

            # ── dd: delete line ──
            if vim_pending == "d" and key == "d":
                vim_pending = ""
                _save_undo()
                buf.clear()
                cursor_pos = 0
                _repaint()
                continue

            # ── cw: change word ──
            if vim_pending == "c" and key == "w":
                vim_pending = ""
                _save_undo()
                _vim_delete_word(buf, cursor_pos)
                cursor_pos = min(cursor_pos, len(buf))
                vim_mode = "insert"
                _repaint()
                continue

            # Start multi-char: d (wait for d), c (wait for w)
            if key == "d" and vim_pending != "d":
                vim_pending = "d"
                vim_pending_time = _t.monotonic()
                continue
            if key == "c" and vim_pending != "c":
                vim_pending = "c"
                vim_pending_time = _t.monotonic()
                continue

            # Clear pending on any other key
            vim_pending = ""

            # ── i / a: enter insert mode ──
            if key == "i":
                vim_mode = "insert"
                _repaint()
                continue
            if key == "a":
                if cursor_pos < len(buf):
                    cursor_pos += 1
                vim_mode = "insert"
                _repaint()
                continue

            # ── v: visual mode ──
            if key == "v":
                if vim_mode == "visual":
                    vim_mode = "normal"
                else:
                    vim_mode = "visual"
                    visual_start = cursor_pos
                _repaint()
                continue

            # ── Normal mode navigation ──
            if key == "w":
                _vim_word_forward(buf, cursor_pos)
                cursor_pos = min(cursor_pos, len(buf))
                _repaint()
                continue
            if key == "b":
                _vim_word_backward(buf, cursor_pos)
                cursor_pos = max(cursor_pos, 0)
                _repaint()
                continue
            if key == "0":
                cursor_pos = 0
                _repaint()
                continue
            if key == "$":
                cursor_pos = len(buf)
                _repaint()
                continue

            # ── u: undo ──
            if key == "u" and undo_stack:
                buf = list(undo_stack.pop())
                cursor_pos = min(cursor_pos, len(buf))
                _repaint()
                continue

            # ── Visual mode: yank (copy selection) ──
            if vim_mode == "visual" and key == "y":
                sel_start = min(visual_start, cursor_pos)
                sel_end = max(visual_start, cursor_pos)
                selected = "".join(buf[sel_start:sel_end])
                if selected:
                    _copy_to_clipboard_impl(selected, console=console)
                vim_mode = "normal"
                _repaint()
                continue

            # In visual mode, movement keys keep us in visual mode
            if vim_mode == "visual" and key in ("h", "l"):
                if key == "h":
                    cursor_pos = max(cursor_pos - 1, 0)
                else:
                    cursor_pos = min(cursor_pos + 1, len(buf))
                _repaint()
                continue

            # Unknown normal mode key — ignore (don't insert)
            continue

        # ── Ctrl+J (\x0a) — insert newline in multiline mode ──────
        if ch == "\n":
            if multiline:
                buf.append("\n")
                cursor_pos = len(buf)
                last_char = now
                _repaint()
                continue
            # Normalise lone \n to space (pasted content)
            ch = " "

        buf.append(ch)
        cursor_pos = len(buf)
        last_char = now
        # Fast path: overwrite from column 0 without erase cycle.
        # Forward typing always lengthens the buffer, so overwriting
        # leaves no leftover characters and no visible flash.
        if not _vim_indicator():
            _repaint_fast()
        else:
            _repaint()


# ── Reverse history search ────────────────────────────────────────────


def _reverse_search(
    hist: list[str],
    *,
    console: Console,
) -> str | None:
    """Interactive ``(reverse-i-search)`` prompt.

    Pressing Ctrl+R cycles through history entries that match the typed
    query.  Enter accepts the match; Esc / Ctrl+C cancels.
    """
    import time as _t

    try:
        import msvcrt as _m
    except ImportError:
        return None

    query: list[str] = []
    match_index = 0
    matches: list[str] = []
    last_char_time = 0.0

    def _render() -> None:
        nonlocal matches, match_index
        q = "".join(query)
        matches = (
            [h for h in reversed(hist) if q.lower() in h.lower()] if q else list(reversed(hist))
        )
        if not matches:
            match_index = -1
            sys.stdout.write(
                f"\r\x1b[K  ({Token.info})(reverse-i-search)[/]{q}[{Token.error}] \u2718[/]"
            )
        else:
            match_index = max(0, min(match_index, len(matches) - 1))
            pick = matches[match_index]
            sys.stdout.write(
                f"\r\x1b[K  ({Token.info})(reverse-i-search)[/]{q}[{Token.muted}]: {pick}[/]"
            )
        console.file.flush()

    _render()

    while True:
        ch = _m.getwch()
        now = _t.monotonic()

        if ch in ("\x00", "\xe0"):
            _m.getwch()
            continue

        # Accept
        if ch == "\r":
            sys.stdout.write("\r\x1b[K")
            console.print()
            if matches and match_index >= 0:
                return matches[match_index]
            return None

        # Cancel
        if ch in ("\x1b", "\x03"):
            sys.stdout.write("\r\x1b[K")
            console.print()
            return None

        # Navigate matches
        if ch == "\x12":  # Ctrl+R again → next match
            if matches:
                match_index = (match_index + 1) % len(matches)
            _render()
            continue

        # Backspace
        if ch in ("\b", "\x7f"):
            if query:
                query.pop()
            match_index = 0
            _render()
            continue

        # Printable
        if ch.isprintable():
            query.append(ch)
            match_index = 0
            _render()

        last_char_time = now


# ── External editor launcher ──────────────────────────────────────────


def _launch_editor(
    initial: str,
    *,
    console: Console,
) -> str | None:
    """Open the user's ``$EDITOR`` with *initial* content.

    Returns the edited text, or ``None`` if the editor was cancelled /
    returned empty / the file was unchanged.
    """
    import subprocess

    editor = (
        os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or ("notepad" if os.name == "nt" else "nano")
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(initial)
        tmp.close()

        sys.stdout.write(f"\r\x1b[K  [{Token.info}]Opened {editor} \u2026[/]\n")
        console.file.flush()

        proc = subprocess.run(
            [editor, tmp.name],
            shell=True if os.name == "nt" else False,
        )

        if proc.returncode != 0:
            console.print(f"  [{Token.error}]Editor exited with code {proc.returncode}[/]")
            return None

        with open(tmp.name, "r", encoding="utf-8") as f:
            result = f.read()

        if result == initial:
            console.print(f"  [{Token.muted}]No changes[/]")
            return None

        console.print(f"  [{Token.success}]\u2714 Loaded {len(result)} chars from editor[/]")
        return result
    except FileNotFoundError:
        console.print(f"  [{Token.error}]Editor not found: {editor}[/]")
        console.print(f"  [{Token.muted}]Set $EDITOR or $VISUAL environment variable[/]")
        return None
    except Exception as exc:
        console.print(f"  [{Token.error}]Editor error: {exc}[/]")
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ── Vim word navigation helpers ────────────────────────────────────────


def _vim_word_forward(buf: list[str], pos: int) -> int:
    """Move *pos* to the start of the next word."""
    n = len(buf)
    i = pos
    # Skip current word
    while i < n and buf[i].isalnum():
        i += 1
    # Skip whitespace
    while i < n and buf[i] in (" ", "\t"):
        i += 1
    return i


def _vim_word_backward(buf: list[str], pos: int) -> int:
    """Move *pos* to the start of the current or previous word."""
    i = max(pos - 1, 0)
    # Skip whitespace
    while i > 0 and buf[i] in (" ", "\t"):
        i -= 1
    # Skip to start of word
    while i > 0 and buf[i - 1].isalnum():
        i -= 1
    return i


def _vim_delete_word(buf: list[str], pos: int) -> None:
    """Delete from *pos* to the end of the current word."""
    n = len(buf)
    i = pos
    while i < n and buf[i].isalnum():
        i += 1
    while i < n and buf[i] in (" ", "\t"):
        i += 1
    del buf[pos:i]


# ── Clipboard helper (lightweight, no pyperclip dep needed) ────────────


def _copy_to_clipboard_impl(text: str, *, console: Console) -> None:
    """Copy *text* to clipboard with feedback."""
    import subprocess

    try:
        import pyperclip

        pyperclip.copy(text)
        console.print(f"  [{Token.success}]\u2714 Copied {len(text)} chars to clipboard[/]")
        return
    except ImportError:
        pass
    try:
        if os.name == "nt":
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            proc.communicate(text.encode("utf-8"))
        else:
            for cmd in (
                ["pbcopy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    proc.communicate(text.encode("utf-8"))
                    break
                except FileNotFoundError:
                    continue
    except Exception:
        console.print(f"  [{Token.info}]Clipboard not available ({len(text)} chars)[/]")


# ── Command shortcut handler (Alt+D, Alt+L, etc.) ──────────────────────


_COMMAND_SHORTCUTS: dict[str, str] = {
    "D": "doctor",
    "L": "mission list",
    "R": "mission report",
    "S": "solve",
    "E": "explain",
    "M": "memory stats",
    "B": "benchmark summary",
    "W": "workspace status",
}


def _handle_command_shortcut(
    key: str,
    buf: list[str],
    *,
    console: Console,
) -> None:
    """Execute a command shortcut.

    Called when Alt+<key> is pressed during input.  The current buffer
    is stashed (like Ctrl+S), the command is printed to the console,
    and executed immediately via the CLI.
    """
    global _stashed_buffer
    cmd = _COMMAND_SHORTCUTS.get(key)
    if not cmd:
        return

    # Stash current text
    current = "".join(buf)
    if current:
        _stashed_buffer = current
    buf.clear()

    # Print the command
    sys.stdout.write("\r\x1b[K")
    console.print(f"  [{Token.info}]\u21b7 {cmd}[/]")
    console.file.flush()

    # Execute the CLI command directly
    try:
        from prometheus.main import cli

        cli(cmd.split(), standalone_mode=False)
    except SystemExit:
        pass
    except Exception as exc:
        console.print(f"  [{Token.error}]{exc}[/]")


def _fallback_input(
    prompt: str,
    *,
    multiline: bool = False,
    console: Console | None = None,
) -> str:
    """Fallback for non-TTY stdin or platforms without msvcrt."""
    c = console or _default_console

    # Non-TTY path: read from piped stdin directly.
    if not sys.stdin.isatty():
        if multiline:
            lines: list[str] = []
            for raw in sys.stdin:
                stripped = raw.rstrip("\r\n")
                if not stripped and lines:
                    break
                lines.append(stripped)
            return "\n".join(lines)
        line = sys.stdin.readline().rstrip("\r\n")
        return line

    try:
        import tty
        import termios
        import select

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            buf: list[str] = []
            while True:
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    ch = sys.stdin.read(1)
                    if ch == "\r":
                        c.print()
                        return "".join(buf)
                    if ch == "\x7f":
                        if buf:
                            buf.pop()
                    elif ch == "\t":
                        pass  # Tab — no completer in fallback mode
                    elif ch == "\x03":
                        c.print()
                        return "".join(buf)
                    elif ch == "\x0c":
                        os.system("clear")
                    elif ch == "\x1b":
                        nxt = ""
                        r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if r2:
                            nxt = sys.stdin.read(1)
                        if nxt == "[":
                            nxt2 = ""
                            r3, _, _ = select.select([sys.stdin], [], [], 0.05)
                            if r3:
                                nxt2 = sys.stdin.read(1)
                            _ = nxt2  # consume but ignore arrow keys
                        elif multiline and nxt == "\r":
                            buf.append("\n")
                    elif ch == "\n":
                        ch = " "
                        buf.append(ch)
                    else:
                        buf.append(ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, OSError, AttributeError):
        line = c.input(prompt)
        return line
    return ""
