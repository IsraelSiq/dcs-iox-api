# launcher.py — entry point para o executável PyInstaller
# Garante que imports do pacote 'server' funcionam quando rodando como .exe
import sys
import os

# Quando empacotado pelo PyInstaller, sys._MEIPASS aponta para o bundle
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS
    if base not in sys.path:
        sys.path.insert(0, base)
    # Workaround: uvicorn precisa encontrar o app via string "server.api:app"
    os.chdir(base)

import asyncio

def main():
    from server.main import main as server_main
    try:
        asyncio.run(server_main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
