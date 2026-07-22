#!/usr/bin/env python3
"""
Spectra7 — Multi-Protocol Bombing Engine
Usage: python spectra7.py
"""
import os
import sys
import secrets as _secrets
import webbrowser
from threading import Timer
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from utils.logger import init_db


def check_first_run():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    have_file = os.path.exists(env_path)

    # If .env exists with SECRET_KEY, we're good
    if have_file:
        with open(env_path) as _f:
            for _line in _f:
                if _line.startswith("SECRET_KEY="):
                    print("[*] Configuration found (.env).")
                    return
        # .env exists but no SECRET_KEY — rewrite it below

    # If all essential vars are already in os.environ (Render dashboard), skip .env
    env_has_secret = bool(os.getenv("SECRET_KEY"))
    env_has_pass = bool(os.getenv("DASHBOARD_PASSWORD"))
    if env_has_secret and env_has_pass:
        print("[*] Configuration found (environment variables).")
        return

    # First run — generate .env
    print("[!] First run. Generating configuration...")
    secret_key = _secrets.token_hex(32)
    dash_pw = os.getenv("DASHBOARD_PASSWORD") or _secrets.token_urlsafe(12)

    if not os.getenv("DASHBOARD_PASSWORD"):
        print(f"[!] Generated DASHBOARD_PASSWORD: {dash_pw}")
        print("[!] Set DASHBOARD_PASSWORD in Render dashboard to use a custom password.")

    with open(env_path, "w") as f:
        f.write(f"SECRET_KEY={secret_key}\n")
        f.write(f"DASHBOARD_PASSWORD={dash_pw}\n")
        f.write("HOST=0.0.0.0\n")
        f.write("PORT=5000\n")
        f.write("MAX_PER_TARGET_PER_DAY=250\n")
    print("[+] Configuration saved to .env")


def open_browser(port):
    webbrowser.open(f"http://127.0.0.1:{port}")


def main():
    print("""
    ╔═══════════════════════════════════════╗
    ║          S P E C T R A  7             ║
    ║        BOMBING ENGINE                 ║
    ║      [ SMS | CALL ]                   ║
    ╚═══════════════════════════════════════╝
    """)

    check_first_run()
    init_db()

    port = int(os.getenv("PORT", 10000))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"[*] Binding: {host}:{port}")

    from web.app import app
    print(f"[*] Starting Spectra7 (waitress)...")
    from waitress import serve
    serve(app, host=host, port=port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Shutdown.")
        sys.exit(0)
