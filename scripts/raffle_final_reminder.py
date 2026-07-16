"""Final 'closing soon' reminder for the active raffle, meant to run at 10:30pm
Mexico City time (30 min before ticket sales close at 11:00pm). Standalone
script: does not import main.py, only talks to Supabase REST + Telegram Bot API
directly, matching every other one-off admin script run this session.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
BOT_TOKEN = "8914862269:AAH9CABVEHO7nni9UalM6b3J5MSs7YyzZU0"

CART_PAYMENT_INFO = (
    "💳 Cuenta CLABE (BBVA)\n"
    "Silvia Montalvo\n"
    "012700015287595938\n\n"
    "🌎 ¿Eres extranjero?\n"
    "Puedes hacer tu depósito directo por Felix, Xoom o Remitly."
)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    with open(REPO_DIR / ".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def sb_get(base_url: str, key: str, path: str):
    url = f"{base_url}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def tg_api(method: str, params: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main() -> None:
    env = load_env()
    base_url = env["SUPABASE_URL"]
    key = env["SUPABASE_SERVICE_ROLE_KEY"]

    raffles = sb_get(base_url, key, "raffle_events?select=*&status=eq.active")
    if not raffles:
        print("No hay rifa activa. No se manda recordatorio.")
        return
    raffle = raffles[0]
    raffle_id = raffle["id"]
    print(f"Rifa activa: {raffle.get('title')} (id={raffle_id})")

    reserved = sb_get(
        base_url, key, f"raffle_tickets?select=*&raffle_id=eq.{raffle_id}&payment_status=eq.reserved"
    )
    by_user: dict[int, list[str]] = defaultdict(list)
    for row in reserved:
        by_user[row["telegram_id"]].append(row["ticket_number"])

    print(f"Usuarios con boletos reservados sin pagar: {len(by_user)}")

    sent = 0
    failed = []
    for tid, nums in by_user.items():
        total = len(nums) * 50
        nums_text = ", ".join(nums)
        text = (
            "⏰ ÚLTIMA LLAMADA — Sorteo Hot Tub 🔥\n\n"
            f"Tus boletos {nums_text} se liberan si no pagas antes de las 11:00pm de HOY.\n\n"
            f"Total: ${total} MXN\n\n"
            f"{CART_PAYMENT_INFO}\n\n"
            "Manda tu comprobante aquí mismo para no perder tu lugar 🙏"
        )
        result = tg_api("sendMessage", {"chat_id": tid, "text": text})
        if result.get("ok"):
            sent += 1
        else:
            failed.append((tid, result.get("description")))
        time.sleep(0.05)

    print(f"Enviados: {sent}")
    print(f"Fallidos: {len(failed)}")
    for f in failed:
        print(" ", f)


if __name__ == "__main__":
    main()
