@echo off
rem Build FB2TranslationEditor.exe (output: dist\FB2TranslationEditor\)
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name FB2TranslationEditor --icon assets\icon.ico --add-data "fb2editor\dicts;fb2editor\dicts" --collect-submodules spylls run.pyw
echo.
echo Done: dist\FB2TranslationEditor\FB2TranslationEditor.exe
pause
