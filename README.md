# Study Buddy

A free, screen-aware study partner. Press a shortcut (or click the floating bubble) and it
looks at your screen, reads your school files, searches the web and helps you work through
assignments step by step. Anything it makes for you (notes, flashcards, practice quizzes) is
saved in **Documents/Study Buddy**.

It thinks with [Claude Code](https://claude.com/claude-code), so there's no API key to set up.

| Version | Folder | For |
| --- | --- | --- |
| v1 | [`v1_windows`](v1_windows) | Windows 10 and 11 |
| v2 | [`v2_macos`](v2_macos) | macOS (Intel and Apple silicon) |

## Download

1. On this page, click the green **Code** button, then **Download ZIP**.
2. Unzip it and open the folder for your computer: `v1_windows` or `v2_macos`.

## Before you start (both versions)

1. Install **Python 3** from [python.org/downloads](https://www.python.org/downloads/).
   On Windows, tick **Add python.exe to PATH** in the installer.
2. Install **Claude Code** from [claude.com/claude-code](https://claude.com/claude-code), then open a
   terminal, type `claude` and sign in once.

## Windows (v1_windows)

Double-click `study_buddy.pyw`.

- **Ctrl+Alt+Space** shows or hides it and takes a screenshot.
- Snip part of your screen with **Win+Shift+S**, then press **Ctrl+V** in the chat.
- **Talk** starts Windows voice typing.

## macOS (v2_macos)

Double-click **Start Study Buddy.command**.

The first time, macOS may say it "could not verify" the file. Click **Done**, open
**System Settings › Privacy & Security**, scroll to the bottom and click **Open Anyway** next to
"Start Study Buddy.command", then confirm with your password.

Use the Python from python.org, not the `python3` that comes with macOS. Apple's built-in one
can crash with an error like `macOS 15 (1508) or later required`. You can also start Study Buddy
from Terminal:

```
/Library/Frameworks/Python.framework/Versions/Current/bin/python3 path/to/v2_macos/study_buddy.py
```

- **Control+Option+B** shows or hides it and takes a screenshot. If another app already
  uses that shortcut, the status line at the bottom of the window shows the one it picked.
- Snip part of your screen with **Control+Shift+Command+4**, then press **Command+V** in the chat.
- To talk instead of type, press **Fn (Globe) twice** to start macOS Dictation.
- **Command+Q** quits it.

macOS will ask for a few permissions the first time. Click **Allow** for each:

- **Screen Recording** lets it see your screen. If screenshots only show your wallpaper, go to
  **System Settings › Privacy & Security › Screen Recording**, turn on **Terminal** (or
  **Python**), then quit and restart Study Buddy.
- **Documents, Desktop and Downloads** let it read your schoolwork.
