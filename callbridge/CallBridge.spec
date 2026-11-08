# -*- mode: python ; coding: utf-8 -*-
# Empaquetado: pyinstaller CallBridge.spec   (o build_exe.bat)
# Genera dist/CallBridge/CallBridge.exe (carpeta, arranca más rápido que --onefile).
from PyInstaller.utils.hooks import collect_all

import os

datas = [("callbridge/web", "callbridge/web")]
if os.path.exists("callbridge/android/CallBridge.apk"):   # la APK que instala el botón del puente
    datas.append(("callbridge/android/CallBridge.apk", "callbridge/android"))
binaries = []
hiddenimports = []
for pkg in ("faster_whisper", "ctranslate2", "sherpa_onnx", "onnxruntime", "av", "webview", "llama_cpp",
            "sounddevice", "_sounddevice_data", "soundfile", "_soundfile_data"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:  # paquete opcional no instalado (p. ej. llama_cpp)
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CallBridge",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CallBridge")
