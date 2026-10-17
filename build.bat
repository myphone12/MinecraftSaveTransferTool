python -m nuitka --mode=app ^
  --windows-icon-from-ico="./res/icon.ico" --enable-plugin=tk-inter ^
  --include-data-dir=res=res ^
  --include-package=nbt ^
  --assume-yes-for-downloads --windows-console-mode=attach main.py
pause