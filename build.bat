@echo off
rem Builds dist\ChopChopSaveConverter.exe (needs Python 3.10+ on PATH).
python -m pip install -r requirements-build.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --name ChopChopSaveConverter ^
  --add-data "data;data" ^
  chopchop_convert.py || exit /b 1
dist\ChopChopSaveConverter.exe --self-test
