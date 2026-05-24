import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message, PollAnswer
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from supabase import Client, create_client


POLL_QUESTION = "¿Qué contenido te gustaría ver más este mes?"
POLL_OPTIONS = ["Fotos", "Videos", "Lives", "Todo"]
DATE_FORMAT = "%Y-%m-%d"
APP_TIMEZONE = ZoneInfo("America/Mexico_City")

logger = logging.getLogger(__name__)
router = Router()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    supabase_url: str
    supabase_service_role_key: str
    admin_chat_id: int
    content_channel_id: int | str
    admin_user_ids: set[int]


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_chat_id(value: str) -> int | str:
    value = value.strip()
    if value.startswith("@"):
        return value
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError("CONTENT_CHANNEL_ID must be a numeric chat ID or @channelusername") from exc


def parse_admin_ids(value: str) -> set[int]:
    admin_ids: set[int] = set()
    for raw_id in value.split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            admin_ids.add(int(raw_id))
        except ValueError as exc:
            raise RuntimeError("ADMIN_USER_IDS must be a comma-separated list of Telegram user IDs") from exc
    if not admin_ids:
        raise RuntimeError("ADMIN_USER_IDS must include at least one Telegram user ID")
    return admin_ids


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=required_env("BOT_TOKEN"),
        supabase_url=required_env("SUPABASE_URL"),
        supabase_service_role_key=required_env("SUPABASE_SERVICE_ROLE_KEY"),
        admin_chat_id=int(required_env("ADMIN_CHAT_ID")),
        content_channel_id=parse_chat_id(required_env("CONTENT_CHANNEL_ID")),
        admin_user_ids=parse_admin_ids(required_env("ADMIN_USER_IDS")),
    )


def is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_user_ids)


async def reject_non_admin(message: Message) -> None:
    await message.answer("No autorizado.")


def today_iso() -> str:
    return datetime.now(APP_TIMEZONE).date().isoformat()


async def send_long_message(message: Message, text: str) -> None:
    max_length = 3900
    for index in range(0, len(text), max_length):
        await message.answer(text[index : index + max_length])


def format_user(row: dict[str, Any]) -> str:
    telegram_id = row.get("telegram_id", "N/A")
    username = row.get("username")
    first_name = row.get("first_name") or ""
    last_name = row.get("last_name") or ""
    selected = row.get("selected_option") or "-"
    expiry = row.get("expiry_date") or "-"
    handle = f"@{username}" if username else "(sin username)"
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or "(sin nombre)"
    return f"{telegram_id} | {handle} | {full_name} | poll: {selected} | vence: {expiry}"


def get_registered_user(supabase: Client, telegram_id: int) -> dict[str, Any] | None:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def upsert_poll_user(supabase: Client, poll_answer: PollAnswer) -> None:
    selected_option = None
    if poll_answer.option_ids:
        option_id = poll_answer.option_ids[0]
        selected_option = POLL_OPTIONS[option_id] if 0 <= option_id < len(POLL_OPTIONS) else str(option_id)

    existing = get_registered_user(supabase, poll_answer.user.id)
    payload = {
        "telegram_id": poll_answer.user.id,
        "username": poll_answer.user.username,
        "first_name": poll_answer.user.first_name,
        "last_name": poll_answer.user.last_name,
        "last_poll_id": poll_answer.poll_id,
        "selected_option": selected_option,
    }

    if existing:
        (
            supabase.table("telegram_users")
            .update(payload)
            .eq("telegram_id", poll_answer.user.id)
            .execute()
        )
        logger.info("Updated poll answer for telegram_id=%s", poll_answer.user.id)
        return

    payload["registered_at"] = datetime.now(timezone.utc).isoformat()
    supabase.table("telegram_users").insert(payload).execute()
    logger.info("Registered poll user telegram_id=%s", poll_answer.user.id)


@router.message(Command("send_poll"))
async def send_poll(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await message.bot.send_poll(
            chat_id=settings.content_channel_id,
            question=POLL_QUESTION,
            options=POLL_OPTIONS,
            is_anonymous=True,
            allows_multiple_answers=False,
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.exception("Could not send poll")
        await message.answer(f"No pude enviar la encuesta: {exc}")
        return

    await message.answer("Encuesta enviada al canal.")


@router.message(Command("users"))
async def users(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        count_response = (
            supabase.table("telegram_users")
            .select("telegram_id", count="exact")
            .execute()
        )
        latest_response = (
            supabase.table("telegram_users")
            .select("*")
            .order("registered_at", desc=True)
            .limit(10)
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not fetch users")
        await message.answer(f"No pude consultar usuarios: {exc}")
        return

    total = count_response.count or 0
    latest = latest_response.data or []
    lines = [f"Usuarios registrados: {total}", "", "Últimos 10:"]
    lines.extend(format_user(row) for row in latest)
    if not latest:
        lines.append("Sin usuarios registrados todavía.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("set_expiry"))
async def set_expiry(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Uso: /set_expiry <telegram_id> <YYYY-MM-DD>")
        return

    try:
        telegram_id = int(parts[1])
        expiry = datetime.strptime(parts[2], DATE_FORMAT).date().isoformat()
    except ValueError:
        await message.answer("Formato inválido. Usa: /set_expiry <telegram_id> <YYYY-MM-DD>")
        return

    try:
        existing = get_registered_user(supabase, telegram_id)
        if not existing:
            await message.answer("Usuario no encontrado en telegram_users.")
            return
        (
            supabase.table("telegram_users")
            .update({"expiry_date": expiry})
            .eq("telegram_id", telegram_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not set expiry for telegram_id=%s", telegram_id)
        await message.answer(f"No pude actualizar la fecha: {exc}")
        return

    await message.answer(f"Vencimiento actualizado: {telegram_id} -> {expiry}")


@router.message(Command("expired"))
async def expired(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        response = (
            supabase.table("telegram_users")
            .select("*")
            .lt("expiry_date", today_iso())
            .order("expiry_date")
            .limit(100)
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not fetch expired users")
        await message.answer(f"No pude consultar expirados: {exc}")
        return

    rows = response.data or []
    lines = [f"Usuarios expirados al {today_iso()}: {len(rows)}"]
    lines.extend(format_user(row) for row in rows)
    if not rows:
        lines.append("No hay usuarios expirados.")
    await send_long_message(message, "\n".join(lines))


@router.poll_answer()
async def poll_answer(poll_answer_update: PollAnswer, supabase: Client) -> None:
    try:
        upsert_poll_user(supabase, poll_answer_update)
    except Exception:
        logger.exception("Could not process poll answer for user_id=%s", poll_answer_update.user.id)


@router.error()
async def handle_error(event: ErrorEvent) -> None:
    logger.exception("Unhandled update error: %s", event.exception)


async def notify_expiring_today(bot: Bot, supabase: Client, settings: Settings) -> None:
    today = today_iso()
    try:
        response = (
            supabase.table("telegram_users")
            .select("*")
            .eq("expiry_date", today)
            .order("registered_at", desc=True)
            .execute()
        )
        rows = response.data or []
        if not rows:
            text = f"No hay usuarios venciendo hoy ({today})."
        else:
            lines = [f"Usuarios venciendo hoy ({today}): {len(rows)}"]
            lines.extend(format_user(row) for row in rows)
            text = "\n".join(lines)
        await bot.send_message(settings.admin_chat_id, text[:3900])
        logger.info("Sent daily expiry notification with %s users", len(rows))
    except Exception:
        logger.exception("Could not send daily expiry notification")


async def main() -> None:
    configure_logging()
    settings = load_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)

    bot = Bot(settings.bot_token)

    dp = Dispatcher()
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    scheduler.add_job(
        notify_expiring_today,
        CronTrigger(hour=9, minute=0, timezone=APP_TIMEZONE),
        args=[bot, supabase, settings],
        id="daily_expiry_notification",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()

    logger.info("Bot started with long polling")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            settings=settings,
            supabase=supabase,
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
