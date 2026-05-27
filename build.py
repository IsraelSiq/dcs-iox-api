# build.py — gera dist/dcs-iox-api.exe via PyInstaller
# Uso: python build.py
#
# Pre-requisito: pip install pyinstaller
# Output:        dist/dcs-iox-api.exe  (~60-90 MB)
import subprocess
import sys

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",                          # tudo em um unico .exe
    "--name", "dcs-iox-api",
    "--console",                          # janela de terminal (logs visiveis)
    # Inclui o pacote server inteiro
    "--add-data", "server;server",
    # Coleta modulos que o uvicorn/fastapi carregam dinamicamente
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    "--collect-all", "starlette",
    "--collect-all", "pydantic",
    "--collect-all", "pydantic_core",
    "--collect-all", "anyio",
    "--collect-all", "h11",
    "--collect-all", "httptools",
    "--collect-all", "websockets",
    # Imports ocultos comuns com uvicorn[standard]
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
    "--hidden-import", "email.mime.text",
    "--hidden-import", "email.mime.multipart",
    "--hidden-import", "logging.handlers",
    "--hidden-import", "asyncio",
    "--noconfirm",                        # sobrescreve build anterior sem perguntar
    "--clean",                            # limpa cache antes de buildar
    "launcher.py",                        # entry point
]

print("[build] Rodando PyInstaller...")
print("[build] Isso pode demorar 1-3 minutos na primeira vez.\n")

result = subprocess.run(cmd)

if result.returncode == 0:
    print("\n[build] ✅ Sucesso! Executavel em: dist/dcs-iox-api.exe")
    print("[build] Para rodar: .\\dist\\dcs-iox-api.exe")
else:
    print("\n[build] ❌ Falhou. Veja o log acima.")
    sys.exit(1)
