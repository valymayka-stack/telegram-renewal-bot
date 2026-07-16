"""Draws the top-3 raffle winners, announces them in the content channel, and
delivers prizes automatically by DM. Meant to run once at 11:30pm Mexico City
time, 30 min after ticket sales close.

Standalone script (does not import main.py) so it can run cold from a
scheduled task with zero dependency on the live bot process. Mirrors the
logic in main.py's announce_and_deliver_raffle_top3 / deliver_raffle_grupo_prize /
deliver_raffle_set_prize / draw_raffle_winners_top3 (as of commit 72eddc1 +
the already_drawn guard added right after).

Idempotent: if the raffle already has a winner_ticket set, this exits
without drawing again or re-delivering prizes (prevents double-granting a
30-day renewal or duplicate invite links if run twice by accident).
"""
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_DIR = Path(__file__).resolve().parent.parent
BOT_TOKEN = "8914862269:AAH9CABVEHO7nni9UalM6b3J5MSs7YyzZU0"
CONTENT_CHANNEL_ID = -1003915464312
ADMIN_ID = 7872669612
APP_TZ = ZoneInfo("America/Mexico_City")
INVITE_LINK_LIFETIME_SECONDS = 24 * 60 * 60

GRUPO_CODE = "grupo"
GRUPO_BUNDLED_CODES = {"nuevos_sus", "blue_love"}
SET_PRIZE_CODE = "hot_tub"
GRUPO_RANKS = {1, 2}
SET_RANKS = {1, 3}
PRIZE_LABELS = {
    1: "1 mes de Grupo Exclusivo + set Hot Tub",
    2: "1 mes de Grupo Exclusivo",
    3: "set Hot Tub",
}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


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


ENV = load_env()
SUPABASE_URL = ENV["SUPABASE_URL"]
SUPABASE_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]


def sb_get(path: str):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def sb_patch(path: str, body: dict):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="PATCH",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def sb_upsert(path: str, body: dict, on_conflict: str):
    url = f"{SUPABASE_URL}/rest/v1/{path}?on_conflict={on_conflict}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def tg_api(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return json.load(e)


def create_invite_link(chat_id: int, name_prefix: str, telegram_id: int) -> tuple[str, str]:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    name = f"raffle-{name_prefix}-{telegram_id}-{timestamp}"[:32]
    expire_date = int(datetime.now(timezone.utc).timestamp()) + INVITE_LINK_LIFETIME_SECONDS
    result = tg_api(
        "createChatInviteLink",
        {"chat_id": chat_id, "name": name, "member_limit": 1, "expire_date": expire_date},
    )
    if not result.get("ok"):
        raise RuntimeError(f"createChatInviteLink failed: {result.get('description')}")
    return result["result"]["invite_link"], name


def save_user_channel_access(telegram_id: int, channel: dict, invite_link: str, invite_name: str, expires_at: str | None):
    payload = {
        "telegram_id": telegram_id,
        "channel_key": channel["code"],
        "channel_label": channel["title"],
        "chat_id": str(channel["telegram_chat_id"]),
        "invite_link": invite_link,
        "invite_link_name": invite_name,
        "invite_link_created_at": datetime.now(timezone.utc).isoformat(),
        "invite_link_revoked": False,
        "invite_link_used": False,
        "status": "active",
        "access_status": "active",
        "granted_at": datetime.now(timezone.utc).isoformat(),
        "joined_channel_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    sb_upsert("user_channel_access", payload, on_conflict="telegram_id,channel_key")


def user_has_active_membership(user: dict | None) -> bool:
    if not user or user.get("status") != "active":
        return False
    expiry_raw = user.get("expiry_date")
    if not expiry_raw:
        return False
    expiry = datetime.fromisoformat(expiry_raw).date()
    return expiry >= datetime.now(APP_TZ).date()


def deliver_grupo_prize(telegram_id: int) -> str:
    existing = sb_get(f"telegram_users?select=*&telegram_id=eq.{telegram_id}")
    existing_user = existing[0] if existing else None

    if user_has_active_membership(existing_user):
        current_expiry = datetime.fromisoformat(existing_user["expiry_date"]).date()
        new_expiry = current_expiry + timedelta(days=30)
        sb_patch(
            f"telegram_users?telegram_id=eq.{telegram_id}",
            {
                "expiry_date": new_expiry.isoformat(),
                "status": "active",
                "payment_status": "paid",
                "last_payment_at": datetime.now(timezone.utc).isoformat(),
                "approved_by_admin_id": ADMIN_ID,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "notes": "Raffle prize: Grupo renewed +30 days from current expiry_date",
            },
        )
        expiry_display = new_expiry.strftime("%d/%m/%Y")
        tg_api(
            "sendMessage",
            {
                "chat_id": telegram_id,
                "text": (
                    "🎉 ¡Felicidades, ganaste el sorteo! 🎁\n\n"
                    "Como ya tienes el Grupo activo, tu suscripción se renovó 30 días más.\n\n"
                    f"Tu nueva fecha de vencimiento es: {expiry_display}"
                ),
            },
        )
        return f"Grupo renovado (ya era miembro) — nuevo vencimiento {new_expiry.isoformat()}"

    channels = sb_get(f"access_channels?select=*&code=in.(grupo,nuevos_sus,blue_love)")
    channels_by_code = {c["code"]: c for c in channels}
    grupo_channel = channels_by_code.get(GRUPO_CODE)
    if not grupo_channel:
        raise RuntimeError("Canal Grupo no encontrado en access_channels")

    today = datetime.now(APP_TZ).date()
    expiry_date = today + timedelta(days=30)
    channel_links = []
    main_invite_link = ""
    main_invite_name = ""
    for code in [GRUPO_CODE, *GRUPO_BUNDLED_CODES]:
        channel = channels_by_code.get(code)
        if not channel:
            continue
        invite_link, invite_name = create_invite_link(channel["telegram_chat_id"], code, telegram_id)
        expires_at = expiry_date.isoformat() if channel.get("has_expiry") else None
        save_user_channel_access(telegram_id, channel, invite_link, invite_name, expires_at)
        channel_links.append((channel["title"], invite_link))
        if code == GRUPO_CODE:
            main_invite_link, main_invite_name = invite_link, invite_name

    sb_patch(
        f"telegram_users?telegram_id=eq.{telegram_id}",
        {
            "telegram_id": telegram_id,
            "status": "active",
            "payment_status": "paid",
            "invite_link": main_invite_link,
            "invite_link_name": main_invite_name,
            "invite_link_revoked": False,
            "invite_link_used": False,
            "invite_link_created_at": datetime.now(timezone.utc).isoformat(),
            "membership_start_date": today.isoformat(),
            "expiry_date": expiry_date.isoformat(),
            "approved_by_admin_id": ADMIN_ID,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "last_payment_at": datetime.now(timezone.utc).isoformat(),
            "notes": "Raffle prize: Grupo",
        },
    )
    # telegram_users may not have a row yet for a brand-new user; PATCH with no match is a no-op, so insert as fallback.
    if not existing_user:
        sb_upsert(
            "telegram_users",
            {
                "telegram_id": telegram_id,
                "status": "active",
                "payment_status": "paid",
                "invite_link": main_invite_link,
                "invite_link_name": main_invite_name,
                "invite_link_revoked": False,
                "invite_link_used": False,
                "invite_link_created_at": datetime.now(timezone.utc).isoformat(),
                "membership_start_date": today.isoformat(),
                "expiry_date": expiry_date.isoformat(),
                "approved_by_admin_id": ADMIN_ID,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "last_payment_at": datetime.now(timezone.utc).isoformat(),
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "notes": "Raffle prize: Grupo (new user)",
            },
            on_conflict="telegram_id",
        )

    lines = ["🎉 ¡Felicidades, ganaste el sorteo! 🎁", "", "Aquí está tu acceso:"]
    for label, link in channel_links:
        lines.append(f"{label}: {link}")
    tg_api("sendMessage", {"chat_id": telegram_id, "text": "\n".join(lines)})
    return f"Grupo nuevo (+{len(channel_links) - 1} canales incluidos) — vence {expiry_date.isoformat()}"


def deliver_set_prize(telegram_id: int) -> str:
    channels = sb_get(f"access_channels?select=*&code=eq.{SET_PRIZE_CODE}")
    if not channels:
        raise RuntimeError(f"Canal premio no encontrado: {SET_PRIZE_CODE}")
    channel = channels[0]
    invite_link, invite_name = create_invite_link(channel["telegram_chat_id"], SET_PRIZE_CODE, telegram_id)
    save_user_channel_access(telegram_id, channel, invite_link, invite_name, None)
    tg_api(
        "sendMessage",
        {
            "chat_id": telegram_id,
            "text": f"🎁 ¡Felicidades, ganaste el sorteo! Aquí está tu acceso al set {channel['title']}:\n{invite_link}",
        },
    )
    return f"Set {channel['title']} entregado"


def main() -> None:
    raffles = sb_get("raffle_events?select=*&status=eq.active")
    if not raffles:
        print("No hay ninguna rifa activa. Nada que sortear.")
        return
    raffle = raffles[0]
    raffle_id = raffle["id"]
    print(f"Rifa: {raffle.get('title')} (id={raffle_id})")

    if raffle.get("winner_ticket"):
        print("Ya se había sorteado y entregado antes. No se vuelve a sortear ni a reenviar premios.")
        return

    tickets = sb_get(f"raffle_tickets?select=*&raffle_id=eq.{raffle_id}&payment_status=eq.confirmed")
    if not tickets:
        print("No hay boletos confirmados/pagados. No se puede sortear.")
        return

    pool = list(tickets)
    winners = []
    for _ in range(min(3, len(pool))):
        winners.append(pool.pop(secrets.randbelow(len(pool))))

    payload = {
        "winner_ticket": winners[0]["ticket_number"],
        "winner_telegram_id": winners[0]["telegram_id"],
        "winner_drawn_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if len(winners) > 1:
        payload["second_place_ticket"] = winners[1]["ticket_number"]
        payload["second_place_telegram_id"] = winners[1]["telegram_id"]
    if len(winners) > 2:
        payload["third_place_ticket"] = winners[2]["ticket_number"]
        payload["third_place_telegram_id"] = winners[2]["telegram_id"]

    claimed = sb_patch(f"raffle_events?id=eq.{raffle_id}&winner_drawn_at=is.null", payload)
    if not claimed:
        print("El sorteo ya fue reclamado por otra ejecución justo antes de esta. Abortando para no duplicar entregas.")
        return

    places = {i + 1: w for i, w in enumerate(winners)}
    print("Ganadores:")
    for rank, w in places.items():
        print(f"  {MEDALS.get(rank, '')} Lugar {rank}: boleto {w['ticket_number']} — telegram_id {w['telegram_id']}")

    # Public announcement (no telegram_id/username exposed)
    lines = [f"🎉 GANADORES — {raffle.get('title') or 'Sorteo'} 🎉", ""]
    for rank, w in places.items():
        lines.append(f"{MEDALS.get(rank, '•')} Boleto {w['ticket_number']} — {PRIZE_LABELS.get(rank, '')}")
    lines.append("")
    lines.append("📩 Los premios se enviarán por privado a cada ganador. ¡Felicidades! 🎊")
    ann = tg_api("sendMessage", {"chat_id": CONTENT_CHANNEL_ID, "text": "\n".join(lines)})
    print("Anuncio publicado:" if ann.get("ok") else f"FALLÓ el anuncio: {ann.get('description')}")

    delivery_log = []
    for rank, w in places.items():
        telegram_id = int(w["telegram_id"])
        try:
            if rank in GRUPO_RANKS:
                status = deliver_grupo_prize(telegram_id)
                delivery_log.append(f"Lugar {rank} ({telegram_id}): {status}")
            if rank in SET_RANKS:
                status = deliver_set_prize(telegram_id)
                delivery_log.append(f"Lugar {rank} ({telegram_id}): {status}")
        except Exception as exc:
            delivery_log.append(f"Lugar {rank} ({telegram_id}): ERROR - {exc}")
        time.sleep(0.2)

    print("\nEntrega de premios:")
    for line in delivery_log:
        print(" ", line)


if __name__ == "__main__":
    main()
