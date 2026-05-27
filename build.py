# build.py
# Gera dist/dcs-iox-api.exe via PyInstaller.
# Uso: python build.py
#
# Pre-requisito: pip install pyinstaller
# Output:        dist/dcs-iox-api.exe
import subprocess
import sys
import os

EXE_NAME = "dcs-iox-api"

# Inclui icone se existir em assets/icon.ico
icon_args = []
if os.path.exists("assets/icon.ico"):
    icon_args = ["--icon", "assets/icon.ico"]

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--name", EXE_NAME,
    "--console",                          # mostra janela de terminal com os logs
    # Pacote server
    "--add-data", "server;server",
    # Coleta modulos dinamicos
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    "--collect-all", "starlette",
    "--collect-all", "pydantic",
    "--collect-all", "pydantic_core",
    "--collect-all", "anyio",
    "--collect-all", "h11",
    "--collect-all", "httptools",
    "--collect-all", "websockets",
    # Hidden imports uvicorn
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops",
    "--hidden-import", "uvicorn.loops.asyncio",
    "--hidden-import", "uvicorn.protocols",
    "--hidden-import", "uvicorn.protocols.http",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.websockets",
    "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
    "--hidden-import", "uvicorn.lifespan",
    "--hidden-import", "uvicorn.lifespan.on",
    # Stdlib
    "--hidden-import", "email.mime.text",
    "--hidden-import", "email.mime.multipart",
    "--hidden-import", "logging.handlers",
    "--hidden-import", "asyncio",
    "--hidden-import", "webbrowser",
    "--hidden-import", "threading",
    "--hidden-import", "urllib.request",
    *icon_args,
    "--noconfirm",
    "--clean",
    "launcher.py",
]

print(f"[build] Gerando {EXE_NAME}.exe...")
print("[build] Isso pode demorar 1-3 minutos na primeira vez.\n")

result = subprocess.run(cmd)

if result.returncode == 0:
    print(f"\n[build] Sucesso! Executavel em: dist/{EXE_NAME}.exe")
    print(f"[build] Para rodar: .\\dist\\{EXE_NAME}.exe")
else:
    print("\n[build] Falhou. Veja o log acima.")
    sys.exit(1)
