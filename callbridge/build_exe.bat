@echo off
rem Crea un entorno, instala dependencias y genera dist\CallBridge\CallBridge.exe
cd /d "%~dp0"
if not exist .venv (
  py -3.11 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pyinstaller --noconfirm CallBridge.spec
echo.
echo Listo: dist\CallBridge\CallBridge.exe
pause
