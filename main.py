import asyncio
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from supabase import Client, create_client
import uvicorn


BASE_DIR = Path(__file__).resolve().parent
CTA_MESSAGE = "¿Quieres ver más contenido como este? 🔥"
CTA_BUTTON_TEXT = "QUIERO MÁS CONTENIDO 🔥"
CTA_CALLBACK_DATA = "want_more_content"
CTA_NOTES = "Clicked QUIERO MÁS CONTENIDO button"
DATE_FORMAT = "%Y-%m-%d"
APP_TIMEZONE = ZoneInfo("America/Mexico_City")
SCHEMA_MIGRATION_SQL = """
alter table public.telegram_users add column if not exists joined_at timestamptz;
alter table public.telegram_users add column if not exists last_payment_at timestamptz;
alter table public.telegram_users add column if not exists invite_link text;
alter table public.telegram_users add column if not exists removed_at timestamptz;
alter table public.telegram_users add column if not exists status text;
alter table public.telegram_users add column if not exists notes text;
alter table public.telegram_users add column if not exists expiry_date date;
update public.telegram_users
set joined_at = coalesce(joined_at, registered_at, now())
where joined_at is null;
update public.telegram_users
set expiry_date = (joined_at + interval '30 days')::date
where expiry_date is null and joined_at is not null;
""".strip()

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
    admin_password: str


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
        admin_password=required_env("ADMIN_PASSWORD"),
    )


def is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_user_ids)


async def reject_non_admin(message: Message) -> None:
    await message.answer("No autorizado.")


def today_iso() -> str:
    return datetime.now(APP_TIMEZONE).date().isoformat()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), DATE_FORMAT).date()
        except ValueError:
            return None


def days_remaining(expiry_date: Any) -> int | None:
    parsed = parse_iso_date(expiry_date)
    if not parsed:
        return None
    return (parsed - datetime.now(APP_TIMEZONE).date()).days


async def send_long_message(message: Message, text: str) -> None:
    max_length = 3900
    for index in range(0, len(text), max_length):
        await message.answer(text[index : index + max_length])


def format_user(row: dict[str, Any]) -> str:
    telegram_id = row.get("telegram_id", "N/A")
    username = row.get("username")
    first_name = row.get("first_name") or ""
    last_name = row.get("last_name") or ""
    status = row.get("status") or "-"
    expiry = row.get("expiry_date") or "-"
    handle = f"@{username}" if username else "(sin username)"
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or "(sin nombre)"
    return f"{telegram_id} | {handle} | {full_name} | status: {status} | vence: {expiry}"


def get_registered_user(supabase: Client, telegram_id: int) -> dict[str, Any] | None:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def run_schema_migration(supabase: Client) -> None:
    supabase.rpc("exec_sql", {"sql": SCHEMA_MIGRATION_SQL}).execute()


def list_dashboard_users(supabase: Client, user_filter: str) -> list[dict[str, Any]]:
    query = supabase.table("telegram_users").select("*")
    if user_filter == "active":
        query = query.eq("status", "active")
    elif user_filter == "expiring_7":
        today = today_iso()
        soon = (datetime.now(APP_TIMEZONE).date() + timedelta(days=7)).isoformat()
        query = query.gte("expiry_date", today).lte("expiry_date", soon)
    elif user_filter == "expired":
        query = query.lt("expiry_date", today_iso())
    elif user_filter == "no_expiry":
        query = query.is_("expiry_date", "null")

    response = query.order("registered_at", desc=True).limit(500).execute()
    rows = response.data or []
    for row in rows:
        row["days_remaining"] = days_remaining(row.get("expiry_date"))
    return rows


def renew_user_from_today(supabase: Client, telegram_id: int) -> str:
    expiry = (datetime.now(APP_TIMEZONE).date() + timedelta(days=30)).isoformat()
    (
        supabase.table("telegram_users")
        .update(
            {
                "expiry_date": expiry,
                "status": "active",
                "last_payment_at": now_utc_iso(),
                "notes": "Renewed +30 days from today",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return expiry


def renew_user_from_current_expiry(supabase: Client, telegram_id: int) -> str:
    user = get_registered_user(supabase, telegram_id)
    if not user:
        raise ValueError("User not found")
    current_expiry = parse_iso_date(user.get("expiry_date"))
    if user.get("status") != "active" or not current_expiry or current_expiry < datetime.now(APP_TIMEZONE).date():
        raise ValueError("User is not active with a future expiry_date")

    expiry = (current_expiry + timedelta(days=30)).isoformat()
    (
        supabase.table("telegram_users")
        .update(
            {
                "expiry_date": expiry,
                "status": "active",
                "last_payment_at": now_utc_iso(),
                "notes": "Renewed +30 days from current expiry_date",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return expiry


def mark_user_paid(supabase: Client, telegram_id: int) -> None:
    (
        supabase.table("telegram_users")
        .update(
            {
                "status": "active",
                "last_payment_at": now_utc_iso(),
                "notes": "Marked paid from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def mark_user_inactive(supabase: Client, telegram_id: int, notes: str = "Marked inactive from dashboard") -> None:
    (
        supabase.table("telegram_users")
        .update({"status": "inactive", "notes": notes})
        .eq("telegram_id", telegram_id)
        .execute()
    )


def update_user_notes(supabase: Client, telegram_id: int, notes: str) -> None:
    (
        supabase.table("telegram_users")
        .update({"notes": notes})
        .eq("telegram_id", telegram_id)
        .execute()
    )


def update_user_invite_link(supabase: Client, telegram_id: int, invite_link: str) -> None:
    (
        supabase.table("telegram_users")
        .update({"invite_link": invite_link, "notes": "Generated one-use invite link from dashboard"})
        .eq("telegram_id", telegram_id)
        .execute()
    )


def mark_user_removed(supabase: Client, telegram_id: int) -> None:
    (
        supabase.table("telegram_users")
        .update(
            {
                "status": "inactive",
                "removed_at": now_utc_iso(),
                "notes": "Removed from channel from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def build_cta_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CTA_BUTTON_TEXT,
                    callback_data=CTA_CALLBACK_DATA,
                )
            ]
        ]
    )


def upsert_cta_user(supabase: Client, callback_query: CallbackQuery) -> None:
    if not callback_query.from_user:
        raise ValueError("Callback query has no from_user")

    user = callback_query.from_user
    existing = get_registered_user(supabase, user.id)
    joined_at = now_utc_iso()
    expiry_date = (datetime.now(APP_TIMEZONE).date() + timedelta(days=30)).isoformat()
    payload = {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": "active",
        "notes": CTA_NOTES,
    }

    if existing:
        if not existing.get("joined_at"):
            payload["joined_at"] = joined_at
        if not existing.get("expiry_date"):
            payload["expiry_date"] = expiry_date
        (
            supabase.table("telegram_users")
            .update(payload)
            .eq("telegram_id", user.id)
            .execute()
        )
        logger.info("Updated CTA user telegram_id=%s", user.id)
        return

    payload["registered_at"] = joined_at
    payload["joined_at"] = joined_at
    payload["expiry_date"] = expiry_date
    supabase.table("telegram_users").insert(payload).execute()
    logger.info("Registered CTA user telegram_id=%s", user.id)


@router.message(Command("send_poll"))
async def send_poll(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await message.bot.send_message(
            chat_id=settings.content_channel_id,
            text=CTA_MESSAGE,
            reply_markup=build_cta_keyboard(),
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.exception("Could not send CTA message")
        await message.answer(f"No pude enviar el mensaje: {exc}")
        return

    await message.answer("Mensaje enviado al canal.")


@router.message(Command("users"))
async def users(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        count_response = (
            supabase.table("telegram_users")
            .select("*", count="exact")
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


@router.message(Command("sync_schema"))
async def sync_schema(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await asyncio.to_thread(run_schema_migration, supabase)
        await message.answer("Schema sincronizado correctamente.")
    except Exception as exc:
        logger.exception("Could not sync schema")
        await send_long_message(
            message,
            "No pude ejecutar la migración automáticamente. "
            "Crea un RPC seguro llamado exec_sql o ejecuta este SQL en Supabase:\n\n"
            f"```sql\n{SCHEMA_MIGRATION_SQL}\n```\n\n"
            f"Error: {exc}",
        )


@router.callback_query(F.data == CTA_CALLBACK_DATA)
async def want_more_content(callback_query: CallbackQuery, supabase: Client) -> None:
    try:
        upsert_cta_user(supabase, callback_query)
        await callback_query.answer("Listo 🔥")
    except Exception:
        user_id = callback_query.from_user.id if callback_query.from_user else "unknown"
        logger.exception("Could not process CTA callback for user_id=%s", user_id)
        await callback_query.answer("Intenta de nuevo.", show_alert=False)


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


async def run_telegram_bot(bot: Bot, supabase: Client, settings: Settings) -> None:
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

    logger.info("Starting Telegram bot polling")
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


def dashboard_redirect(
    user_filter: str = "all",
    message: str | None = None,
    error: str | None = None,
    invite_link: str | None = None,
) -> RedirectResponse:
    params = {"filter": user_filter}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    if invite_link:
        params["invite_link"] = invite_link
    return RedirectResponse(url=f"/dashboard?{urlencode(params)}", status_code=303)


def create_web_app(settings: Settings, supabase: Client, bot: Bot) -> FastAPI:
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app = FastAPI(title="Telegram Renewal Admin")
    app.add_middleware(
        SessionMiddleware,
        secret_key=f"{settings.bot_token}:{settings.admin_password}",
        same_site="lax",
        https_only=bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_NAME")),
    )

    def is_logged_in(request: Request) -> bool:
        return bool(request.session.get("admin_authenticated"))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> RedirectResponse:
        if is_logged_in(request):
            return RedirectResponse(url="/dashboard", status_code=303)
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        if is_logged_in(request):
            return RedirectResponse(url="/dashboard", status_code=303)
        return templates.TemplateResponse("login.html", {"request": request, "error": None})

    @app.post("/login")
    async def login(request: Request, password: str = Form(...)) -> RedirectResponse | HTMLResponse:
        if secrets.compare_digest(password, settings.admin_password):
            request.session["admin_authenticated"] = True
            return RedirectResponse(url="/dashboard?message=Login%20successful", status_code=303)

        logger.warning("Failed dashboard login")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid password"},
            status_code=401,
        )

    @app.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        filter: str = "all",
        message: str | None = None,
        error: str | None = None,
        invite_link: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)

        safe_filter = filter if filter in {"all", "active", "expiring_7", "expired", "no_expiry"} else "all"
        try:
            rows = await asyncio.to_thread(list_dashboard_users, supabase, safe_filter)
        except Exception as exc:
            logger.exception("Could not load dashboard users")
            rows = []
            error = f"Could not load users: {exc}"

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users": rows,
                "active_filter": safe_filter,
                "message": message,
                "error": error,
                "invite_link": invite_link,
                "today": today_iso(),
            },
        )

    @app.post("/dashboard/users/{telegram_id}/renew/today")
    async def dashboard_renew_today(telegram_id: int, request: Request, filter: str = "all") -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            expiry = await asyncio.to_thread(renew_user_from_today, supabase, telegram_id)
            return dashboard_redirect(filter, message=f"Renewed from today. New expiry: {expiry} for {telegram_id}.")
        except Exception as exc:
            logger.exception("Could not renew from today for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not renew user: {exc}")

    @app.post("/dashboard/users/{telegram_id}/renew/current-expiry")
    async def dashboard_renew_current_expiry(
        telegram_id: int,
        request: Request,
        filter: str = "all",
    ) -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            expiry = await asyncio.to_thread(renew_user_from_current_expiry, supabase, telegram_id)
            return dashboard_redirect(
                filter,
                message=f"Renewed from current expiry_date. New expiry: {expiry} for {telegram_id}.",
            )
        except Exception as exc:
            logger.exception("Could not renew from current expiry for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not renew from current expiry_date: {exc}")

    @app.post("/dashboard/users/{telegram_id}/paid")
    async def dashboard_mark_paid(telegram_id: int, request: Request, filter: str = "all") -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(mark_user_paid, supabase, telegram_id)
            return dashboard_redirect(filter, message=f"User {telegram_id} marked paid.")
        except Exception as exc:
            logger.exception("Could not mark paid telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not mark paid: {exc}")

    @app.post("/dashboard/users/{telegram_id}/inactive")
    async def dashboard_mark_inactive(telegram_id: int, request: Request, filter: str = "all") -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(mark_user_inactive, supabase, telegram_id)
            return dashboard_redirect(filter, message=f"User {telegram_id} marked inactive.")
        except Exception as exc:
            logger.exception("Could not mark inactive telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not mark inactive: {exc}")

    @app.post("/dashboard/users/{telegram_id}/invite")
    async def dashboard_invite(telegram_id: int, request: Request, filter: str = "all") -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=settings.content_channel_id,
                name=f"dashboard-{telegram_id}-{int(datetime.now(timezone.utc).timestamp())}",
                member_limit=1,
            )
            await asyncio.to_thread(update_user_invite_link, supabase, telegram_id, invite.invite_link)
            return dashboard_redirect(
                filter,
                message=f"One-use invite link generated for {telegram_id}.",
                invite_link=invite.invite_link,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.exception("Could not create invite link for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not create invite link: {exc}")
        except Exception as exc:
            logger.exception("Unexpected invite link error for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not create invite link: {exc}")

    @app.get("/dashboard/users/{telegram_id}/remove", response_class=HTMLResponse)
    async def dashboard_remove_confirm(
        telegram_id: int,
        request: Request,
        filter: str = "all",
    ) -> HTMLResponse | RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
            if not user:
                return dashboard_redirect(filter, error=f"User {telegram_id} not found.")
            return templates.TemplateResponse(
                "confirm_remove.html",
                {
                    "request": request,
                    "user": user,
                    "active_filter": filter,
                },
            )
        except Exception as exc:
            logger.exception("Could not load remove confirmation for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not load confirmation: {exc}")

    @app.post("/dashboard/users/{telegram_id}/remove/confirm")
    async def dashboard_remove_confirmed(telegram_id: int, request: Request, filter: str = "all") -> RedirectResponse:
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await bot.ban_chat_member(chat_id=settings.content_channel_id, user_id=telegram_id)
            await bot.unban_chat_member(
                chat_id=settings.content_channel_id,
                user_id=telegram_id,
                only_if_banned=True,
            )
            await asyncio.to_thread(mark_user_removed, supabase, telegram_id)
            return dashboard_redirect(filter, message=f"User {telegram_id} removed from channel.")
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.exception("Could not remove telegram_id=%s from channel", telegram_id)
            return dashboard_redirect(filter, error=f"Could not remove user from channel: {exc}")
        except Exception as exc:
            logger.exception("Unexpected remove error for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, error=f"Could not remove user from channel: {exc}")

    return app


async def run_web_server(app: FastAPI) -> None:
    PORT = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting web dashboard on port {PORT}")
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()


async def run_startup_migration(supabase: Client) -> None:
    try:
        await asyncio.to_thread(run_schema_migration, supabase)
        logger.info("Schema migration completed")
    except Exception:
        logger.warning("Schema migration skipped or failed; use /sync_schema or run README SQL", exc_info=True)


async def main() -> None:
    configure_logging()
    settings = load_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    bot = Bot(settings.bot_token)
    app = create_web_app(settings, supabase, bot)

    asyncio.create_task(run_startup_migration(supabase), name="schema-migration")
    bot_task = asyncio.create_task(run_telegram_bot(bot, supabase, settings), name="telegram-bot")
    web_task = asyncio.create_task(run_web_server(app), name="web-server")
    try:
        await asyncio.gather(bot_task, web_task)
    finally:
        for task in (bot_task, web_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(bot_task, web_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
