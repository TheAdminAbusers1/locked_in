#!/usr/bin/env python3
"""
Ugly-on-purpose lock screen for Fedora/GNOME.

- Dark blue handle + bright yellow square lock icon (intentionally clashing).
- No fixed-length ring anymore. Instead, every keystroke triggers a random
  green/red flash somewhere on screen (green = correct char, red = wrong),
  which works for passphrases of any length.
- Pixelates the screen behind the lock.
- Passphrase is never stored or displayed in plaintext. Each character
  position is hashed separately (salted SHA-256) so per-character feedback
  is possible without keeping the real passphrase anywhere on disk.
- Passphrase can be any length and mix letters, numbers, and symbols.
- After typing the passphrase, you must press Enter 3 times quickly
  (within 219.5491ms) to actually submit it — a single Enter does nothing.

First run: prompts you to set a passphrase.
Every run after that: shows the lock.

Usage:
    python3 lock.py            # show the lock screen
    python3 lock.py --setup    # (re)set your passphrase
"""

import os
import sys
import json
import math
import hashlib
import secrets
import random
import tkinter as tk
from tkinter import font as tkfont



CONFIG_DIR = os.path.expanduser("~/.config/locker")
PIN_FILE = os.path.join(CONFIG_DIR, "pin.json")

UGLY_YELLOW = "#fbff00"
UGLY_BLUE = "#0a1a4f"
UGLY_PINK = "#ff2fb0"
UGLY_GREEN = "#00ff5e"
UGLY_LIGHT_GREEN = "#008000"
UGLY_DARK_GREEN = "#006400"
UGLY_RED = "#ff2200"
BG_FALLBACK = "#3a3a3a"
RING_UNLIT = "#888888"

# Ring is split into this many segments; segments light up on keystrokes
RING_SEGMENTS = 8

# Enter must be pressed this many times within this window (ms) to submit
TRIPLE_TAP_WINDOW_MS = 219.5491

# How long to lock out input after an incorrect attempt (wrong character,
# or wrong full passphrase on submit), before progress is wiped (ms)
WRONG_CHAR_LOCKOUT_MS = 3500


# ---------------------------------------------------------------------------
# Passphrase storage (hashed per-character, never plaintext)
# ---------------------------------------------------------------------------

def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)


def hash_char(salt: str, position: int, ch: str) -> str:
    payload = f"{salt}:{position}:{ch}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def save_pin(passphrase: str):
    ensure_config_dir()
    salt = secrets.token_hex(16)
    hashes = [hash_char(salt, i, c) for i, c in enumerate(passphrase)]
    data = {"salt": salt, "length": len(passphrase), "hashes": hashes}
    with open(PIN_FILE, "w") as f:
        json.dump(data, f)
    os.chmod(PIN_FILE, 0o600)


def load_pin_data():
    if not os.path.exists(PIN_FILE):
        return None
    with open(PIN_FILE) as f:
        return json.load(f)



# ---------------------------------------------------------------------------
# Setup UI (first run / --setup)
# ---------------------------------------------------------------------------

def run_setup():
    root = tk.Tk()
    root.title("Set your lock passphrase")
    root.geometry("460x240")
    root.configure(bg=UGLY_BLUE)

    ugly_font = tkfont.Font(family="Sans", size=14, weight="bold")

    tk.Label(root, text="Choose a passphrase (letters, numbers, symbols, any length \u2265 4)",
              bg=UGLY_BLUE, fg=UGLY_YELLOW, font=ugly_font, wraplength=420,
              justify="center").pack(pady=(20, 5))

    entry1 = tk.Entry(root, show="*", font=ugly_font, justify="center",
                       bg=UGLY_YELLOW, fg=UGLY_BLUE, insertbackground=UGLY_BLUE)
    entry1.pack(pady=5)

    tk.Label(root, text="Confirm passphrase", bg=UGLY_BLUE, fg=UGLY_YELLOW,
              font=ugly_font).pack(pady=(15, 5))
    entry2 = tk.Entry(root, show="*", font=ugly_font, justify="center",
                       bg=UGLY_YELLOW, fg=UGLY_BLUE, insertbackground=UGLY_BLUE)
    entry2.pack(pady=5)

    status = tk.Label(root, text="", bg=UGLY_BLUE, fg=UGLY_PINK, font=ugly_font)
    status.pack(pady=10)

    def submit():
        p1, p2 = entry1.get(), entry2.get()
        if len(p1) < 4:
            status.config(text="Passphrase must be at least 4 characters.")
            return
        if p1 != p2:
            status.config(text="Passphrases don't match.")
            entry1.delete(0, tk.END)
            entry2.delete(0, tk.END)
            return
        save_pin(p1)
        status.config(text="Saved. Closing...", fg=UGLY_GREEN)
        root.after(600, root.destroy)

    tk.Button(root, text="Save passphrase", command=submit, bg=UGLY_PINK,
              fg="white", font=ugly_font, relief="raised", bd=5).pack(pady=10)

    root.bind("<Return>", lambda e: submit())
    root.bind("<Escape>", lambda e: root.destroy())

    entry1.focus_set()
    root.mainloop()


# ---------------------------------------------------------------------------
# Lock screen UI
# ---------------------------------------------------------------------------

class LockScreen:
    def __init__(self, pin_data):
        self.pin_data = pin_data
        self.length = pin_data["length"]
        self.salt = pin_data["salt"]
        self.hashes = pin_data["hashes"]
        self.typed = []       # list of chars entered so far
        self.correctness = [] # list of bool, parallel to typed
        self.enter_times = [] # timestamps (ms) of recent Enter presses
        self.locked_until = 0 # time (ms) when next keystroke is allowed

        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG_FALLBACK)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.bind("<Alt-F4>", lambda e: "break")

        self.width = self.root.winfo_screenwidth()
        self.height = self.root.winfo_screenheight()

        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height,
                                 highlightthickness=0, bg=BG_FALLBACK)
        self.canvas.pack(fill="both", expand=True)

        self._draw_lock()

        self.root.grab_set()
        self.root.focus_force()
        self.root.bind("<Key>", self.on_key)

        self.root.mainloop()

    # -- lock icon --------------------------------------------------------
    def _draw_lock(self):
        cx, cy = self.width // 2, self.height // 2
        self.cx, self.cy = cx, cy

        # Deliberately garish ring, now split into lightable segments
        ring_radius = 180
        self.ring_radius = ring_radius
        self.canvas.create_oval(cx - ring_radius - 10, cy - ring_radius - 10,
                                 cx + ring_radius + 10, cy + ring_radius + 10,
                                 outline=UGLY_PINK, width=6)

        # Build the ring out of RING_SEGMENTS arc pieces (with small gaps)
        # so individual sections can be lit up on keystrokes.
        self.ring_segment_ids = []
        n = RING_SEGMENTS
        gap_deg = 4  # gap between segments, in degrees
        seg_extent = (360.0 / n) - gap_deg
        for i in range(n):
            start_deg = i * (360.0 / n) + gap_deg / 2
            seg_id = self.canvas.create_arc(
                cx - ring_radius, cy - ring_radius,
                cx + ring_radius, cy + ring_radius,
                start=start_deg, extent=seg_extent,
                style="arc", outline=RING_UNLIT, width=14)
            self.ring_segment_ids.append(seg_id)

        # ugly yellow square body
        sq = 130
        self.canvas.create_rectangle(cx - sq/2, cy - sq/2 + 30, cx + sq/2, cy + sq/2 + 30,
                                      fill=UGLY_YELLOW, outline=UGLY_PINK, width=6)

        # ugly dark blue handle (crooked arc + rectangles, on purpose ugly)
        self.canvas.create_arc(cx - 55, cy - 110, cx + 55, cy + 10,
                                start=0, extent=180, style="arc",
                                outline=UGLY_BLUE, width=22)
        self.canvas.create_rectangle(cx - 8, cy - 20, cx + 14, cy + 40,
                                      fill=UGLY_BLUE, outline="black", width=3)

        # keyhole, off-center on purpose
        self.canvas.create_oval(cx - 14, cy + 15, cx + 4, cy + 35,
                                 fill=UGLY_BLUE, outline="")
        self.canvas.create_rectangle(cx - 6, cy + 28, cx + 2, cy + 55,
                                      fill=UGLY_BLUE, outline="")

        clash_font = tkfont.Font(family="Sans", size=20, weight="bold")
        self.canvas.create_text(cx, cy - ring_radius - 40,
                                 text="LOCKED", fill=UGLY_GREEN, font=clash_font)

        # progress dots, no digits/chars shown, just count typed
        self.progress_text = self.canvas.create_text(
            cx, cy + ring_radius + 40, text="", fill="white",
            font=tkfont.Font(family="Sans", size=18, weight="bold"))

    def _update_progress_dots(self):
        dots = "*" * len(self.typed)
        self.canvas.itemconfig(self.progress_text, text=dots)

    # -- random flash effect --------------------------------------------
    def _flash(self, correct: bool):
        # Pick a random ring segment and light it up briefly, instead of
        # drawing a random blob on screen.
        seg_id = random.choice(self.ring_segment_ids)
        color = UGLY_LIGHT_GREEN if correct else UGLY_RED
        self.canvas.itemconfig(seg_id, outline=color, width=20)
        # quick flash: revert to unlit shortly after
        self.root.after(90, lambda: self._unlight_segment(seg_id))

    def _unlight_segment(self, seg_id):
        try:
            self.canvas.itemconfig(seg_id, outline=RING_UNLIT, width=14)
        except tk.TclError:
            return

    # -- input handling ------------------------------------------------
    def on_key(self, event):
        # Check if we're still in lockout period after a wrong guess
        now = self.root.tk.call('clock', 'milliseconds')
        if int(now) < self.locked_until:
            return  # Ignore keystrokes during lockout
        
        ch = event.char
        if ch and ch.isprintable():
            pos = len(self.typed)
            if pos < self.length:
                expected_hash = self.hashes[pos]
                actual_hash = hash_char(self.salt, pos, ch)
                correct = (expected_hash == actual_hash)
            else:
                correct = False
            self.typed.append(ch)
            self.correctness.append(correct)
            self._flash(correct)
            self._update_progress_dots()

            if not correct:
                # Wrong character: lock out input for 3500ms, then wipe progress
                self.locked_until = int(now) + WRONG_CHAR_LOCKOUT_MS
                self.root.after(WRONG_CHAR_LOCKOUT_MS, self.reset_attempt)

        elif event.keysym == "BackSpace":
            if self.typed:
                self.typed.pop()
                self.correctness.pop()
                self._update_progress_dots()

        elif event.keysym == "Return":
            now = self.root.tk.call('clock', 'milliseconds')
            self.enter_times.append(int(now))
            # keep only presses within the last TRIPLE_TAP_WINDOW_MS
            self.enter_times = [t for t in self.enter_times
                                 if now - t <= TRIPLE_TAP_WINDOW_MS]
            if len(self.enter_times) >= 3:
                self.enter_times = []
                self.check_full()

    def check_full(self):
        all_correct = (len(self.typed) == self.length and all(self.correctness))
        if all_correct:
            self.unlock()
        else:
            now = self.root.tk.call('clock', 'milliseconds')
            self.locked_until = int(now) + WRONG_CHAR_LOCKOUT_MS
            self.root.after(WRONG_CHAR_LOCKOUT_MS, self.reset_attempt)

    def reset_attempt(self):
        self.typed = []
        self.correctness = []
        self.enter_times = []
        self._update_progress_dots()

    def unlock(self):
        self.root.grab_release()
        self.root.destroy()


# ---------------------------------------------------------------------------

def main():
    if "--setup" in sys.argv or load_pin_data() is None:
        run_setup()
        if load_pin_data() is None:
            return  # user closed setup without saving

    pin_data = load_pin_data()
    LockScreen(pin_data)


if __name__ == "__main__":
    main()
