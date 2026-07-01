# Locker (Unix/Linux)

An intentionally ugly lock screen with a passphrase.

- Passphrase can be any length (min 4 characters), any mix of letters,
  numbers, and symbols.
- Nothing is ever stored in plaintext — each character is salted and
  SHA-256 hashed.
- To submit, press **Enter 3 times within 219.5491ms**. A single Enter does
  nothing.
- Wrong guess? 5000ms lockout, then you start over.

## Requirements

- Python 3.8+
- `tkinter` (part of standard Python, but some Linux distros split it out)

On Fedora/RHEL:
```bash
sudo dnf install python3-tkinter
```

On Debian/Ubuntu:
```bash
sudo apt install python3-tk
```

## Setup

1. Download `lock.py` and put it somewhere permanent (not a temp/Downloads
   folder you'll clean out later).
2. Set your passphrase:

   ```bash
   python3 lock.py --setup
   ```

3. Test it:

   ```bash
   python3 lock.py
   ```

   Type your passphrase, then press **Enter 3 times fast** to unlock.

## Linux (GNOME/Fedora) — keyboard shortcut

Use the included `setup_shortcut.sh`. It registers a GNOME custom
keybinding (default `Ctrl+Alt+L`) that runs `lock.py`.

```bash
bash setup_shortcut.sh
```

To change the key combo, edit `SHORTCUT_KEY` near the top of the script
before running it, or change it later in **Settings > Keyboard > Custom
Shortcuts > Locker**.

Note: This is **NOT** a security feature and is just meant to keep those you dont want to see your laptop out and for a guessing game.
