@echo off
REM Build the standalone Windows executable with PyInstaller.
REM Output: dist\POTA-Accessible-Spots.exe (a single, self-contained file).
REM
REM Requires PyInstaller:  py -m pip install -r requirements-dev.txt

setlocal
cd /d "%~dp0"

py -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name "POTA-Accessible-Spots" ^
  --distpath dist ^
  --workpath build ^
  --specpath build ^
  pota_accessible.py

echo.
echo Done. See dist\POTA-Accessible-Spots.exe
endlocal
