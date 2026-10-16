python -m nuitka --standalone --onefile ^
  --windows-icon-from-ico="./res/icon.ico" --enable-plugin=tk-inter ^
  --include-data-dir=res=res ^
  --assume-yes-for-downloads --windows-console-mode=attach main.py
pause