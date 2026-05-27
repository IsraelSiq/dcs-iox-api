# launcher.py
# Inicia o servidor dcs-iox-api e abre o radar no browser automaticamente.
# Funciona tanto via `python launcher.py` quanto como .exe (PyInstaller).
import sys
import os
import asyncio
import threading
import time
import webbrowser

# --- PyInstaller: ajusta path para o bundle ---
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS
    if base not in sys.path:
        sys.path.insert(0, base)
    os.chdir(base)

RADAR_URL   = "http://127.0.0.1:8000/radar"
HEALTH_URL  = "http://127.0.0.1:8000/health"
OPEN_DELAY  = 3.0   # segundos para aguardar o servidor subir antes de abrir o browser


def wait_and_open_browser():
    """Aguarda o servidor responder e abre o radar no browser padrão."""
    import urllib.request
    deadline = time.time() + 15.0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            break  # servidor respondeu
        except Exception:
            time.sleep(0.5)
    webbrowser.open(RADAR_URL)
    print(f"[launcher] Browser aberto em {RADAR_URL}")


def main():
    print("============================================")
    print("  DCS IOX API")
    print("  Radar: http://127.0.0.1:8000/radar")
    print("  Dashboard: http://127.0.0.1:8000/dashboard")
    print("  Pressione Ctrl+C para encerrar.")
    print("============================================\n")

    # Abre o browser em background enquanto o servidor sobe
    t = threading.Thread(target=wait_and_open_browser, daemon=True)
    t.start()

    from server.main import main as server_main
    try:
        asyncio.run(server_main())
    except KeyboardInterrupt:
        print("\n[launcher] Encerrado.")


if __name__ == "__main__":
    main()
