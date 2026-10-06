python -m nuitka --standalone --onefile ^
  --windows-icon-from-ico="./res/icon.ico" --enable-plugin=tk-inter ^
  --include-data-dir=res=res ^
  --include-data-files=NBT-version-1.5.1/nbt/nbt.py=NBT-version-1.5.1/nbt/nbt.py ^
  --assume-yes-for-downloads --windows-console-mode=attach main.py
pause