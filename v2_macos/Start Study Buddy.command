#!/bin/bash
# Double-click this file to start Study Buddy. You can close the Terminal window afterwards.
cd "$(dirname "$0")" || exit 1

# Prefer the python.org Python: its Tk works properly on current macOS.
for py in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import tkinter" >/dev/null 2>&1; then
    nohup "$py" study_buddy.py >/dev/null 2>&1 &
    disown
    echo "Study Buddy is starting. You can close this window."
    exit 0
  fi
done

echo "I couldn't find Python with Tk. Install Python from https://www.python.org/downloads/macos/"
echo "then double-click this file again."
read -r -p "Press Return to close."
