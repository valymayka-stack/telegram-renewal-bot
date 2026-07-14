import asyncio
import logging
import os
import secrets
import shlex
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
CONFIRM_SUBSCRIPTION_MESSAGE = (
    "Bebes, para llevar mejor control, den click aquí para confirmar su suscripción 💕  \n"
    "Es importante dar click, si no, pueden llegar a ser removidos del canal."
)
CONFIRM_SUBSCRIPTION_BUTTON_TEXT = "CONFIRMAR SUSCRIPCIÓN ✅"
CONFIRM_SUBSCRIPTION_CALLBACK_DATA = "confirm_subscription_v1"
CONFIRMATION_CAMPAIGN = "subscription_confirmation_v1"
CONFIRMATION_SOURCE = "confirm_subscription_button"
INVITE_LINK_LIFETIME = timedelta(hours=24)
HIDDEN_APPROVAL_CHANNEL_CODES = {
    "regalo_renovacion",
    "regalo_marcador_exacto",
    "mexico_ecuador",
    "regalo_partido",
    "nuevos_sus",
    "blue_love",
}
PREDICTION_MEX_INGLATERRA_GAME_CODE = "mex_inglaterra"
PREDICTION_MEX_INGLATERRA_SCORES = [
    "México 1-0 Inglaterra",
    "México 2-0 Inglaterra",
    "México 2-1 Inglaterra",
    "México 3-0 Inglaterra",
    "México 3-1 Inglaterra",
    "México 0-0 Inglaterra",
    "México 1-1 Inglaterra",
    "México 2-2 Inglaterra",
    "México 0-1 Inglaterra",
    "México 1-2 Inglaterra",
    "Se define en penales",
]
PREDICTION_GAMES = {
    PREDICTION_MEX_INGLATERRA_GAME_CODE: PREDICTION_MEX_INGLATERRA_SCORES,
}
PREDICTION_BUTTON_LABELS = {
    PREDICTION_MEX_INGLATERRA_GAME_CODE: [
        "🇲🇽 1-0 🏴",
        "🇲🇽 2-0 🏴",
        "🇲🇽 2-1 🏴",
        "🇲🇽 3-0 🏴",
        "🇲🇽 3-1 🏴",
        "🇲🇽 0-0 🏴",
        "🇲🇽 1-1 🏴",
        "🇲🇽 2-2 🏴",
        "🇲🇽 0-1 🏴",
        "🇲🇽 1-2 🏴",
        "🥅 Se define en penales",
    ],
}
PREDICTION_MEX_INGLATERRA_TEXT = (
    "⚽ Pronóstico México vs Inglaterra\n\n"
    "Elige tu marcador. Solo cuenta un pronóstico por usuario; si cambias de opción, se actualiza tu elección."
)
RAFFLE_BUTTON_TEXT = "🎟️ QUIERO MIS BOLETOS"
RAFFLE_PRIZE_CHANNEL_CODE = "premio_sorteo"
GRUPO_CHANNEL_KEY = "grupo"
GRUPO_CHANNEL_LABEL = "Grupo"
LADY_CHANNEL_KEY = "lady_in_red"
LADY_CHANNEL_LABEL = "Lady in Red"
GRUPO_BUNDLED_CHANNEL_KEYS = {"nuevos_sus", "blue_love"}
CART_CATEGORIES = {"eterea": "Etérea", "casera": "Casera"}
CART_DISCOUNT_MIN_SETS = 3
CART_DISCOUNT_RATE = 0.10
CART_PAYMENT_INFO = (
    "💳 Cuenta CLABE (BBVA)\n"
    "Silvia Montalvo\n"
    "012700015287595938\n\n"
    "🌎 ¿Eres extranjero?\n"
    "Puedes hacer tu depósito directo por Felix, Xoom o Remitly.\n"
    "Datos adicionales que te pueden pedir:\n"
    "Estado: Guanajuato\n"
    "Teléfono: No aplica\n"
    "Correo: No aplica"
)
DATE_FORMAT = "%Y-%m-%d"
APP_TIMEZONE = ZoneInfo("America/Mexico_City")
SCHEMA_MIGRATION_SQL = """
alter table public.telegram_users add column if not exists joined_at timestamptz;
alter table public.telegram_users add column if not exists membership_start_date date;
alter table public.telegram_users add column if not exists payment_status text default 'unpaid';
alter table public.telegram_users add column if not exists pending_payment_file_id text;
alter table public.telegram_users add column if not exists pending_payment_file_type text;
alter table public.telegram_users add column if not exists pending_payment_at timestamptz;
alter table public.telegram_users add column if not exists approved_by_admin_id bigint;
alter table public.telegram_users add column if not exists approved_at timestamptz;
alter table public.telegram_users add column if not exists rejected_at timestamptz;
alter table public.telegram_users add column if not exists needs_new_receipt_at timestamptz;
alter table public.telegram_users add column if not exists last_payment_at timestamptz;
alter table public.telegram_users add column if not exists invite_link text;
alter table public.telegram_users add column if not exists invite_link_created_at timestamptz;
alter table public.telegram_users add column if not exists invite_link_name text;
alter table public.telegram_users add column if not exists invite_link_revoked boolean default false;
alter table public.telegram_users add column if not exists invite_link_used boolean default false;
alter table public.telegram_users add column if not exists revoked_at timestamptz;
alter table public.telegram_users add column if not exists joined_channel_at timestamptz;
alter table public.telegram_users add column if not exists left_channel_at timestamptz;
alter table public.telegram_users add column if not exists last_seen_at timestamptz;
alter table public.telegram_users add column if not exists renewal_notice_7d_sent_at timestamptz;
alter table public.telegram_users add column if not exists renewal_notice_3d_sent_at timestamptz;
alter table public.telegram_users add column if not exists renewal_notice_1d_sent_at timestamptz;
alter table public.telegram_users add column if not exists removed_at timestamptz;
alter table public.telegram_users add column if not exists removal_reason text;
alter table public.telegram_users add column if not exists confirmed_subscription boolean default false;
alter table public.telegram_users add column if not exists confirmed_at timestamptz;
alter table public.telegram_users add column if not exists confirmation_campaign text;
alter table public.telegram_users add column if not exists source text;
alter table public.telegram_users add column if not exists status text;
alter table public.telegram_users add column if not exists notes text;
alter table public.telegram_users add column if not exists expiry_date date;
alter table public.telegram_users alter column payment_status set default 'unpaid';
alter table public.telegram_users alter column confirmed_subscription set default false;
alter table public.telegram_users alter column invite_link_revoked set default false;
alter table public.telegram_users alter column invite_link_used set default false;
update public.telegram_users
set joined_at = coalesce(joined_at, registered_at, now())
where joined_at is null;
update public.telegram_users
set payment_status = coalesce(payment_status, 'unpaid')
where payment_status is null;
update public.telegram_users
set confirmed_subscription = coalesce(confirmed_subscription, false)
where confirmed_subscription is null;
update public.telegram_users
set invite_link_revoked = coalesce(invite_link_revoked, false)
where invite_link_revoked is null;
update public.telegram_users
set invite_link_used = coalesce(invite_link_used, false)
where invite_link_used is null;
update public.telegram_users
set expiry_date = (joined_at + interval '30 days')::date
where expiry_date is null and membership_start_date is null and joined_at is not null;
update public.telegram_users
set expiry_date = membership_start_date + 30
where expiry_date is null and membership_start_date is not null;
create table if not exists public.payment_history (
  id bigserial primary key,
  telegram_id bigint not null,
  username text,
  first_name text,
  admin_id bigint,
  action text default 'approved',
  payment_status text default 'paid',
  receipt_file_id text,
  receipt_file_type text,
  invite_link text,
  membership_start_date date,
  expiry_date date,
  verified boolean default true,
  notes text,
  created_at timestamptz default now()
);
alter table public.payment_history add column if not exists receipt_file_type text;
alter table public.payment_history add column if not exists membership_start_date date;
alter table public.payment_history add column if not exists expiry_date date;
alter table public.payment_history add column if not exists verified boolean default true;
alter table public.payment_history alter column action set default 'approved';
alter table public.payment_history alter column payment_status set default 'paid';
alter table public.payment_history alter column verified set default true;
create index if not exists payment_history_telegram_id_idx
  on public.payment_history (telegram_id);
create index if not exists payment_history_created_at_idx
  on public.payment_history (created_at desc);
create index if not exists payment_history_payment_status_idx
  on public.payment_history (payment_status);
create table if not exists public.access_channels (
  channel_key text primary key,
  label text not null,
  chat_id text not null,
  active boolean default true,
  is_active boolean default true,
  expires_membership boolean default false,
  has_expiry boolean default false,
  created_at timestamptz default now()
);
alter table public.access_channels add column if not exists label text;
alter table public.access_channels add column if not exists chat_id text;
alter table public.access_channels add column if not exists active boolean default true;
alter table public.access_channels add column if not exists is_active boolean default true;
alter table public.access_channels add column if not exists expires_membership boolean default false;
alter table public.access_channels add column if not exists has_expiry boolean default false;
alter table public.access_channels add column if not exists created_at timestamptz default now();
create table if not exists public.user_channel_access (
  id bigserial primary key,
  telegram_id bigint not null,
  channel_key text not null,
  channel_label text,
  chat_id text,
  invite_link text,
  invite_link_name text,
  invite_link_created_at timestamptz,
  invite_link_revoked boolean default false,
  invite_link_used boolean default false,
  access_status text default 'active',
  granted_at timestamptz,
  expires_at date,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (telegram_id, channel_key)
);
alter table public.user_channel_access add column if not exists telegram_id bigint;
alter table public.user_channel_access add column if not exists channel_key text;
alter table public.user_channel_access add column if not exists channel_label text;
alter table public.user_channel_access add column if not exists chat_id text;
alter table public.user_channel_access add column if not exists invite_link text;
alter table public.user_channel_access add column if not exists invite_link_name text;
alter table public.user_channel_access add column if not exists invite_link_created_at timestamptz;
alter table public.user_channel_access add column if not exists invite_link_revoked boolean default false;
alter table public.user_channel_access add column if not exists invite_link_used boolean default false;
alter table public.user_channel_access add column if not exists status text default 'active';
alter table public.user_channel_access add column if not exists access_status text default 'active';
alter table public.user_channel_access add column if not exists granted_at timestamptz;
alter table public.user_channel_access add column if not exists expires_at date;
alter table public.user_channel_access add column if not exists created_at timestamptz default now();
alter table public.user_channel_access add column if not exists updated_at timestamptz default now();
create index if not exists user_channel_access_telegram_id_idx
  on public.user_channel_access (telegram_id);
create index if not exists user_channel_access_channel_key_idx
  on public.user_channel_access (channel_key);
alter table public.user_channel_access add column if not exists joined_channel_at timestamptz;
create table if not exists public.manual_invite_links (
  id bigserial primary key,
  channel_code text,
  telegram_chat_id text,
  invite_link text,
  invite_link_name text,
  created_by_admin_id bigint,
  created_at timestamptz default now(),
  expires_at timestamptz,
  used_by_telegram_id bigint,
  used_at timestamptz,
  revoked boolean default false,
  revoked_at timestamptz,
  notes text
);
create index if not exists manual_invite_links_invite_link_idx
  on public.manual_invite_links (invite_link);
create index if not exists manual_invite_links_channel_code_idx
  on public.manual_invite_links (channel_code);
create table if not exists public.renewal_message_recipients (
  id bigserial primary key,
  telegram_id bigint not null,
  username text,
  first_name text,
  sent_at timestamptz default now()
);
create index if not exists renewal_message_recipients_sent_at_idx
  on public.renewal_message_recipients (sent_at desc);
create index if not exists renewal_message_recipients_telegram_id_idx
  on public.renewal_message_recipients (telegram_id);
create table if not exists public.prediction_votes (
  id bigserial primary key,
  game_code text not null,
  telegram_id bigint not null,
  username text,
  first_name text,
  selected_score text not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (game_code, telegram_id)
);
create index if not exists prediction_votes_game_code_idx
  on public.prediction_votes (game_code);
create index if not exists prediction_votes_selected_score_idx
  on public.prediction_votes (game_code, selected_score);
create index if not exists prediction_votes_updated_at_idx
  on public.prediction_votes (updated_at desc);
create unique index if not exists prediction_votes_game_telegram_unique_idx
  on public.prediction_votes (game_code, telegram_id);
create table if not exists public.bot_state (
  key text primary key,
  value text,
  updated_at timestamptz default now()
);
alter table public.access_channels add column if not exists price numeric;
alter table public.access_channels add column if not exists category text;
create table if not exists public.cart_items (
  id bigserial primary key,
  telegram_id bigint not null,
  channel_key text not null,
  added_at timestamptz default now(),
  unique (telegram_id, channel_key)
);
create index if not exists cart_items_telegram_id_idx on public.cart_items (telegram_id);
alter table public.access_channels add column if not exists photo_file_id text;
alter table public.access_channels add column if not exists description text;
alter table public.access_channels add column if not exists featured boolean default false;
create table if not exists public.cart_reminders (
  telegram_id bigint primary key,
  reminded_at timestamptz default now()
);
""".strip()

logger = logging.getLogger(__name__)
router = Router()
PAYMENT_CHANNEL_SELECTIONS: dict[tuple[int, int, int], set[str]] = {}
PENDING_PAYMENT_ADMIN_MESSAGES: dict[tuple[int, int], int] = {}
RAFFLE_ADMIN_MESSAGES: dict[tuple[int, int], int] = {}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    supabase_url: str
    supabase_service_role_key: str
    admin_chat_id: int
    content_channel_id: int | str
    admin_user_ids: set[int]
    admin_password: str
    auto_remove_expired: bool
    renewal_notice_days: tuple[int, ...]


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


def parse_stored_chat_id(value: Any) -> int | str:
    return parse_chat_id(str(value))


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


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_notice_days(value: str | None) -> tuple[int, ...]:
    if not value:
        return (7, 3, 1)
    days: list[int] = []
    for raw_day in value.split(","):
        raw_day = raw_day.strip()
        if not raw_day:
            continue
        days.append(int(raw_day))
    return tuple(days or [7, 3, 1])


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
        auto_remove_expired=parse_bool(os.getenv("AUTO_REMOVE_EXPIRED"), default=False),
        renewal_notice_days=parse_notice_days(os.getenv("RENEWAL_NOTICE_DAYS")),
    )


def is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_user_ids)


def is_admin_id(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id and user_id in settings.admin_user_ids)


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


def format_local_datetime(value: Any) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(APP_TIMEZONE).strftime("%d/%m/%Y %H:%M")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def membership_start_for_user(row: dict[str, Any]) -> date:
    membership_start = parse_iso_date(row.get("membership_start_date"))
    if membership_start:
        return membership_start
    joined_at = parse_iso_date(row.get("joined_at"))
    if joined_at:
        return joined_at
    return datetime.now(APP_TIMEZONE).date()


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


def format_user_record(row: dict[str, Any]) -> str:
    if not row:
        return "Usuario no encontrado."
    lines = []
    for key in sorted(row.keys()):
        lines.append(f"{key}: {row.get(key)}")
    return "\n".join(lines)


def format_payment_history_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Sin historial de pagos."
    lines: list[str] = []
    for row in rows:
        created_at = row.get("created_at_display") or format_local_datetime(row.get("created_at"))
        lines.append(
            f"{created_at} | {row.get('action') or '-'} | "
            f"{row.get('payment_status') or '-'} | admin: {row.get('admin_id') or '-'} | "
            f"start: {row.get('membership_start_date') or '-'} | "
            f"expiry: {row.get('expiry_date') or '-'} | "
            f"notes: {row.get('notes') or '-'}"
        )
    return "\n".join(lines)


def get_registered_user(supabase: Client, telegram_id: int) -> dict[str, Any] | None:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def fetch_users_summary(supabase: Client) -> tuple[int, list[dict[str, Any]]]:
    count_response = supabase.table("telegram_users").select("*", count="exact").execute()
    latest_response = (
        supabase.table("telegram_users")
        .select("*")
        .order("registered_at", desc=True)
        .limit(10)
        .execute()
    )
    return count_response.count or 0, latest_response.data or []


def fetch_unconfirmed_users(supabase: Client, limit: int = 500) -> list[dict[str, Any]]:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .order("registered_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [row for row in (response.data or []) if row.get("confirmed_subscription") is not True]


def fetch_pending_payment_users(supabase: Client, limit: int = 100) -> list[dict[str, Any]]:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("payment_status", "pending_review")
        .order("pending_payment_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def set_user_expiry_date(supabase: Client, telegram_id: int, expiry: str) -> bool:
    if not get_registered_user(supabase, telegram_id):
        return False
    (
        supabase.table("telegram_users")
        .update({"expiry_date": expiry})
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return True


def fetch_users_for_notice_day(supabase: Client, target: str, column: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("status", "active")
        .eq("expiry_date", target)
        .is_(column, "null")
        .execute()
    )
    return response.data or []


def mark_notice_sent(supabase: Client, column: str, sent_ids: list[int]) -> None:
    (
        supabase.table("telegram_users")
        .update({column: now_utc_iso()})
        .in_("telegram_id", sent_ids)
        .execute()
    )


def get_user_by_invite_link_name(supabase: Client, invite_link_name: str) -> dict[str, Any] | None:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("invite_link_name", invite_link_name)
        .eq("invite_link_revoked", False)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def insert_payment_history(
    supabase: Client,
    telegram_id: int,
    action: str,
    payment_status: str | None = None,
    admin_id: int | None = None,
    receipt_file_id: str | None = None,
    receipt_file_type: str | None = None,
    invite_link: str | None = None,
    membership_start_date: str | None = None,
    expiry_date: str | None = None,
    verified: bool = True,
    notes: str | None = None,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    try:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "payment_status": payment_status,
            "admin_id": admin_id,
            "action": action,
            "receipt_file_id": receipt_file_id,
            "receipt_file_type": receipt_file_type,
            "invite_link": invite_link,
            "membership_start_date": membership_start_date,
            "expiry_date": expiry_date,
            "verified": verified,
            "notes": notes,
        }
        supabase.table("payment_history").insert(payload).execute()
    except Exception:
        logger.warning(
            "Could not insert payment history action=%s telegram_id=%s",
            action,
            telegram_id,
            exc_info=True,
        )


def get_payment_history(supabase: Client, telegram_id: int, limit: int | None = 10) -> list[dict[str, Any]]:
    query = (
        supabase.table("payment_history")
        .select("*")
        .eq("telegram_id", telegram_id)
        .eq("action", "approved")
        .eq("payment_status", "paid")
        .order("created_at", desc=True)
    )
    if limit is not None:
        query = query.limit(limit)
    response = query.execute()
    rows = response.data or []
    for row in rows:
        row["created_at_display"] = format_local_datetime(row.get("created_at"))
        row["receipt_file_url"] = payment_receipt_file_url(row.get("receipt_file_id"))
    return rows


def fetch_all_approved_payment_history(supabase: Client) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    while True:
        response = (
            supabase.table("payment_history")
            .select("telegram_id, invite_link, created_at")
            .eq("action", "approved")
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def parse_channel_labels_from_invite_text(invite_link_text: str) -> list[str]:
    labels: list[str] = []
    for line in (invite_link_text or "").split("\n"):
        line = line.strip()
        if ":" in line:
            label = line.split(":", 1)[0].strip()
            if label:
                labels.append(label)
    return labels


def payment_history_telegram_ids(supabase: Client) -> set[int]:
    response = (
        supabase.table("payment_history")
        .select("telegram_id")
        .eq("action", "approved")
        .eq("payment_status", "paid")
        .limit(5000)
        .execute()
    )
    return {int(row["telegram_id"]) for row in (response.data or []) if row.get("telegram_id") is not None}


def grupo_access_channel(settings: Settings) -> dict[str, Any]:
    return {
        "channel_key": GRUPO_CHANNEL_KEY,
        "label": GRUPO_CHANNEL_LABEL,
        "chat_id": str(settings.content_channel_id),
        "active": True,
        "is_active": True,
        "expires_membership": True,
        "has_expiry": True,
    }


def channel_is_active(channel: dict[str, Any]) -> bool:
    if "is_active" in channel:
        return channel.get("is_active") is True
    if "active" in channel:
        return channel.get("active") is True
    return True


def channel_has_expiry(channel: dict[str, Any]) -> bool:
    if "has_expiry" in channel:
        return channel.get("has_expiry") is True
    if "expires_membership" in channel:
        return channel.get("expires_membership") is True
    return channel_code(channel) == GRUPO_CHANNEL_KEY


def channel_code(channel: dict[str, Any]) -> str:
    return str(channel.get("code") or channel.get("channel_key") or "")


def channel_label(channel: dict[str, Any]) -> str:
    label = channel.get("label") or channel.get("title") or channel.get("name")
    if label:
        return str(label)
    code = channel_code(channel)
    if code == GRUPO_CHANNEL_KEY:
        return GRUPO_CHANNEL_LABEL
    if code == LADY_CHANNEL_KEY:
        return LADY_CHANNEL_LABEL
    return code or "Canal"


def channel_telegram_chat_id(channel: dict[str, Any]) -> Any:
    return channel.get("telegram_chat_id") or channel.get("chat_id")


def channel_price(channel: dict[str, Any]) -> float | None:
    price = channel.get("price")
    if price is None:
        return None
    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def channel_category(channel: dict[str, Any]) -> str | None:
    category = channel.get("category")
    if category in CART_CATEGORIES:
        return category
    return None


def channel_photo_file_id(channel: dict[str, Any]) -> str | None:
    return channel.get("photo_file_id") or None


def channel_description(channel: dict[str, Any]) -> str | None:
    return channel.get("description") or None


CHANNEL_NEW_BADGE_DAYS = 7


def channel_is_featured(channel: dict[str, Any]) -> bool:
    return channel.get("featured") is True


def channel_is_new(channel: dict[str, Any]) -> bool:
    created_at = parse_iso_datetime(channel.get("created_at"))
    if created_at is None:
        return False
    return (datetime.now(timezone.utc) - created_at) <= timedelta(days=CHANNEL_NEW_BADGE_DAYS)


def is_active_member(user_row: dict[str, Any] | None) -> bool:
    if not user_row or user_row.get("status") != "active":
        return False
    expiry = parse_iso_date(user_row.get("expiry_date"))
    if expiry is None:
        return False
    return expiry >= datetime.now(APP_TIMEZONE).date()


def get_access_channels(supabase: Client, settings: Settings) -> list[dict[str, Any]]:
    try:
        response = (
            supabase.table("access_channels")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        channels = [row for row in (response.data or []) if channel_code(row)]
        logger.info("Loaded approval channels: %s", channels)
        return channels
    except Exception:
        logger.warning("Could not fetch approval channels from access_channels", exc_info=True)
        return []


def get_cart_channel_keys(supabase: Client, telegram_id: int) -> set[str]:
    try:
        response = (
            supabase.table("cart_items")
            .select("channel_key")
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return {row["channel_key"] for row in (response.data or [])}
    except Exception:
        logger.warning("Could not fetch cart items telegram_id=%s", telegram_id, exc_info=True)
        return set()


def add_cart_item(supabase: Client, telegram_id: int, channel_key: str) -> None:
    (
        supabase.table("cart_items")
        .upsert(
            {"telegram_id": telegram_id, "channel_key": channel_key},
            on_conflict="telegram_id,channel_key",
        )
        .execute()
    )
    try:
        supabase.table("cart_reminders").delete().eq("telegram_id", telegram_id).execute()
    except Exception:
        logger.warning("Could not reset cart reminder telegram_id=%s", telegram_id, exc_info=True)


def remove_cart_item(supabase: Client, telegram_id: int, channel_key: str) -> None:
    (
        supabase.table("cart_items")
        .delete()
        .eq("telegram_id", telegram_id)
        .eq("channel_key", channel_key)
        .execute()
    )


def cart_channels(channels: list[dict[str, Any]], cart_keys: set[str]) -> list[dict[str, Any]]:
    return [channel for channel in channels if channel_code(channel) in cart_keys]


def cart_total(channels: list[dict[str, Any]]) -> float:
    return sum(channel_price(channel) or 0 for channel in channels)


def cart_discount(channels: list[dict[str, Any]]) -> tuple[float, float, float]:
    """Returns (subtotal, discount_amount, total). 10% off sets (not Grupo) when 3+ sets are in the cart."""
    subtotal = cart_total(channels)
    sets = [c for c in channels if channel_code(c) != GRUPO_CHANNEL_KEY]
    discount = 0.0
    if len(sets) >= CART_DISCOUNT_MIN_SETS:
        discount = cart_total(sets) * CART_DISCOUNT_RATE
    return subtotal, discount, subtotal - discount


def channels_in_category(channels: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    matching = [channel for channel in channels if channel_category(channel) == category]
    matching.sort(key=lambda channel: (not channel_is_featured(channel), -(channel_price(channel) or 0)))
    return matching


def get_stale_cart_telegram_ids(supabase: Client, older_than_minutes: int = 120) -> list[int]:
    try:
        response = supabase.table("cart_items").select("telegram_id, added_at").execute()
        rows = response.data or []
    except Exception:
        logger.warning("Could not fetch cart_items for abandonment check", exc_info=True)
        return []
    latest: dict[int, datetime] = {}
    for row in rows:
        added_at = parse_iso_datetime(row.get("added_at"))
        if added_at is None:
            continue
        telegram_id = row["telegram_id"]
        if telegram_id not in latest or added_at > latest[telegram_id]:
            latest[telegram_id] = added_at
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    return [telegram_id for telegram_id, ts in latest.items() if ts < cutoff]


def already_reminded_telegram_ids(supabase: Client, telegram_ids: list[int]) -> set[int]:
    if not telegram_ids:
        return set()
    try:
        response = (
            supabase.table("cart_reminders")
            .select("telegram_id")
            .in_("telegram_id", telegram_ids)
            .execute()
        )
        return {row["telegram_id"] for row in (response.data or [])}
    except Exception:
        logger.warning("Could not fetch cart_reminders", exc_info=True)
        return set()


def pending_review_telegram_ids(supabase: Client, telegram_ids: list[int]) -> set[int]:
    if not telegram_ids:
        return set()
    try:
        response = (
            supabase.table("telegram_users")
            .select("telegram_id")
            .in_("telegram_id", telegram_ids)
            .eq("payment_status", "pending_review")
            .execute()
        )
        return {row["telegram_id"] for row in (response.data or [])}
    except Exception:
        logger.warning("Could not fetch pending review users", exc_info=True)
        return set()


def mark_cart_reminded(supabase: Client, telegram_id: int) -> None:
    try:
        (
            supabase.table("cart_reminders")
            .upsert({"telegram_id": telegram_id, "reminded_at": now_utc_iso()}, on_conflict="telegram_id")
            .execute()
        )
    except Exception:
        logger.warning("Could not mark cart reminder telegram_id=%s", telegram_id, exc_info=True)


def get_access_channel_by_code(supabase: Client, requested_code: str) -> dict[str, Any] | None:
    requested_code = requested_code.strip()
    if not requested_code:
        return None
    try:
        response = (
            supabase.table("access_channels")
            .select("*")
            .eq("code", requested_code)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]
    except Exception:
        logger.warning("Could not look up access channel by code=%s", requested_code, exc_info=True)
    try:
        response = (
            supabase.table("access_channels")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        for channel in response.data or []:
            if str(channel.get("channel_key") or "") == requested_code:
                return channel
    except Exception:
        logger.warning("Could not fall back to access channel_key=%s", requested_code, exc_info=True)
    return None


def slugify_channel_code(title: str) -> str:
    text = title.lower().replace("&", "")
    chars: list[str] = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
        elif ch in (" ", "-", "_"):
            chars.append("_")
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def access_channel_code_exists(supabase: Client, code: str) -> bool:
    try:
        response = (
            supabase.table("access_channels")
            .select("code")
            .eq("code", code)
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except Exception:
        logger.warning("Could not check if access channel code exists code=%s", code, exc_info=True)
        return False


def get_max_access_channel_sort_order(supabase: Client) -> int:
    try:
        response = (
            supabase.table("access_channels")
            .select("sort_order")
            .order("sort_order", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return int(response.data[0].get("sort_order") or 0)
    except Exception:
        logger.warning("Could not fetch max sort_order", exc_info=True)
    return 0


def insert_access_channel(
    supabase: Client,
    code: str,
    title: str,
    chat_id_value: int,
    category: str | None,
    price: float | None,
    description: str,
    photo_file_id: str,
    sort_order: int,
    featured: bool = False,
) -> None:
    (
        supabase.table("access_channels")
        .insert(
            {
                "code": code,
                "title": title,
                "telegram_chat_id": chat_id_value,
                "has_expiry": False,
                "is_active": True,
                "sort_order": sort_order,
                "category": category,
                "price": price,
                "description": description or None,
                "photo_file_id": photo_file_id,
                "featured": featured,
            }
        )
        .execute()
    )


def set_channel_featured(supabase: Client, code: str, featured: bool) -> None:
    (
        supabase.table("access_channels")
        .update({"featured": featured})
        .eq("code", code)
        .execute()
    )


def parse_add_set_caption(caption: str) -> dict[str, str] | None:
    lines = (caption or "").strip().split("\n")
    if not lines or not lines[0].strip().startswith("/add_set"):
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def available_access_channel_codes(supabase: Client, settings: Settings) -> str:
    channels = get_access_channels(supabase, settings)
    codes = [channel_code(channel) for channel in channels if channel_code(channel)]
    return ", ".join(codes) if codes else "none"


def find_access_channel_for_chat(supabase: Client, settings: Settings, chat_id: int, username: str | None = None) -> dict[str, Any] | None:
    for channel in get_access_channels(supabase, settings):
        telegram_chat_id = channel_telegram_chat_id(channel)
        if telegram_chat_id is None:
            continue
        try:
            parsed_chat_id = parse_stored_chat_id(telegram_chat_id)
            if parsed_chat_id == chat_id:
                return channel
            if isinstance(parsed_chat_id, str) and username and parsed_chat_id.lstrip("@").lower() == username.lower():
                return channel
        except RuntimeError:
            if username and str(telegram_chat_id).lstrip("@").lower() == username.lower():
                return channel
    if chat_id == settings.content_channel_id:
        return grupo_access_channel(settings)
    return None


def save_manual_invite_link(
    supabase: Client,
    channel: dict[str, Any],
    invite_link: str,
    invite_link_name: str,
    admin_id: int,
    expires_at: datetime,
) -> None:
    (
        supabase.table("manual_invite_links")
        .insert(
            {
                "channel_code": channel_code(channel),
                "telegram_chat_id": str(channel_telegram_chat_id(channel)),
                "invite_link": invite_link,
                "invite_link_name": invite_link_name,
                "created_by_admin_id": admin_id,
                "created_at": now_utc_iso(),
                "expires_at": expires_at.isoformat(),
                "revoked": False,
                "notes": "Manual open invite link created by admin",
            }
        )
        .execute()
    )


def find_payment_history_recipient_by_link(supabase: Client, invite_link_value: str) -> int | None:
    try:
        response = (
            supabase.table("payment_history")
            .select("telegram_id, created_at")
            .ilike("invite_link", f"%{invite_link_value}%")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return int(response.data[0]["telegram_id"])
    except Exception:
        logger.warning("Could not look up payment_history recipient for invite link", exc_info=True)
    return None


def get_manual_invite_by_link(supabase: Client, invite_link: str) -> dict[str, Any] | None:
    response = (
        supabase.table("manual_invite_links")
        .select("*")
        .eq("invite_link", invite_link)
        .eq("revoked", False)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def mark_manual_invite_used(supabase: Client, invite_link: str, telegram_id: int) -> None:
    (
        supabase.table("manual_invite_links")
        .update({"used_by_telegram_id": telegram_id, "used_at": now_utc_iso()})
        .eq("invite_link", invite_link)
        .execute()
    )


def is_blacklisted_user(supabase: Client, telegram_id: int) -> bool:
    user = get_registered_user(supabase, telegram_id)
    if user and (
        user.get("status") == "blacklisted"
        or user.get("is_blacklisted") is True
        or user.get("blacklisted") is True
    ):
        return True
    try:
        response = (
            supabase.table("blacklisted_users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except Exception:
        return False


def is_blacklisted(supabase: Client, telegram_id: int) -> bool:
    try:
        response = (
            supabase.table("blacklist")
            .select("telegram_id")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except Exception:
        logger.warning("Could not check blacklist telegram_id=%s", telegram_id, exc_info=True)
        return False


def should_ignore_blacklisted(supabase: Client, settings: Settings, telegram_id: int) -> bool:
    if telegram_id in settings.admin_user_ids:
        return False
    return is_blacklisted(supabase, telegram_id)


class BlacklistMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        settings = data.get("settings")
        supabase = data.get("supabase")
        if user and settings and supabase:
            if await asyncio.to_thread(should_ignore_blacklisted, supabase, settings, user.id):
                return None
        return await handler(event, data)


def ensure_grupo_access_channel(supabase: Client, settings: Settings) -> None:
    try:
        (
            supabase.table("access_channels")
            .upsert(
                {
                    "channel_key": GRUPO_CHANNEL_KEY,
                    "label": GRUPO_CHANNEL_LABEL,
                    "chat_id": str(settings.content_channel_id),
                    "active": True,
                    "is_active": True,
                    "expires_membership": True,
                    "has_expiry": True,
                },
                on_conflict="channel_key",
            )
            .execute()
        )
    except Exception:
        logger.warning("Could not ensure Grupo access channel", exc_info=True)


def selected_channel_keys_from_raw(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part for part in raw.split(",") if part}


def selected_channel_keys_for_approval(selected_channel_keys: set[str] | None) -> set[str]:
    return set(selected_channel_keys or set())


def encode_selected_channel_keys(keys: set[str]) -> str:
    return ",".join(sorted(keys))


def payment_selection_key(callback_query: CallbackQuery, telegram_id: int) -> tuple[int, int, int] | None:
    if not callback_query.message:
        return None
    return (callback_query.message.chat.id, callback_query.message.message_id, telegram_id)


async def delete_pending_payment_admin_messages(bot: Bot, selection_key: tuple[int, int, int] | None) -> None:
    if not selection_key:
        return
    chat_id, admin_message_id, telegram_id = selection_key
    receipt_message_id = PENDING_PAYMENT_ADMIN_MESSAGES.pop((chat_id, admin_message_id), None)
    if not receipt_message_id:
        logger.warning(
            "Missing copied receipt message id for pending payment cleanup telegram_id=%s admin_message_id=%s",
            telegram_id,
            admin_message_id,
        )
    for message_id in (receipt_message_id, admin_message_id):
        if not message_id:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.warning(
                "Could not delete pending payment admin message telegram_id=%s message_id=%s",
                telegram_id,
                message_id,
                exc_info=True,
            )


async def delete_raffle_admin_messages(bot: Bot, admin_message: Message | None) -> None:
    if not admin_message:
        return
    key = (admin_message.chat.id, admin_message.message_id)
    receipt_message_id = RAFFLE_ADMIN_MESSAGES.pop(key, None)
    if not receipt_message_id:
        logger.warning("Missing copied raffle receipt message id admin_message_id=%s", admin_message.message_id)
    for message_id in (receipt_message_id, admin_message.message_id):
        if not message_id:
            continue
        try:
            await bot.delete_message(chat_id=admin_message.chat.id, message_id=message_id)
        except Exception:
            logger.warning("Could not delete raffle admin message message_id=%s", message_id, exc_info=True)


def get_active_raffle(supabase: Client) -> dict[str, Any] | None:
    response = (
        supabase.table("raffle_events")
        .select("*")
        .eq("status", "active")
        .order("draw_date")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_active_raffle_by_trigger(supabase: Client, text: str) -> dict[str, Any] | None:
    response = (
        supabase.table("raffle_events")
        .select("*")
        .eq("status", "active")
        .ilike("trigger_keyword", text.strip())
        .order("draw_date")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_raffle_by_id(supabase: Client, raffle_id: int) -> dict[str, Any] | None:
    response = supabase.table("raffle_events").select("*").eq("id", raffle_id).limit(1).execute()
    return response.data[0] if response.data else None


def raffle_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=RAFFLE_BUTTON_TEXT, callback_data="raffle:start")]]
    )


def raffle_quantity_keyboard(raffle_id: int, max_quantity: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(quantity), callback_data=f"raffle:qty:{raffle_id}:{quantity}")
        for quantity in range(1, min(max_quantity, 5) + 1)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def format_raffle_numbers(rows: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {row['ticket_number']}" for row in rows)


def get_reserved_raffle_order(supabase: Client, telegram_id: int) -> list[dict[str, Any]]:
    active_response = (
        supabase.table("raffle_events")
        .select("*")
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    active_raffle = active_response.data[0] if active_response.data else None
    if not active_raffle:
        logger.info("No active raffle found while checking receipt telegram_id=%s", telegram_id)
        return []
    response = (
        supabase.table("raffle_tickets")
        .select("*")
        .eq("raffle_id", active_raffle["id"])
        .eq("telegram_id", telegram_id)
        .eq("payment_status", "reserved")
        .execute()
    )
    rows = sorted(response.data or [], key=lambda row: str(row.get("ticket_number") or ""))
    if not rows:
        logger.info("No reserved raffle tickets found for active raffle telegram_id=%s raffle_id=%s", telegram_id, active_raffle["id"])
        return []
    logger.info(
        "Reserved raffle tickets detected telegram_id=%s raffle_id=%s order_ids=%s ticket_count=%s",
        telegram_id,
        active_raffle["id"],
        sorted({str(row.get("order_id") or "") for row in rows}),
        len(rows),
    )
    return rows


def update_raffle_tickets_receipt_by_ids(
    supabase: Client,
    ticket_ids: list[int],
    receipt_file_id: str,
    receipt_file_type: str,
) -> None:
    if not ticket_ids:
        return
    (
        supabase.table("raffle_tickets")
        .update(
            {
                "receipt_file_id": receipt_file_id,
                "receipt_file_type": receipt_file_type,
                "updated_at": now_utc_iso(),
            }
        )
        .in_("id", ticket_ids)
        .eq("payment_status", "reserved")
        .execute()
    )


def get_raffle_order(supabase: Client, order_id: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("raffle_tickets")
        .select("*")
        .eq("order_id", order_id)
        .order("ticket_number")
        .execute()
    )
    return response.data or []


def generate_unique_raffle_numbers(supabase: Client, raffle_id: int, quantity: int) -> list[str]:
    response = supabase.table("raffle_tickets").select("ticket_number").eq("raffle_id", raffle_id).execute()
    used = {row["ticket_number"] for row in (response.data or [])}
    numbers: list[str] = []
    attempts = 0
    while len(numbers) < quantity:
        attempts += 1
        if attempts > 2000:
            raise RuntimeError("No pude generar boletos únicos disponibles.")
        number = f"{secrets.randbelow(10000):04d}"
        if number in used or number in numbers:
            continue
        numbers.append(number)
    return numbers


def reserve_raffle_tickets(supabase: Client, raffle: dict[str, Any], user: Any, quantity: int) -> list[dict[str, Any]]:
    raffle_id = int(raffle["id"])
    max_tickets = int(raffle.get("max_tickets_per_user") or 5)
    existing = (
        supabase.table("raffle_tickets")
        .select("id")
        .eq("raffle_id", raffle_id)
        .eq("telegram_id", user.id)
        .in_("payment_status", ["reserved", "confirmed"])
        .execute()
    )
    current_count = len(existing.data or [])
    if current_count + quantity > max_tickets:
        raise ValueError(f"Puedes reservar máximo {max_tickets} boletos para este sorteo.")
    ticket_price = int(raffle.get("ticket_price_mxn") or 100)
    order_id = str(uuid.uuid4())
    rows = [
        {
            "raffle_id": raffle_id,
            "order_id": order_id,
            "telegram_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "ticket_number": number,
            "payment_status": "reserved",
            "amount_expected_mxn": ticket_price,
            "reserved_at": now_utc_iso(),
            "updated_at": now_utc_iso(),
        }
        for number in generate_unique_raffle_numbers(supabase, raffle_id, quantity)
    ]
    response = supabase.table("raffle_tickets").insert(rows).execute()
    return response.data or rows


def update_raffle_order_receipt(
    supabase: Client,
    order_id: str,
    receipt_file_id: str,
    receipt_file_type: str,
) -> None:
    (
        supabase.table("raffle_tickets")
        .update(
            {
                "receipt_file_id": receipt_file_id,
                "receipt_file_type": receipt_file_type,
                "updated_at": now_utc_iso(),
            }
        )
        .eq("order_id", order_id)
        .eq("payment_status", "reserved")
        .execute()
    )


def confirm_raffle_order(supabase: Client, order_id: str, admin_id: int) -> list[dict[str, Any]]:
    rows = get_raffle_order(supabase, order_id)
    if not rows:
        return []
    for row in rows:
        amount_expected = row.get("amount_expected_mxn")
        (
            supabase.table("raffle_tickets")
            .update(
                {
                    "payment_status": "confirmed",
                    "confirmed_at": now_utc_iso(),
                    "amount_paid_mxn": amount_expected,
                    "admin_id": admin_id,
                    "updated_at": now_utc_iso(),
                }
            )
            .eq("id", row["id"])
            .eq("payment_status", "reserved")
            .execute()
        )
    return get_raffle_order(supabase, order_id)


def cancel_raffle_order(supabase: Client, order_id: str, admin_id: int) -> list[dict[str, Any]]:
    rows = get_raffle_order(supabase, order_id)
    if not rows:
        return []
    (
        supabase.table("raffle_tickets")
        .update(
            {
                "payment_status": "cancelled",
                "cancelled_at": now_utc_iso(),
                "admin_id": admin_id,
                "updated_at": now_utc_iso(),
            }
        )
        .eq("order_id", order_id)
        .eq("payment_status", "reserved")
        .execute()
    )
    return rows


def get_reserved_raffle_tickets_for_user(supabase: Client, raffle_id: int, telegram_id: int) -> list[dict[str, Any]]:
    response = (
        supabase.table("raffle_tickets")
        .select("*")
        .eq("raffle_id", raffle_id)
        .eq("telegram_id", telegram_id)
        .eq("payment_status", "reserved")
        .execute()
    )
    return sorted(response.data or [], key=lambda row: str(row.get("ticket_number") or ""))


def confirm_reserved_raffle_tickets_for_user(supabase: Client, raffle_id: int, telegram_id: int, admin_id: int) -> list[dict[str, Any]]:
    rows = get_reserved_raffle_tickets_for_user(supabase, raffle_id, telegram_id)
    if not rows:
        return []
    ticket_ids = [int(row["id"]) for row in rows]
    for row in rows:
        (
            supabase.table("raffle_tickets")
            .update(
                {
                    "payment_status": "confirmed",
                    "confirmed_at": now_utc_iso(),
                    "amount_paid_mxn": row.get("amount_expected_mxn"),
                    "admin_id": admin_id,
                    "updated_at": now_utc_iso(),
                }
            )
            .eq("id", row["id"])
            .eq("payment_status", "reserved")
            .execute()
        )
    response = supabase.table("raffle_tickets").select("*").in_("id", ticket_ids).order("ticket_number").execute()
    return response.data or rows


def cancel_reserved_raffle_tickets_for_user(supabase: Client, raffle_id: int, telegram_id: int, admin_id: int) -> list[dict[str, Any]]:
    rows = get_reserved_raffle_tickets_for_user(supabase, raffle_id, telegram_id)
    if not rows:
        return []
    ticket_ids = [int(row["id"]) for row in rows]
    (
        supabase.table("raffle_tickets")
        .update(
            {
                "payment_status": "cancelled",
                "cancelled_at": now_utc_iso(),
                "admin_id": admin_id,
                "updated_at": now_utc_iso(),
            }
        )
        .in_("id", ticket_ids)
        .eq("payment_status", "reserved")
        .execute()
    )
    return rows


def raffle_stats(supabase: Client, raffle_id: int) -> dict[str, int]:
    rows = supabase.table("raffle_tickets").select("*").eq("raffle_id", raffle_id).execute().data or []
    active_rows = [row for row in rows if row.get("payment_status") in {"reserved", "confirmed"}]
    return {
        "users": len({row.get("telegram_id") for row in rows if row.get("telegram_id")}),
        "reserved": sum(1 for row in rows if row.get("payment_status") == "reserved"),
        "confirmed": sum(1 for row in rows if row.get("payment_status") == "confirmed"),
        "cancelled": sum(1 for row in rows if row.get("payment_status") == "cancelled"),
        "expected_revenue": sum(int(row.get("amount_expected_mxn") or 0) for row in active_rows),
        "confirmed_revenue": sum(int(row.get("amount_paid_mxn") or 0) for row in rows if row.get("payment_status") == "confirmed"),
    }


def raffle_ticket_rows(supabase: Client, raffle_id: int, payment_status: str | None = None) -> list[dict[str, Any]]:
    query = supabase.table("raffle_tickets").select("*").eq("raffle_id", raffle_id)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    rows = query.execute().data or []
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("telegram_id") or ""),
            str(row.get("order_id") or ""),
            str(row.get("payment_status") or ""),
            str(row.get("ticket_number") or ""),
        ),
    )


def raffle_ticket_rows_for_user(supabase: Client, raffle_id: int, lookup: str) -> list[dict[str, Any]]:
    rows = raffle_ticket_rows(supabase, raffle_id)
    normalized = lookup.strip().lstrip("@").lower()
    return [
        row
        for row in rows
        if str(row.get("telegram_id") or "") == normalized
        or str(row.get("username") or "").lower().lstrip("@") == normalized
    ]


def format_raffle_ticket_report(rows: list[dict[str, Any]], title: str) -> str:
    if not rows:
        return f"{title}\n\nNo raffle tickets found."
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("telegram_id") or ""),
            str(row.get("order_id") or "no-order"),
            str(row.get("payment_status") or "-"),
        )
        groups.setdefault(key, []).append(row)
    lines = [title]
    for (telegram_id, order_id, payment_status), group_rows in groups.items():
        first = group_rows[0]
        tickets = ", ".join(str(row.get("ticket_number") or "-") for row in group_rows)
        expected = sum(int(row.get("amount_expected_mxn") or 0) for row in group_rows)
        paid = sum(int(row.get("amount_paid_mxn") or 0) for row in group_rows)
        lines.extend(
            [
                "",
                f"Telegram ID: {telegram_id}",
                f"Username: @{first.get('username') or '-'}",
                f"First name: {first.get('first_name') or '-'}",
                f"Order: {order_id}",
                f"Tickets: {tickets}",
                f"Payment status: {payment_status}",
                f"Expected amount: ${expected} MXN",
                f"Paid amount: ${paid} MXN",
            ]
        )
    return "\n".join(lines)[:3900]


def confirmed_raffle_tickets(supabase: Client, raffle_id: int) -> list[dict[str, Any]]:
    return (
        supabase.table("raffle_tickets")
        .select("*")
        .eq("raffle_id", raffle_id)
        .eq("payment_status", "confirmed")
        .order("telegram_id")
        .order("ticket_number")
        .execute()
        .data
        or []
    )


def draw_raffle_winner(supabase: Client, raffle: dict[str, Any]) -> dict[str, Any]:
    if raffle.get("winner_ticket") or raffle.get("winner_telegram_id"):
        return {"already_drawn": True, "ticket_number": raffle.get("winner_ticket"), "telegram_id": raffle.get("winner_telegram_id")}
    tickets = confirmed_raffle_tickets(supabase, int(raffle["id"]))
    if not tickets:
        raise ValueError("No confirmed tickets.")
    winner = secrets.choice(tickets)
    (
        supabase.table("raffle_events")
        .update(
            {
                "winner_ticket": winner["ticket_number"],
                "winner_telegram_id": winner["telegram_id"],
                "winner_drawn_at": now_utc_iso(),
                "updated_at": now_utc_iso(),
            }
        )
        .eq("id", raffle["id"])
        .is_("winner_drawn_at", "null")
        .execute()
    )
    return {"already_drawn": False, "ticket_number": winner["ticket_number"], "telegram_id": winner["telegram_id"]}


def payment_receipt_file_url(file_id: Any) -> str | None:
    if not file_id:
        return None
    return f"/dashboard/payments/file?{urlencode({'file_id': str(file_id)})}"


def list_approved_payments(supabase: Client, search: str = "", limit: int = 200) -> list[dict[str, Any]]:
    response = (
        supabase.table("payment_history")
        .select("*")
        .eq("action", "approved")
        .eq("payment_status", "paid")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = response.data or []
    search_term = search.strip().lower()
    if search_term:
        rows = [
            row
            for row in rows
            if search_term in str(row.get("telegram_id") or "").lower()
            or search_term in str(row.get("username") or "").lower()
        ]
    for row in rows:
        row["created_at_display"] = format_local_datetime(row.get("created_at"))
        row["receipt_file_url"] = payment_receipt_file_url(row.get("receipt_file_id"))
    return rows


def upsert_user_payload(supabase: Client, telegram_id: int, payload: dict[str, Any]) -> None:
    existing = get_registered_user(supabase, telegram_id)
    if existing:
        (
            supabase.table("telegram_users")
            .update(payload)
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return
    payload.setdefault("telegram_id", telegram_id)
    payload.setdefault("registered_at", now_utc_iso())
    payload.setdefault("joined_at", payload["registered_at"])
    supabase.table("telegram_users").insert(payload).execute()


def run_schema_migration(supabase: Client) -> None:
    supabase.rpc("exec_sql", {"sql": SCHEMA_MIGRATION_SQL}).execute()


def list_dashboard_users(
    supabase: Client,
    user_filter: str,
    search: str = "",
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    query = supabase.table("telegram_users").select("*")
    if user_filter == "active":
        query = query.eq("status", "active")
    elif user_filter == "pending_payments":
        query = query.eq("payment_status", "pending_review")
    elif user_filter == "paid":
        query = query.eq("payment_status", "paid")
    elif user_filter == "needs_new_receipt":
        query = query.eq("payment_status", "needs_new_receipt")
    elif user_filter == "rejected":
        query = query.eq("payment_status", "rejected")
    elif user_filter == "removed_inactive":
        query = query.eq("status", "inactive")
    elif user_filter == "confirmed":
        query = query.eq("confirmed_subscription", True)
    elif user_filter == "source_confirm_subscription":
        query = query.eq("source", CONFIRMATION_SOURCE)
    elif user_filter == "expiring_7":
        today = today_iso()
        soon = (datetime.now(APP_TIMEZONE).date() + timedelta(days=7)).isoformat()
        query = query.gte("expiry_date", today).lte("expiry_date", soon)
    elif user_filter == "expired":
        query = query.lt("expiry_date", today_iso())
    elif user_filter == "no_expiry":
        query = query.is_("expiry_date", "null")

    response = query.order("registered_at", desc=True).limit(2000).execute()
    rows = response.data or []
    if user_filter == "not_confirmed":
        rows = [row for row in rows if row.get("confirmed_subscription") is not True]
    elif user_filter == "has_payment_history":
        try:
            ids_with_history = payment_history_telegram_ids(supabase)
            rows = [row for row in rows if int(row.get("telegram_id")) in ids_with_history]
        except Exception:
            logger.warning("Could not apply has_payment_history dashboard filter", exc_info=True)
            rows = []
    search_term = search.strip().lower()
    if search_term:
        rows = [
            row
            for row in rows
            if search_term in str(row.get("telegram_id") or "").lower()
            or search_term in str(row.get("username") or "").lower()
            or search_term in str(row.get("first_name") or "").lower()
            or search_term in str(row.get("last_name") or "").lower()
        ]

    for row in rows:
        row["days_remaining"] = days_remaining(row.get("expiry_date"))
        row["joined_at_display"] = format_local_datetime(row.get("joined_at"))
        row["confirmed_at_display"] = format_local_datetime(row.get("confirmed_at"))
        row["joined_channel_at_display"] = format_local_datetime(row.get("joined_channel_at"))
        row["left_channel_at_display"] = format_local_datetime(row.get("left_channel_at"))
        row["membership_start_date_effective"] = membership_start_for_user(row).isoformat()

    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page)
    safe_page = min(max(page, 1), total_pages)
    start = (safe_page - 1) * per_page
    end = start + per_page
    page_rows = rows[start:end]
    for row in page_rows:
        try:
            row["recent_payment_history"] = get_payment_history(supabase, int(row["telegram_id"]), limit=5)
        except Exception:
            logger.warning("Could not load recent payment history telegram_id=%s", row.get("telegram_id"), exc_info=True)
            row["recent_payment_history"] = []
    return {
        "rows": page_rows,
        "total": total,
        "page": safe_page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_previous": safe_page > 1,
        "has_next": safe_page < total_pages,
    }


def renew_user_from_today(supabase: Client, telegram_id: int) -> str:
    expiry = (datetime.now(APP_TIMEZONE).date() + timedelta(days=30)).isoformat()
    (
        supabase.table("telegram_users")
        .update(
            {
                "expiry_date": expiry,
                "status": "active",
                "payment_status": "paid",
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
                "payment_status": "paid",
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
                "payment_status": "paid",
                "last_payment_at": now_utc_iso(),
                "notes": "Marked paid from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def pending_payment_keyboard(
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    selected_keys: set[str] | None = None,
) -> InlineKeyboardMarkup:
    channels = sorted(
        get_access_channels(supabase, settings),
        key=lambda channel: channel_code(channel) != GRUPO_CHANNEL_KEY,
    )
    selected = set(selected_keys or set())
    channel_rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for channel in channels:
        key = channel_code(channel)
        if key in HIDDEN_APPROVAL_CHANNEL_CODES:
            continue
        label = channel_label(channel)
        marker = "✅ " if key in selected else "⬜ "
        current_row.append(
            InlineKeyboardButton(
                text=f"{marker}{label}",
                callback_data=f"payment:toggle:{telegram_id}:{key}",
            )
        )
        if len(current_row) == 3:
            channel_rows.append(current_row)
            current_row = []
    if current_row:
        channel_rows.append(current_row)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            *channel_rows,
            [
                InlineKeyboardButton(text="Approve selected ✅", callback_data=f"payment:approve:{telegram_id}"),
            ],
            [
                InlineKeyboardButton(text="Reject ❌", callback_data=f"payment:reject:{telegram_id}"),
                InlineKeyboardButton(text="Ask another receipt 🔁", callback_data=f"payment:ask_receipt:{telegram_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="Confirm renewal ✅",
                    callback_data=f"payment:confirm_renewal:{telegram_id}",
                ),
            ],
        ]
    )


async def create_one_use_invite_link(bot: Bot, settings: Settings, telegram_id: int) -> tuple[str, str]:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    name = f"approved-{telegram_id}-{timestamp}"
    invite = await bot.create_chat_invite_link(
        chat_id=settings.content_channel_id,
        name=name,
        member_limit=1,
        expire_date=datetime.now(timezone.utc) + INVITE_LINK_LIFETIME,
    )
    return invite.invite_link, name


async def create_one_use_invite_link_for_chat(bot: Bot, chat_id: int | str, telegram_id: int, channel_key: str) -> tuple[str, str]:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    name = f"approved-{channel_key}-{telegram_id}-{timestamp}"[:32]
    invite = await bot.create_chat_invite_link(
        chat_id=chat_id,
        name=name,
        member_limit=1,
        expire_date=datetime.now(timezone.utc) + INVITE_LINK_LIFETIME,
    )
    return invite.invite_link, name


async def create_manual_open_invite_link(bot: Bot, chat_id: int | str, channel_code_value: str) -> tuple[str, str, datetime]:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    name = f"manual-open-{channel_code_value}-{timestamp}"[:32]
    expires_at = datetime.now(timezone.utc) + INVITE_LINK_LIFETIME
    invite = await bot.create_chat_invite_link(
        chat_id=chat_id,
        name=name,
        member_limit=1,
        expire_date=expires_at,
    )
    return invite.invite_link, name, expires_at


def has_active_unused_invite(row: dict[str, Any] | None) -> bool:
    if not row or not row.get("invite_link"):
        return False
    if row.get("invite_link_revoked") is True or row.get("invite_link_used") is True:
        return False
    created_at = parse_iso_datetime(row.get("invite_link_created_at"))
    if not created_at:
        return False
    return datetime.now(timezone.utc) - created_at < INVITE_LINK_LIFETIME


def payment_recently_approved(row: dict[str, Any] | None) -> bool:
    if not row or row.get("payment_status") != "paid":
        return False
    approved_at = parse_iso_datetime(row.get("approved_at"))
    if not approved_at:
        return False
    return datetime.now(timezone.utc) - approved_at < timedelta(hours=1)


async def save_invite_link(
    supabase: Client,
    telegram_id: int,
    invite_link: str,
    invite_link_name: str,
    notes: str = "One-use invite link generated",
) -> None:
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        {
            "telegram_id": telegram_id,
            "invite_link": invite_link,
            "invite_link_created_at": now_utc_iso(),
            "invite_link_name": invite_link_name,
            "invite_link_revoked": False,
            "invite_link_used": False,
            "notes": notes,
        },
    )


def save_user_channel_access(
    supabase: Client,
    telegram_id: int,
    channel: dict[str, Any],
    invite_link: str,
    invite_link_name: str,
    expires_at: str | None = None,
) -> None:
    payload = {
        "telegram_id": telegram_id,
        "channel_key": channel_code(channel),
        "channel_label": channel_label(channel),
        "chat_id": str(channel_telegram_chat_id(channel)),
        "invite_link": invite_link,
        "invite_link_name": invite_link_name,
        "invite_link_created_at": now_utc_iso(),
        "invite_link_revoked": False,
        "invite_link_used": False,
        "status": "active",
        "access_status": "active",
        "granted_at": now_utc_iso(),
        "joined_channel_at": now_utc_iso(),
        "expires_at": expires_at,
        "updated_at": now_utc_iso(),
    }
    try:
        (
            supabase.table("user_channel_access")
            .upsert(payload, on_conflict="telegram_id,channel_key")
            .execute()
        )
    except Exception:
        logger.warning(
            "Could not save user_channel_access telegram_id=%s channel_key=%s",
            telegram_id,
            channel_code(channel),
            exc_info=True,
        )


async def revoke_invite_for_user(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    note: str,
    clear_link: bool = False,
) -> bool:
    user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    if not user or not user.get("invite_link") or user.get("invite_link_revoked") is True:
        return False
    revoked_link = user["invite_link"]
    try:
        await bot.revoke_chat_invite_link(settings.content_channel_id, revoked_link)
        logger.info("Revoked previous invite link telegram_id=%s", telegram_id)
    except TelegramBadRequest:
        logger.warning("Could not revoke previous invite link telegram_id=%s", telegram_id, exc_info=True)
    payload: dict[str, Any] = {
        "telegram_id": telegram_id,
        "invite_link_revoked": True,
        "revoked_at": now_utc_iso(),
        "notes": note,
    }
    if clear_link:
        payload.update(
            {
                "invite_link": None,
                "invite_link_created_at": None,
                "invite_link_name": None,
                "invite_link_used": False,
            }
        )
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        payload,
    )
    return True


async def revoke_existing_invite_link(bot: Bot, supabase: Client, settings: Settings, telegram_id: int) -> None:
    await revoke_invite_for_user(
        bot,
        supabase,
        settings,
        telegram_id,
        "Previous invite link revoked before generating a new one",
    )


async def regenerate_invite_link(bot: Bot, supabase: Client, settings: Settings, telegram_id: int) -> str:
    await revoke_existing_invite_link(bot, supabase, settings, telegram_id)
    invite_link, invite_name = await create_one_use_invite_link(bot, settings, telegram_id)
    await save_invite_link(supabase, telegram_id, invite_link, invite_name, "Invite link regenerated by admin")
    return invite_link


async def create_invite_if_no_active(bot: Bot, supabase: Client, settings: Settings, telegram_id: int) -> str:
    user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    if has_active_unused_invite(user):
        raise ValueError("⚠️ Este usuario ya tiene un invite link activo")
    invite_link, invite_name = await create_one_use_invite_link(bot, settings, telegram_id)
    await save_invite_link(supabase, telegram_id, invite_link, invite_name, "Invite link generated by admin")
    return invite_link


async def send_invite_to_user(bot: Bot, telegram_id: int, invite_link: str) -> bool:
    try:
        await bot.send_message(
            telegram_id,
            f"Pago aprobado ✅ Aquí está tu link privado de acceso: {invite_link}\n"
            "Este link es personal y de un solo uso.",
        )
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM invite link to telegram_id=%s", telegram_id, exc_info=True)
        return False


async def send_channel_invites_to_user(bot: Bot, telegram_id: int, channel_links: list[dict[str, str]]) -> bool:
    lines = ["Pago aprobado ✅", ""]
    for item in channel_links:
        lines.append(f"{item['label']}:")
        lines.append(item["invite_link"])
        lines.append("")
    try:
        await bot.send_message(telegram_id, "\n".join(lines).strip())
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM channel invite links to telegram_id=%s", telegram_id, exc_info=True)
        return False


async def send_renewal_confirmation(bot: Bot, telegram_id: int) -> bool:
    try:
        await bot.send_message(
            telegram_id,
            "Tu membresía ha sido renovada exitosamente. Gracias 💕",
        )
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM renewal confirmation telegram_id=%s", telegram_id, exc_info=True)
        return False


async def approve_payment(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    admin_id: int,
    selected_channel_keys: set[str] | None = None,
) -> dict[str, Any]:
    existing_user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    requested_keys = selected_channel_keys_for_approval(selected_channel_keys)
    if GRUPO_CHANNEL_KEY in requested_keys:
        requested_keys = requested_keys | GRUPO_BUNDLED_CHANNEL_KEYS
    available_channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    selected_channels = [
        channel
        for channel in available_channels
        if channel_code(channel) in requested_keys
    ]
    if not selected_channels:
        raise ValueError("Selecciona al menos un canal disponible.")
    includes_grupo = any(channel_code(channel) == GRUPO_CHANNEL_KEY for channel in selected_channels)
    includes_expiring_channel = any(channel_has_expiry(channel) for channel in selected_channels)

    if payment_recently_approved(existing_user):
        if includes_grupo and len(selected_channels) == 1 and has_active_unused_invite(existing_user):
            invite_link = existing_user["invite_link"]
            dm_sent = await send_invite_to_user(bot, telegram_id, invite_link)
            if dm_sent:
                await bot.send_message(settings.admin_chat_id, f"Pago ya aprobado recientemente; reenvié el link existente a {telegram_id}")
            else:
                await bot.send_message(
                    settings.admin_chat_id,
                    "Pago ya aprobado recientemente. No pude reenviar el link; el usuario debe abrir el bot o escribirle primero.",
                )
            logger.warning("Duplicate approval prevented telegram_id=%s active_link_reused=true", telegram_id)
            return {"invite_link": invite_link, "duplicate": True, "reused": True}
        logger.warning("Duplicate approval prevented telegram_id=%s active_link_reused=false", telegram_id)
        raise ValueError("Payment already approved recently; not generating another invite link.")

    today = datetime.now(APP_TIMEZONE).date()
    expiry = today + timedelta(days=30)
    reused_invite = includes_grupo and has_active_unused_invite(existing_user)
    invite_link = ""
    invite_name = ""
    channel_links: list[dict[str, str]] = []
    if reused_invite:
        invite_link = existing_user["invite_link"]
        invite_name = existing_user.get("invite_link_name") or f"existing-{telegram_id}"
        channel_links.append({"label": GRUPO_CHANNEL_LABEL, "invite_link": invite_link})
    for channel in selected_channels:
        code = channel_code(channel)
        if code == GRUPO_CHANNEL_KEY and reused_invite:
            await asyncio.to_thread(
                save_user_channel_access,
                supabase,
                telegram_id,
                channel,
                invite_link,
                invite_name,
                expiry.isoformat() if channel_has_expiry(channel) else None,
            )
            continue
        telegram_chat_id = channel_telegram_chat_id(channel)
        if not telegram_chat_id:
            logger.error("Selected approval channel is missing telegram_chat_id: %s", channel)
            raise ValueError(f"Canal {channel_label(channel)} no tiene telegram_chat_id configurado.")
        chat_id = parse_stored_chat_id(telegram_chat_id)
        generated_link, generated_name = await create_one_use_invite_link_for_chat(bot, chat_id, telegram_id, code)
        await asyncio.to_thread(
            save_user_channel_access,
            supabase,
            telegram_id,
            channel,
            generated_link,
            generated_name,
            expiry.isoformat() if channel_has_expiry(channel) else None,
        )
        channel_links.append({"label": channel_label(channel), "invite_link": generated_link})
        if code == GRUPO_CHANNEL_KEY:
            invite_link = generated_link
            invite_name = generated_name

    approval_payload = {
        "telegram_id": telegram_id,
        "status": "active",
        "payment_status": "paid",
        "approved_by_admin_id": admin_id,
        "approved_at": now_utc_iso(),
        "last_payment_at": now_utc_iso(),
        "notes": "Payment approved by admin",
    }
    if includes_expiring_channel:
        approval_payload.update(
            {
                "membership_start_date": today.isoformat(),
                "expiry_date": expiry.isoformat(),
            }
        )
    if includes_grupo:
        approval_payload.update(
            {
                "invite_link": invite_link,
                "invite_link_name": invite_name,
                "invite_link_revoked": False,
                "invite_link_used": False,
            }
        )
    if includes_grupo and not reused_invite:
        approval_payload["invite_link_created_at"] = now_utc_iso()
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        approval_payload,
    )
    await asyncio.to_thread(
        insert_payment_history,
        supabase,
        telegram_id,
        "approved",
        "paid",
        admin_id,
        existing_user.get("pending_payment_file_id") if existing_user else None,
        existing_user.get("pending_payment_file_type") if existing_user else None,
        "\n".join(f"{item['label']}: {item['invite_link']}" for item in channel_links),
        today.isoformat() if includes_expiring_channel else None,
        expiry.isoformat() if includes_expiring_channel else None,
        True,
        "Payment approved by admin",
        existing_user.get("username") if existing_user else None,
        existing_user.get("first_name") if existing_user else None,
    )
    for channel in selected_channels:
        await asyncio.to_thread(remove_cart_item, supabase, telegram_id, channel_code(channel))
    dm_sent = await send_channel_invites_to_user(bot, telegram_id, channel_links)
    if dm_sent:
        await bot.send_message(settings.admin_chat_id, f"Pago aprobado y link enviado a {telegram_id}")
    else:
        await bot.send_message(
            settings.admin_chat_id,
            "No pude enviar el link. El usuario debe abrir el bot o escribirle primero.",
        )
    logger.info("Payment approved telegram_id=%s admin_id=%s dm_sent=%s", telegram_id, admin_id, dm_sent)
    return {"invite_link": invite_link, "channel_links": channel_links, "duplicate": False, "reused": reused_invite}


async def reject_payment(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    admin_id: int | None = None,
) -> None:
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        {
            "telegram_id": telegram_id,
            "payment_status": "rejected",
            "rejected_at": now_utc_iso(),
            "notes": "Payment rejected by admin",
        },
    )
    try:
        await bot.send_message(
            telegram_id,
            "Tu comprobante no pudo ser validado. Revisa la información y vuelve a intentarlo.",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM rejection to telegram_id=%s", telegram_id, exc_info=True)
    await bot.send_message(settings.admin_chat_id, f"Comprobante rechazado para {telegram_id}")
    logger.info("Payment rejected telegram_id=%s", telegram_id)


async def ask_new_receipt(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    admin_id: int | None = None,
) -> None:
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        {
            "telegram_id": telegram_id,
            "payment_status": "needs_new_receipt",
            "needs_new_receipt_at": now_utc_iso(),
            "notes": "Admin requested another receipt",
        },
    )
    try:
        await bot.send_message(telegram_id, "Por favor envía otra captura más clara del comprobante.")
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM receipt request to telegram_id=%s", telegram_id, exc_info=True)
    await bot.send_message(settings.admin_chat_id, f"Se pidió otra captura a {telegram_id}")
    logger.info("New receipt requested telegram_id=%s", telegram_id)


async def create_or_send_existing_invite(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
) -> str:
    user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    invite_link = user.get("invite_link") if has_active_unused_invite(user) else None
    if not invite_link:
        invite_link, invite_name = await create_one_use_invite_link(bot, settings, telegram_id)
        await save_invite_link(supabase, telegram_id, invite_link, invite_name, "Invite link generated by admin")
    sent = await send_invite_to_user(bot, telegram_id, invite_link)
    if not sent:
        await bot.send_message(
            settings.admin_chat_id,
            "No pude enviar el link. El usuario debe abrir el bot o escribirle primero.",
        )
    logger.info("Invite send attempted telegram_id=%s sent=%s", telegram_id, sent)
    return invite_link


def expired_active_users(supabase: Client) -> list[dict[str, Any]]:
    response = (
        supabase.table("telegram_users")
        .select("*")
        .eq("status", "active")
        .lt("expiry_date", today_iso())
        .execute()
    )
    return response.data or []


def active_users_expiring_next_7_days(supabase: Client) -> list[dict[str, Any]]:
    today = datetime.now(APP_TIMEZONE).date()
    soon = today + timedelta(days=7)
    response = (
        supabase.table("telegram_users")
        .select(
            "telegram_id,username,first_name,expiry_date,"
            "renewal_notice_7d_sent_at,renewal_notice_3d_sent_at,renewal_notice_1d_sent_at"
        )
        .eq("status", "active")
        .gte("expiry_date", today.isoformat())
        .lte("expiry_date", soon.isoformat())
        .order("expiry_date")
        .execute()
    )
    return response.data or []


def renewal_broadcast_text(expiry_date: Any) -> str:
    expiry = str(expiry_date or "-")
    return (
        "Hola bebé 💕\n\n"
        f"Solo paso a recordarte que tu membresía vence el {expiry}. "
        "Te aviso con anticipación para evitar que se te junte al final. ✨\n\n"
        "En caso de no recibir tu renovación antes de esa fecha, tu acceso al canal será removido "
        "automáticamente al día siguiente.\n\n"
        f"Además, si realizas tu renovación a más tardar el {expiry}, recibirás un pequeño set de regalo "
        "como agradecimiento. 🎁💖\n\n"
        "Si tienes alguna situación especial o necesitas datos para transferencia o un link de pago con "
        "tarjeta, házmelo saber y con gusto te los envío.\n\n"
        "¡Gracias, bebé! 😘"
    )


def scheduled_renewal_notice_text(expiry_date: Any) -> str:
    expiry = str(expiry_date or "-")
    return (
        "Hola bebé 💕\n\n"
        f"Solo paso a recordarte que tu membresía vence el {expiry}. "
        "Te aviso con anticipación para evitar que se te junte al final. ✨\n\n"
        "En caso de no recibir tu renovación antes de esa fecha, tu acceso al canal será removido "
        "automáticamente al día siguiente.\n\n"
        "Si necesitas datos para transferencia o link de pago con tarjeta, házmelo saber y con gusto te los envío. 💖\n\n"
        "¡Gracias, bebé! 😘"
    )


def insert_renewal_message_recipient(supabase: Client, row: dict[str, Any]) -> None:
    try:
        supabase.table("renewal_message_recipients").insert(
            {
                "telegram_id": row.get("telegram_id"),
                "username": row.get("username"),
                "first_name": row.get("first_name"),
                "sent_at": now_utc_iso(),
            }
        ).execute()
    except Exception:
        logger.warning(
            "Could not store renewal message recipient telegram_id=%s",
            row.get("telegram_id"),
            exc_info=True,
        )


def latest_renewal_message_recipients(supabase: Client, limit: int = 20) -> list[dict[str, Any]]:
    response = (
        supabase.table("renewal_message_recipients")
        .select("telegram_id,username,first_name,sent_at")
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def prediction_scores_for_game(game_code: str) -> list[str]:
    return PREDICTION_GAMES.get(game_code, [])


def build_prediction_keyboard(game_code: str) -> InlineKeyboardMarkup:
    scores = prediction_scores_for_game(game_code)
    labels = PREDICTION_BUTTON_LABELS.get(game_code, scores)
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for index, score in enumerate(scores):
        current_row.append(
            InlineKeyboardButton(
                text=labels[index],
                callback_data=f"prediction:{game_code}:{index}",
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def upsert_prediction_vote(supabase: Client, game_code: str, callback_query: CallbackQuery, selected_score: str) -> None:
    if not callback_query.from_user:
        raise ValueError("Callback query has no from_user")
    user = callback_query.from_user
    existing = (
        supabase.table("prediction_votes")
        .select("id")
        .eq("game_code", game_code)
        .eq("telegram_id", user.id)
        .limit(1)
        .execute()
    )
    payload = {
        "game_code": game_code,
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "selected_score": selected_score,
        "updated_at": now_utc_iso(),
    }
    if existing.data:
        (
            supabase.table("prediction_votes")
            .update(payload)
            .eq("game_code", game_code)
            .eq("telegram_id", user.id)
            .execute()
        )
    else:
        payload["created_at"] = now_utc_iso()
        supabase.table("prediction_votes").insert(payload).execute()


def prediction_votes_for_game(supabase: Client, game_code: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("prediction_votes")
        .select("*")
        .eq("game_code", game_code)
        .order("selected_score")
        .order("first_name")
        .execute()
    )
    return response.data or []


def prediction_winner_rows(supabase: Client, game_code: str, score: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("prediction_votes")
        .select("*")
        .eq("game_code", game_code)
        .eq("selected_score", score)
        .order("first_name")
        .execute()
    )
    return response.data or []


async def remove_user_from_channel(
    bot: Bot,
    supabase: Client,
    settings: Settings,
    telegram_id: int,
    reason: str,
) -> None:
    await bot.ban_chat_member(chat_id=settings.content_channel_id, user_id=telegram_id)
    await bot.unban_chat_member(
        chat_id=settings.content_channel_id,
        user_id=telegram_id,
        only_if_banned=True,
    )
    await asyncio.to_thread(
        upsert_user_payload,
        supabase,
        telegram_id,
        {
            "telegram_id": telegram_id,
            "status": "inactive",
            "removed_at": now_utc_iso(),
            "removal_reason": reason,
            "notes": "Removed from channel",
        },
    )
    logger.info("Removed telegram_id=%s reason=%s", telegram_id, reason)


ACTIVE_MEMBER_STATUSES = {"member", "administrator", "creator", "restricted"}


async def sweep_blacklisted_user_from_all_channels(
    bot: Bot, supabase: Client, settings: Settings, telegram_id: int
) -> list[str]:
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    removed_from: list[str] = []
    for channel in channels:
        chat_id_raw = channel_telegram_chat_id(channel)
        if not chat_id_raw:
            continue
        try:
            chat_id = parse_stored_chat_id(chat_id_raw)
            member = await bot.get_chat_member(chat_id=chat_id, user_id=telegram_id)
        except Exception:
            continue
        if member.status not in ACTIVE_MEMBER_STATUSES:
            continue
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=telegram_id)
            await bot.unban_chat_member(chat_id=chat_id, user_id=telegram_id, only_if_banned=True)
            removed_from.append(channel_label(channel))
        except Exception:
            logger.warning(
                "Could not remove blacklisted telegram_id=%s from channel=%s",
                telegram_id,
                channel_code(channel),
                exc_info=True,
            )
    return removed_from


def mark_user_inactive(supabase: Client, telegram_id: int, notes: str = "Marked inactive from dashboard") -> None:
    (
        supabase.table("telegram_users")
        .update({"status": "inactive", "notes": notes})
        .eq("telegram_id", telegram_id)
        .execute()
    )


def set_membership_start_date(supabase: Client, telegram_id: int, start_date: str) -> str:
    parsed = datetime.strptime(start_date, DATE_FORMAT).date()
    expiry = (parsed + timedelta(days=30)).isoformat()
    (
        supabase.table("telegram_users")
        .update(
            {
                "membership_start_date": parsed.isoformat(),
                "expiry_date": expiry,
                "status": "active",
                "notes": "Membership start date set from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return expiry


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
        .update(
            {
                "invite_link": invite_link,
                "invite_link_created_at": now_utc_iso(),
                "notes": "Generated one-use invite link from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def set_confirmation_status(supabase: Client, telegram_id: int, confirmed: bool) -> None:
    payload: dict[str, Any] = {
        "confirmed_subscription": confirmed,
        "notes": "Marked confirmed manually" if confirmed else "Marked not confirmed manually",
    }
    if confirmed:
        payload.update(
            {
                "confirmed_at": now_utc_iso(),
                "confirmation_campaign": "manual_dashboard",
                "source": "manual_dashboard",
                "status": "active",
            }
        )
    else:
        payload["confirmed_at"] = None

    (
        supabase.table("telegram_users")
        .update(payload)
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
                "removal_reason": "dashboard_remove",
                "notes": "Removed from channel from dashboard",
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def build_membership_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Quiero unirme al grupo", callback_data="cart:join_grupo")],
        ]
    )


def build_category_picker_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Etérea", callback_data="cart:category:eterea"),
                InlineKeyboardButton(text="Casera", callback_data="cart:category:casera"),
            ],
            [InlineKeyboardButton(text="Ver carrito", callback_data="cart:view")],
        ]
    )


def carousel_caption(channel: dict[str, Any]) -> str:
    label = channel_label(channel)
    price = channel_price(channel)
    price_text = f"${price:.0f} MXN" if price is not None else "-"
    badges = []
    if channel_is_featured(channel):
        badges.append("⭐ DESTACADO")
    if channel_is_new(channel):
        badges.append("🆕 NUEVO")
    parts = []
    if badges:
        parts.append(" · ".join(badges))
    parts.append(f"{label} — {price_text}")
    description = channel_description(channel)
    if description:
        parts.append("")
        parts.append(description)
    return "\n".join(parts)


def build_carousel_keyboard(
    category: str,
    index: int,
    total: int,
    channel: dict[str, Any],
    cart_keys: set[str],
) -> InlineKeyboardMarkup:
    code = channel_code(channel)
    price = channel_price(channel)
    price_text = f"${price:.0f}" if price is not None else "-"
    add_label = "✅ Agregado" if code in cart_keys else f"➕ Agregar {price_text}"
    nav_row: list[InlineKeyboardButton] = []
    if index > 0:
        nav_row.append(InlineKeyboardButton(text="‹ Anterior", callback_data=f"carousel:nav:{category}:{index - 1}"))
    nav_row.append(InlineKeyboardButton(text=add_label, callback_data=f"carousel:toggle:{category}:{index}"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton(text="Siguiente ›", callback_data=f"carousel:nav:{category}:{index + 1}"))
    other_category = "casera" if category == "eterea" else "eterea"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            nav_row,
            [
                InlineKeyboardButton(
                    text=f"Ver {CART_CATEGORIES[other_category]}",
                    callback_data=f"cart:category:{other_category}",
                ),
                InlineKeyboardButton(text=f"Ver carrito ({len(cart_keys)})", callback_data="cart:view"),
            ],
        ]
    )


def build_cart_summary_keyboard(channels: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        code = channel_code(channel)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Quitar {channel_label(channel)}",
                    callback_data=f"cart:remove:{code}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Seguir viendo", callback_data="cart:category:eterea"),
        ]
    )
    if channels:
        rows.append(
            [InlineKeyboardButton(text="Confirmar y pagar", callback_data="cart:checkout")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def build_confirm_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CONFIRM_SUBSCRIPTION_BUTTON_TEXT,
                    callback_data=CONFIRM_SUBSCRIPTION_CALLBACK_DATA,
                )
            ]
        ]
    )


def build_channel_choice_keyboard(channels: list[dict[str, Any]], telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=channel_label(channel),
                    callback_data=f"ask_channel:{telegram_id}:{channel_code(channel)}",
                )
            ]
            for channel in channels
        ]
    )


def build_send_selected_channel_link_keyboard(telegram_id: int, channel_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Send link ✅",
                    callback_data=f"send_channel_link:{telegram_id}:{channel_key}",
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
    membership_start_date = datetime.now(APP_TIMEZONE).date()
    expiry_date = (membership_start_date + timedelta(days=30)).isoformat()
    payload = {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": "active",
        "payment_status": "unpaid",
        "notes": CTA_NOTES,
    }

    if existing:
        if not existing.get("joined_at"):
            payload["joined_at"] = joined_at
        if not existing.get("membership_start_date"):
            payload["membership_start_date"] = membership_start_for_user(existing).isoformat()
        if not existing.get("expiry_date"):
            payload["expiry_date"] = (membership_start_for_user({**existing, **payload}) + timedelta(days=30)).isoformat()
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
    payload["membership_start_date"] = membership_start_date.isoformat()
    payload["expiry_date"] = expiry_date
    supabase.table("telegram_users").insert(payload).execute()
    logger.info("Registered CTA user telegram_id=%s", user.id)


def upsert_confirmed_subscription_user(supabase: Client, callback_query: CallbackQuery) -> None:
    if not callback_query.from_user:
        raise ValueError("Callback query has no from_user")

    user = callback_query.from_user
    existing = get_registered_user(supabase, user.id)
    now = now_utc_iso()
    membership_start_date = datetime.now(APP_TIMEZONE).date()
    payload: dict[str, Any] = {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": "active",
        "confirmed_subscription": True,
        "confirmed_at": now,
        "confirmation_campaign": CONFIRMATION_CAMPAIGN,
        "source": CONFIRMATION_SOURCE,
    }

    if existing:
        if not existing.get("joined_at"):
            payload["joined_at"] = now
        if not existing.get("registered_at"):
            payload["registered_at"] = now
        if not existing.get("membership_start_date"):
            payload["membership_start_date"] = membership_start_date.isoformat()
        if not existing.get("expiry_date"):
            payload["expiry_date"] = (membership_start_date + timedelta(days=30)).isoformat()
        (
            supabase.table("telegram_users")
            .update(payload)
            .eq("telegram_id", user.id)
            .execute()
        )
        logger.info("Confirmed subscription for telegram_id=%s", user.id)
        return

    payload["registered_at"] = now
    payload["joined_at"] = now
    payload["membership_start_date"] = membership_start_date.isoformat()
    payload["expiry_date"] = (membership_start_date + timedelta(days=30)).isoformat()
    supabase.table("telegram_users").insert(payload).execute()
    logger.info("Registered confirmed subscription user telegram_id=%s", user.id)


async def can_browse_cart_catalog(
    supabase: Client, telegram_id: int, existing_user: dict[str, Any] | None
) -> bool:
    if is_active_member(existing_user):
        return True
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    return GRUPO_CHANNEL_KEY in cart_keys


def cart_summary_text(selected: list[dict[str, Any]]) -> str:
    lines = ["Tu carrito:"]
    for channel in selected:
        price = channel_price(channel)
        price_text = f"${price:.0f}" if price is not None else "-"
        lines.append(f"• {channel_label(channel)} — {price_text}")
    lines.append("")
    subtotal, discount, total = cart_discount(selected)
    if discount > 0:
        lines.append(f"Subtotal: ${subtotal:.0f} MXN")
        lines.append(f"Descuento por volumen (-{CART_DISCOUNT_RATE * 100:.0f}%): -${discount:.0f} MXN")
        lines.append(f"Total: ${total:.0f} MXN")
    else:
        lines.append(f"Total: ${total:.0f} MXN")
    return "\n".join(lines)


@router.message(Command("start"))
async def cart_start(message: Message, settings: Settings, supabase: Client) -> None:
    if not message.from_user:
        return
    existing_user = await asyncio.to_thread(get_registered_user, supabase, message.from_user.id)
    if await can_browse_cart_catalog(supabase, message.from_user.id, existing_user):
        await message.answer(
            "¿Qué tipo de contenido quieres ver hoy bebé? 🔥",
            reply_markup=build_category_picker_keyboard(),
        )
        return
    grupo = await asyncio.to_thread(get_access_channel_by_code, supabase, GRUPO_CHANNEL_KEY) or grupo_access_channel(settings)
    price = channel_price(grupo)
    price_text = f"${price:.0f} MXN/mes" if price is not None else "$300 MXN/mes"
    await message.answer(
        "Hola bebé 💕 Para ver los sets disponibles primero necesitas ser miembro del Grupo Exclusivo.\n\n"
        f"💎 Grupo Exclusivo — {price_text}",
        reply_markup=build_membership_gate_keyboard(),
    )


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


@router.message(Command("send_confirm_subscription"))
async def send_confirm_subscription(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await message.bot.send_message(
            chat_id=settings.content_channel_id,
            text=CONFIRM_SUBSCRIPTION_MESSAGE,
            reply_markup=build_confirm_subscription_keyboard(),
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.exception("Could not send subscription confirmation message")
        await message.answer(f"No pude enviar el mensaje de confirmación: {exc}")
        return

    await message.answer("Mensaje de confirmación enviado al canal.")


@router.message(F.text.startswith("/send_mex_inglaterra_prediction"))
@router.message(Command("send_mex_inglaterra_prediction"))
async def send_mex_inglaterra_prediction(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await message.bot.send_message(
            chat_id=settings.content_channel_id,
            text=PREDICTION_MEX_INGLATERRA_TEXT,
            reply_markup=build_prediction_keyboard(PREDICTION_MEX_INGLATERRA_GAME_CODE),
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.exception("Could not send Mexico England prediction")
        await message.answer(f"No pude enviar el pronóstico: {exc}")
        return

    await message.answer("Pronóstico México vs Inglaterra enviado al canal.")


async def send_raffle_quantity_prompt(bot: Bot, user_id: int, raffle: dict[str, Any]) -> bool:
    try:
        await bot.send_message(
            user_id,
            "¿Cuántos boletos deseas?",
            reply_markup=raffle_quantity_keyboard(int(raffle["id"]), int(raffle.get("max_tickets_per_user") or 5)),
        )
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM raffle quantity prompt telegram_id=%s", user_id, exc_info=True)
        return False


async def handle_raffle_receipt(
    message: Message,
    settings: Settings,
    supabase: Client,
    order_rows: list[dict[str, Any]] | None = None,
) -> bool:
    if not message.from_user:
        return False
    if order_rows is None:
        order_rows = await asyncio.to_thread(get_reserved_raffle_order, supabase, message.from_user.id)
    if not order_rows:
        return False
    file_type = "photo" if message.photo else "document"
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    order_id = str(order_rows[0]["order_id"])
    raffle_id = int(order_rows[0]["raffle_id"])
    ticket_ids = [int(row["id"]) for row in order_rows if row.get("id") is not None]
    logger.info(
        "Raffle receipt detected telegram_id=%s raffle_id=%s order_ids=%s ticket_count=%s file_type=%s",
        message.from_user.id,
        raffle_id,
        sorted({str(row.get("order_id") or "") for row in order_rows}),
        len(order_rows),
        file_type,
    )
    await asyncio.to_thread(update_raffle_tickets_receipt_by_ids, supabase, ticket_ids, file_id, file_type)
    raffle = await asyncio.to_thread(get_raffle_by_id, supabase, raffle_id)
    ticket_numbers = "\n".join(str(row.get("ticket_number") or "-") for row in order_rows)
    amount_expected = sum(int(row.get("amount_expected_mxn") or 0) for row in order_rows)
    username = f"@{message.from_user.username}" if message.from_user.username else "-"
    admin_text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎟️ NEW RAFFLE PAYMENT\n\n"
        "👤 User:\n"
        f"{username}\n\n"
        "🆔 Telegram ID:\n"
        f"{message.from_user.id}\n\n"
        "🎟️ Reserved Tickets:\n"
        f"{ticket_numbers}\n\n"
        "💰 Expected Payment:\n"
        f"${amount_expected} MXN\n\n"
        "📅 Raffle:\n"
        f"{(raffle or {}).get('title') or '-'}\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirmar boletos", callback_data=f"raffle_admin:confirm_user:{raffle_id}:{message.from_user.id}"),
                InlineKeyboardButton(text="❌ Rechazar boletos", callback_data=f"raffle_admin:reject_user:{raffle_id}:{message.from_user.id}"),
            ]
        ]
    )
    copied_receipt = None
    try:
        copied_receipt = await message.bot.copy_message(
            chat_id=settings.admin_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as exc:
        logger.exception("Could not copy raffle receipt telegram_id=%s", message.from_user.id)
        await message.answer("Recibimos tu comprobante, pero no pude copiarlo al admin. Intenta de nuevo en un momento.")
        return True
    try:
        admin_message = await message.bot.send_message(settings.admin_chat_id, admin_text, reply_markup=keyboard)
        RAFFLE_ADMIN_MESSAGES[(admin_message.chat.id, admin_message.message_id)] = copied_receipt.message_id
        await message.answer("Comprobante recibido ✅ Lo revisaremos para confirmar tus boletos.")
        logger.info(
            "Raffle receipt admin notification sent telegram_id=%s order_id=%s admin_message_id=%s copied_receipt_id=%s",
            message.from_user.id,
            order_id,
            admin_message.message_id,
            copied_receipt.message_id,
        )
    except Exception as exc:
        logger.exception("Could not notify admin about raffle receipt telegram_id=%s", message.from_user.id)
        await message.answer("Recibimos tu comprobante, pero no pude avisar al admin. Intenta de nuevo en un momento.")
    return True


@router.message(Command("send_raffle"))
async def send_raffle(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle:
        await message.answer("No active raffle found.")
        return
    text = (
        f"{raffle.get('title')}\n\n"
        f"{raffle.get('description') or ''}\n\n"
        f"Precio: ${raffle.get('ticket_price_mxn')} MXN\n"
        f"Fecha del sorteo: {raffle.get('draw_date') or '-'}"
    )
    try:
        await message.bot.send_message(settings.content_channel_id, text, reply_markup=raffle_start_keyboard())
        await message.answer("Raffle sent to content channel.")
    except Exception as exc:
        logger.exception("Could not send raffle")
        await message.answer(f"No pude enviar el sorteo: {exc}")


@router.message(Command("raffle_stats"))
async def raffle_stats_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle:
        await message.answer("No active raffle found.")
        return
    stats = await asyncio.to_thread(raffle_stats, supabase, int(raffle["id"]))
    await message.answer(
        f"{raffle.get('title')}\n\n"
        f"Users: {stats['users']}\n"
        f"Reserved tickets: {stats['reserved']}\n"
        f"Confirmed tickets: {stats['confirmed']}\n"
        f"Cancelled tickets: {stats['cancelled']}\n"
        f"Expected revenue: ${stats['expected_revenue']} MXN\n"
        f"Confirmed revenue: ${stats['confirmed_revenue']} MXN"
    )


async def send_raffle_ticket_report(
    message: Message,
    settings: Settings,
    supabase: Client,
    title: str,
    payment_status: str | None = None,
    user_lookup: str | None = None,
) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle:
        await message.answer("No active raffle found.")
        return
    if user_lookup:
        rows = await asyncio.to_thread(raffle_ticket_rows_for_user, supabase, int(raffle["id"]), user_lookup)
    else:
        rows = await asyncio.to_thread(raffle_ticket_rows, supabase, int(raffle["id"]), payment_status)
    await message.answer(format_raffle_ticket_report(rows, title))


@router.message(Command("raffle_users"))
async def raffle_users_command(message: Message, settings: Settings, supabase: Client) -> None:
    await send_raffle_ticket_report(message, settings, supabase, "Raffle participants")


@router.message(Command("raffle_user"))
async def raffle_user_command(message: Message, settings: Settings, supabase: Client) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Uso: /raffle_user <telegram_id_or_username>")
        return
    await send_raffle_ticket_report(message, settings, supabase, f"Raffle user: {parts[1]}", user_lookup=parts[1])


@router.message(Command("raffle_pending"))
async def raffle_pending_command(message: Message, settings: Settings, supabase: Client) -> None:
    await send_raffle_ticket_report(message, settings, supabase, "Reserved raffle tickets", payment_status="reserved")


@router.message(Command("raffle_confirmed"))
async def raffle_confirmed_command(message: Message, settings: Settings, supabase: Client) -> None:
    await send_raffle_ticket_report(message, settings, supabase, "Confirmed raffle tickets", payment_status="confirmed")


@router.message(Command("raffle_cancelled"))
async def raffle_cancelled_command(message: Message, settings: Settings, supabase: Client) -> None:
    await send_raffle_ticket_report(message, settings, supabase, "Cancelled raffle tickets", payment_status="cancelled")


@router.message(Command("raffle_tickets"))
async def raffle_tickets_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle:
        await message.answer("No active raffle found.")
        return
    rows = await asyncio.to_thread(confirmed_raffle_tickets, supabase, int(raffle["id"]))
    if not rows:
        await message.answer("No confirmed raffle tickets.")
        return
    grouped: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    for row in rows:
        telegram_id = int(row["telegram_id"])
        grouped.setdefault(telegram_id, []).append(row["ticket_number"])
        names[telegram_id] = f"@{row.get('username') or '-'} {row.get('first_name') or ''}".strip()
    lines = [f"Confirmed tickets for {raffle.get('title')}:"]
    for telegram_id, tickets in grouped.items():
        lines.append(f"\n{telegram_id} {names.get(telegram_id, '')}")
        lines.append(", ".join(tickets))
    await message.answer("\n".join(lines)[:3900])


@router.message(Command("raffle_draw"))
async def raffle_draw_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle:
        await message.answer("No active raffle found.")
        return
    try:
        result = await asyncio.to_thread(draw_raffle_winner, supabase, raffle)
        prefix = "Winner already drawn" if result["already_drawn"] else "Winner drawn"
        await message.answer(
            f"{prefix}:\n"
            f"Ticket: {result['ticket_number']}\n"
            f"Telegram ID: {result['telegram_id']}"
        )
    except Exception as exc:
        logger.exception("Could not draw raffle")
        await message.answer(f"No pude hacer el sorteo: {exc}")


@router.message(Command("send_raffle_winner_link"))
async def send_raffle_winner_link(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    raffle = await asyncio.to_thread(get_active_raffle, supabase)
    if not raffle or not raffle.get("winner_telegram_id"):
        await message.answer("No raffle winner found.")
        return
    channel = await asyncio.to_thread(get_access_channel_by_code, supabase, RAFFLE_PRIZE_CHANNEL_CODE)
    if not channel:
        await message.answer(f"Prize channel not found: {RAFFLE_PRIZE_CHANNEL_CODE}")
        return
    telegram_id = int(raffle["winner_telegram_id"])
    try:
        invite_link, invite_name = await create_one_use_invite_link_for_chat(
            message.bot,
            parse_stored_chat_id(channel_telegram_chat_id(channel)),
            telegram_id,
            channel_code(channel),
        )
        await asyncio.to_thread(save_user_channel_access, supabase, telegram_id, channel, invite_link, invite_name, None)
        await message.bot.send_message(
            telegram_id,
            f"🎉 Felicidades, ganaste el sorteo.\n\nAquí está tu acceso al premio:\n{invite_link}",
        )
        await message.answer(f"Prize invite sent to raffle winner {telegram_id}.")
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM raffle winner link telegram_id=%s", telegram_id, exc_info=True)
        await message.answer("No pude enviar el link. El usuario debe abrir el bot o escribirle primero.")
    except Exception as exc:
        logger.exception("Could not send raffle winner link")
        await message.answer(f"No pude enviar el link: {exc}")


@router.message(F.chat.type == "private", F.text)
async def raffle_trigger_text(message: Message, settings: Settings, supabase: Client) -> None:
    if not message.from_user or (message.text or "").startswith("/"):
        raise SkipHandler()
    raffle = await asyncio.to_thread(get_active_raffle_by_trigger, supabase, message.text or "")
    if not raffle:
        raise SkipHandler()
    await message.answer(
        "¿Cuántos boletos deseas?",
        reply_markup=raffle_quantity_keyboard(int(raffle["id"]), int(raffle.get("max_tickets_per_user") or 5)),
    )


@router.message(F.chat.type == "private", F.photo, F.caption.startswith("/add_set"))
async def add_set_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        return
    fields = parse_add_set_caption(message.caption or "")
    if fields is None:
        return
    usage = (
        "Formato:\n\n"
        "/add_set\n"
        "titulo: Nombre del set\n"
        "chat_id: -1001234567890\n"
        "categoria: eterea o casera (déjala vacía para ocultarlo del carrito)\n"
        "precio: 750\n"
        "descripcion: texto de la descripción\n"
        "destacado: si (opcional, para que aparezca primero en su categoría)"
    )
    titulo = fields.get("titulo") or fields.get("título")
    chat_id_raw = fields.get("chat_id")
    categoria = (fields.get("categoria") or fields.get("categoría") or "").strip().lower() or None
    precio_raw = fields.get("precio")
    descripcion = fields.get("descripcion") or fields.get("descripción") or ""
    destacado = (fields.get("destacado") or "").strip().lower() in {"si", "sí", "yes", "true"}

    if not titulo or not chat_id_raw:
        await message.answer(f"Faltan datos obligatorios (título y chat_id).\n\n{usage}")
        return
    try:
        chat_id_value = int(chat_id_raw)
    except ValueError:
        await message.answer(f"chat_id inválido, debe ser un número como -1001234567890.\n\n{usage}")
        return
    if categoria and categoria not in CART_CATEGORIES:
        await message.answer(f"Categoría inválida: '{categoria}'. Usa 'eterea', 'casera', o déjala vacía.")
        return
    price_value: float | None = None
    if precio_raw:
        try:
            price_value = float(precio_raw)
        except ValueError:
            await message.answer("Precio inválido, debe ser un número como 750.")
            return

    code = slugify_channel_code(titulo)
    if not code:
        await message.answer("No pude generar un código válido a partir del título.")
        return
    if await asyncio.to_thread(access_channel_code_exists, supabase, code):
        await message.answer(f"Ya existe un canal con el código '{code}'. Usa un título distinto.")
        return

    photo_file_id = message.photo[-1].file_id
    try:
        max_sort = await asyncio.to_thread(get_max_access_channel_sort_order, supabase)
        await asyncio.to_thread(
            insert_access_channel,
            supabase,
            code,
            titulo,
            chat_id_value,
            categoria,
            price_value,
            descripcion,
            photo_file_id,
            max_sort + 1,
            destacado,
        )
    except Exception as exc:
        logger.exception("Could not create new access channel code=%s", code)
        await message.answer(f"No pude crear el canal: {exc}")
        return

    await message.answer(
        "✅ Canal creado\n"
        f"código: {code}\n"
        f"título: {titulo}\n"
        f"chat_id: {chat_id_value}\n"
        f"categoría: {categoria or 'ninguna (oculto del carrito, solo aprobación manual)'}\n"
        f"precio: {'$' + f'{price_value:.0f}' if price_value is not None else '-'}\n"
        f"destacado: {'sí' if destacado else 'no'}\n\n"
        "Recuerda: @renaaaa_bot debe ser administrador de ese canal con permiso de invitar."
    )


@router.message(Command("feature_set"))
async def feature_set_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Uso: /feature_set <codigo>\nCorre el comando de nuevo sobre el mismo código para quitarlo de destacado.")
        return
    code = parts[1].strip().lower()
    channel = await asyncio.to_thread(get_access_channel_by_code, supabase, code)
    if not channel:
        await message.answer(f"No encontré un canal activo con el código '{code}'.")
        return
    new_state = not channel_is_featured(channel)
    try:
        await asyncio.to_thread(set_channel_featured, supabase, code, new_state)
    except Exception as exc:
        logger.exception("Could not toggle featured for code=%s", code)
        await message.answer(f"No pude actualizar: {exc}")
        return
    label = channel_label(channel)
    if new_state:
        await message.answer(f"⭐ {label} ahora está destacado.")
    else:
        await message.answer(f"{label} ya no está destacado.")


@router.message(F.chat.type == "private", (F.photo | F.document))
async def receive_payment_receipt(message: Message, settings: Settings, supabase: Client) -> None:
    if not message.from_user:
        return
    logger.info("Receipt received from telegram_id=%s", message.from_user.id)
    raffle_order_rows: list[dict[str, Any]] = []
    try:
        logger.info("Active raffle lookup started for telegram_id=%s", message.from_user.id)
        active_response = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: supabase.table("raffle_events")
                .select("*")
                .eq("status", "active")
                .limit(1)
                .execute()
            ),
            timeout=20,
        )
        active_raffle = active_response.data[0] if active_response.data else None
        if not active_raffle:
            logger.info("No active raffle found for receipt telegram_id=%s; continuing normal payment flow", message.from_user.id)
        else:
            active_raffle_id = active_raffle["id"]
            logger.info(
                "Active raffle found for receipt telegram_id=%s raffle_id=%s code=%s",
                message.from_user.id,
                active_raffle_id,
                active_raffle.get("code"),
            )
            logger.info("Reserved raffle ticket lookup started telegram_id=%s raffle_id=%s", message.from_user.id, active_raffle_id)
            reserved_response = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: supabase.table("raffle_tickets")
                    .select("*")
                    .eq("raffle_id", active_raffle_id)
                    .eq("telegram_id", message.from_user.id)
                    .eq("payment_status", "reserved")
                    .execute()
                ),
                timeout=20,
            )
            raffle_order_rows = sorted(reserved_response.data or [], key=lambda row: str(row.get("ticket_number") or ""))
            tickets = ", ".join(str(row.get("ticket_number")) for row in raffle_order_rows)
            logger.info(
                "Reserved raffle ticket rows found telegram_id=%s raffle_id=%s count=%s tickets=%s",
                message.from_user.id,
                active_raffle_id,
                len(raffle_order_rows),
                tickets or "-",
            )
            if raffle_order_rows:
                logger.info("Routing receipt to raffle flow telegram_id=%s tickets=%s", message.from_user.id, tickets)
            else:
                logger.info("No raffle reserved tickets found for telegram_id=%s; continuing normal payment flow", message.from_user.id)
    except Exception as exc:
        logger.exception("Raffle lookup error telegram_id=%s", message.from_user.id)
    if raffle_order_rows and await handle_raffle_receipt(message, settings, supabase, raffle_order_rows):
        return
    if message.from_user.id in settings.admin_user_ids:
        return
    if await asyncio.to_thread(should_ignore_blacklisted, supabase, settings, message.from_user.id):
        return

    now = now_utc_iso()
    file_type = "photo" if message.photo else "document"
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    user = message.from_user
    existing_user = await asyncio.to_thread(get_registered_user, supabase, user.id)
    payload = {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "payment_status": "pending_review",
        "pending_payment_file_id": file_id,
        "pending_payment_file_type": file_type,
        "pending_payment_at": now,
        "source": "payment_receipt_private_bot",
        "last_seen_at": now,
        "notes": "Payment receipt submitted privately",
    }
    await asyncio.to_thread(upsert_user_payload, supabase, user.id, payload)
    if existing_user and existing_user.get("payment_status") == "pending_review":
        await message.answer(
            "Tu comprobante anterior fue actualizado ✅\n"
            "Estamos validando tu pago y pronto recibirás tu acceso."
        )
        logger.info("Updated existing pending payment receipt telegram_id=%s", user.id)
        return

    await message.answer("Comprobante recibido ✅ Lo revisaremos manualmente.")

    username = f"@{user.username}" if user.username else "-"
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, user.id)
    admin_text = "Nuevo comprobante pendiente\n"
    if cart_keys:
        cart_channels_list = cart_channels(
            await asyncio.to_thread(get_access_channels, supabase, settings), cart_keys
        )
        _, _, expected_total = cart_discount(cart_channels_list)
        admin_text += f"💰 Monto esperado: ${expected_total:.0f} MXN\n\n"
    admin_text += (
        f"telegram_id: {user.id}\n"
        f"username: {username}\n"
        f"first_name: {user.first_name or '-'}\n"
        f"last_name: {user.last_name or '-'}\n"
        f"pending_payment_at: {now}"
    )
    if cart_keys:
        admin_text += "\n\nCarrito del cliente:\n" + cart_summary_text(cart_channels_list)
    try:
        copied_receipt = await message.bot.copy_message(
            chat_id=settings.admin_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        admin_message = await message.bot.send_message(
            settings.admin_chat_id,
            admin_text,
            reply_markup=await asyncio.to_thread(
                pending_payment_keyboard,
                supabase,
                settings,
                user.id,
                cart_keys or None,
            ),
        )
        PENDING_PAYMENT_ADMIN_MESSAGES[(admin_message.chat.id, admin_message.message_id)] = copied_receipt.message_id
        if cart_keys:
            PAYMENT_CHANNEL_SELECTIONS[(admin_message.chat.id, admin_message.message_id, user.id)] = set(cart_keys)
        logger.info("Payment receipt submitted telegram_id=%s cart_size=%s", user.id, len(cart_keys))
    except Exception:
        logger.exception("Could not notify admin about payment receipt telegram_id=%s", user.id)


@router.message(Command("sales_stats"))
async def sales_stats_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    try:
        rows = await asyncio.to_thread(fetch_all_approved_payment_history, supabase)
        channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    except Exception as exc:
        logger.exception("Could not compute sales stats")
        await message.answer(f"No pude calcular estadísticas: {exc}")
        return

    price_by_label = {channel_label(c): channel_price(c) or 0 for c in channels}
    category_by_label = {channel_label(c): channel_category(c) for c in channels}

    channel_counts: dict[str, int] = {}
    channel_revenue: dict[str, float] = {}
    category_revenue: dict[str, float] = {"eterea": 0.0, "casera": 0.0, "grupo": 0.0}
    total_revenue = 0.0

    for row in rows:
        for label in parse_channel_labels_from_invite_text(row.get("invite_link") or ""):
            price = price_by_label.get(label, 0)
            channel_counts[label] = channel_counts.get(label, 0) + 1
            channel_revenue[label] = channel_revenue.get(label, 0) + price
            total_revenue += price
            category = category_by_label.get(label)
            if category:
                category_revenue[category] = category_revenue.get(category, 0) + price
            elif label == GRUPO_CHANNEL_LABEL:
                category_revenue["grupo"] = category_revenue.get("grupo", 0) + price

    total_transactions = len(rows)
    avg_order = total_revenue / total_transactions if total_transactions else 0
    top_sets = sorted(channel_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    lines = [
        "📊 Estadísticas de ventas (estimado con precios actuales)",
        f"Transacciones aprobadas: {total_transactions}",
        f"Ingreso total estimado: ${total_revenue:.0f} MXN",
        f"Ticket promedio: ${avg_order:.0f} MXN",
        "",
        f"Grupo: ${category_revenue.get('grupo', 0):.0f} · Etérea: ${category_revenue.get('eterea', 0):.0f} · Casera: ${category_revenue.get('casera', 0):.0f}",
        "",
        "Top 5 sets más vendidos:",
    ]
    if top_sets:
        lines.extend(f"• {label}: {count} veces (${channel_revenue.get(label, 0):.0f} MXN)" for label, count in top_sets)
    else:
        lines.append("Sin datos todavía.")

    await send_long_message(message, "\n".join(lines))


@router.message(Command("users"))
async def users(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        total, latest = await asyncio.to_thread(fetch_users_summary, supabase)
    except Exception as exc:
        logger.exception("Could not fetch users")
        await message.answer(f"No pude consultar usuarios: {exc}")
        return

    lines = [f"Usuarios registrados: {total}", "", "Últimos 10:"]
    lines.extend(format_user(row) for row in latest)
    if not latest:
        lines.append("Sin usuarios registrados todavía.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("chat_id"))
@router.channel_post(Command("chat_id"))
async def chat_id(message: Message, settings: Settings) -> None:
    admin_triggered = is_admin(message, settings)
    bot_is_admin = False
    try:
        bot_user = await message.bot.get_me()
        bot_member = await message.bot.get_chat_member(message.chat.id, bot_user.id)
        bot_is_admin = bot_member.status in {"administrator", "creator"}
    except Exception:
        logger.warning("Could not verify bot admin status for /chat_id chat_id=%s", message.chat.id, exc_info=True)

    if not admin_triggered and not bot_is_admin:
        logger.warning("Ignoring /chat_id because sender and bot are not admin chat_id=%s", message.chat.id)
        if message.chat.type == "private":
            await reject_non_admin(message)
        return

    title = message.chat.title or getattr(message.chat, "full_name", None) or "-"
    username = message.chat.username or "-"
    chat_type = message.chat.type
    text = (
        f"Chat ID: {message.chat.id}\n"
        f"Title: {title}\n"
        f"Username: {username}\n"
        f"Type: {chat_type}"
    )
    logger.info(
        "Chat ID requested chat_id=%s title=%s username=%s type=%s",
        message.chat.id,
        title,
        username,
        chat_type,
    )
    try:
        await message.bot.send_message(settings.admin_chat_id, text)
        if message.chat.id != settings.admin_chat_id:
            await message.answer("Chat ID enviado al admin.")
    except Exception as exc:
        logger.exception("Could not send chat id to admin")
        await message.answer(f"No pude enviar el chat id: {exc}")


def command_telegram_id(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@router.message(Command("unconfirmed"))
async def unconfirmed(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(fetch_unconfirmed_users, supabase)
    except Exception as exc:
        logger.exception("Could not fetch unconfirmed users")
        await message.answer(f"No pude consultar no confirmados: {exc}")
        return

    lines = [f"Usuarios sin confirmación: {len(rows)}"]
    lines.extend(format_user(row) for row in rows[:50])
    if len(rows) > 50:
        lines.append(f"...y {len(rows) - 50} más.")
    if not rows:
        lines.append("Todos los usuarios están confirmados.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("pending_payments"))
async def pending_payments(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    try:
        rows = await asyncio.to_thread(fetch_pending_payment_users, supabase)
    except Exception as exc:
        logger.exception("Could not fetch pending payments")
        await message.answer(f"No pude consultar pagos pendientes: {exc}")
        return
    lines = [f"Pagos pendientes: {len(rows)}"]
    lines.extend(format_user(row) for row in rows)
    if not rows:
        lines.append("No hay pagos pendientes.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("user"))
async def user_record(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /user <telegram_id>")
        return
    row = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    await send_long_message(message, format_user_record(row or {}))


@router.message(Command("reset_user"))
async def reset_user_session(message: Message, settings: Settings, fsm_manager: Any) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /reset_user <telegram_id>")
        return

    context: FSMContext = fsm_manager.get_context(
        bot=message.bot,
        chat_id=telegram_id,
        user_id=telegram_id,
    )
    state = await context.get_state()
    data = await context.get_data()
    if state is None and not data:
        await message.answer("User has no active session.\nNothing to reset.")
        return

    await context.clear()
    logger.info(
        "Admin reset user FSM session admin_id=%s telegram_id=%s previous_state=%s",
        message.from_user.id if message.from_user else None,
        telegram_id,
        state,
    )
    await message.answer(
        "✅ User session reset successfully.\n\n"
        f"Telegram ID:\n{telegram_id}"
    )


@router.message(Command("payment_history"))
async def payment_history_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /payment_history <telegram_id>")
        return
    try:
        rows = await asyncio.to_thread(get_payment_history, supabase, telegram_id, 10)
    except Exception as exc:
        logger.exception("Could not fetch payment history telegram_id=%s", telegram_id)
        await message.answer(f"No pude consultar historial de pagos: {exc}")
        return
    await send_long_message(message, f"Historial de pagos para {telegram_id}:\n{format_payment_history_rows(rows)}")


@router.message(Command("confirm_renewal"))
async def confirm_renewal(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /confirm_renewal <telegram_id>")
        return
    sent = await send_renewal_confirmation(message.bot, telegram_id)
    if sent:
        await message.answer(f"Confirmación de renovación enviada a {telegram_id}.")
    else:
        await message.answer("No pude enviar la confirmación. El usuario debe abrir el bot o escribirle primero.")


@router.message(Command("contact_admin"))
async def contact_admin(message: Message, settings: Settings) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /contact_admin <telegram_id>")
        return
    try:
        await message.bot.send_message(
            telegram_id,
            "Hola 👋\n\n"
            "No puedo validar tu pago por el momento.\n\n"
            "Por favor contacta a @chivi01 para continuar con tu solicitud.\n\n"
            "Gracias 💕",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM contact admin message telegram_id=%s", telegram_id, exc_info=True)
        await message.answer("No pude enviar el mensaje. El usuario debe abrir el bot o escribirle primero.")
        return

    await message.answer(f"Mensaje de contacto enviado a {telegram_id} ✅")


@router.message(Command("blacklist"))
async def blacklist_user(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /blacklist <telegram_id>")
        return
    try:
        await asyncio.to_thread(
            lambda: supabase.table("blacklist")
            .upsert({"telegram_id": telegram_id}, on_conflict="telegram_id")
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not blacklist telegram_id=%s", telegram_id)
        await message.answer(f"No pude bloquear usuario: {exc}")
        return
    await message.answer(f"Usuario {telegram_id} agregado a blacklist. Revisando canales...")
    try:
        removed_from = await sweep_blacklisted_user_from_all_channels(message.bot, supabase, settings, telegram_id)
    except Exception:
        logger.exception("Could not sweep blacklisted telegram_id=%s across channels", telegram_id)
        await message.answer("No pude revisar los canales automáticamente; revísalo a mano si sigue teniendo acceso.")
        return
    if removed_from:
        await message.answer(f"Expulsado de: {', '.join(removed_from)}")
    else:
        await message.answer("No estaba activo en ningún canal.")


@router.message(Command("unblacklist"))
async def unblacklist_user(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /unblacklist <telegram_id>")
        return
    try:
        await asyncio.to_thread(
            lambda: supabase.table("blacklist")
            .delete()
            .eq("telegram_id", telegram_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not unblacklist telegram_id=%s", telegram_id)
        await message.answer(f"No pude desbloquear usuario: {exc}")
        return
    await message.answer(f"Usuario {telegram_id} removido de blacklist.")


@router.message(Command("check_blacklist"))
async def check_blacklist(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /check_blacklist <telegram_id>")
        return
    blocked = await asyncio.to_thread(is_blacklisted, supabase, telegram_id)
    if blocked:
        await message.answer(f"Usuario {telegram_id} está en blacklist.")
    else:
        await message.answer(f"Usuario {telegram_id} no está en blacklist.")


@router.message(Command("send_invite"))
async def send_invite(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /send_invite <telegram_id>")
        return
    try:
        await create_or_send_existing_invite(message.bot, supabase, settings, telegram_id)
        await message.answer(f"Link enviado o guardado para {telegram_id}.")
    except Exception as exc:
        logger.exception("Could not send invite telegram_id=%s", telegram_id)
        await message.answer(f"No pude enviar/generar link: {exc}")


@router.message(Command("manual_open_link"))
async def manual_open_link(message: Message, settings: Settings, supabase: Client) -> None:
    logger.info(
        "Received /manual_open_link chat_id=%s from_user_id=%s text=%s",
        message.chat.id,
        message.from_user.id if message.from_user else None,
        message.text,
    )
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    if not message.from_user:
        await message.answer("No pude identificar al admin.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer("Usage: /manual_open_link grupo")
        return

    requested_code = parts[1].strip()
    try:
        channel = await asyncio.to_thread(get_access_channel_by_code, supabase, requested_code)
        if not channel:
            available_codes = await asyncio.to_thread(available_access_channel_codes, supabase, settings)
            await message.answer(f"Channel not found. Available active channel codes: {available_codes}")
            return
        telegram_chat_id = channel_telegram_chat_id(channel)
        if not telegram_chat_id:
            logger.error("Manual open channel missing telegram_chat_id: %s", channel)
            await message.answer(f"Canal {requested_code} no tiene telegram_chat_id configurado.")
            return
        chat_id = parse_stored_chat_id(telegram_chat_id)
        invite_link, invite_name, expires_at = await create_manual_open_invite_link(
            message.bot,
            chat_id,
            channel_code(channel),
        )
        await asyncio.to_thread(
            save_manual_invite_link,
            supabase,
            channel,
            invite_link,
            invite_name,
            message.from_user.id,
            expires_at,
        )
        await message.answer(f"Manual open invite link\n{channel_label(channel)}:\n{invite_link}")
    except Exception as exc:
        logger.exception("Could not create manual open invite link channel_code=%s", requested_code)
        await message.answer(f"No pude crear el link manual: {exc}")


@router.message(Command("send_manual_link"))
async def send_manual_link(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    if not message.from_user:
        await message.answer("No pude identificar al admin.")
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("Uso: /send_manual_link <telegram_id> <channel_code>")
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("telegram_id inválido.")
        return

    requested_code = parts[2].strip()
    if not requested_code:
        await message.answer("Uso: /send_manual_link <telegram_id> <channel_code>")
        return

    try:
        channel = await asyncio.to_thread(get_access_channel_by_code, supabase, requested_code)
        if not channel:
            available_codes = await asyncio.to_thread(available_access_channel_codes, supabase, settings)
            await message.answer(f"Channel not found. Available active channel codes: {available_codes}")
            return
        telegram_chat_id = channel_telegram_chat_id(channel)
        if not telegram_chat_id:
            logger.error("Manual send channel missing telegram_chat_id: %s", channel)
            await message.answer(f"Canal {requested_code} no tiene telegram_chat_id configurado.")
            return

        invite_link, invite_name, expires_at = await create_manual_open_invite_link(
            message.bot,
            parse_stored_chat_id(telegram_chat_id),
            channel_code(channel),
        )
        await asyncio.to_thread(
            save_manual_invite_link,
            supabase,
            channel,
            invite_link,
            invite_name,
            message.from_user.id,
            expires_at,
        )
        await message.bot.send_message(
            telegram_id,
            f"Aquí está tu link de acceso a {channel_label(channel)}: {invite_link}",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM manual invite link telegram_id=%s", telegram_id, exc_info=True)
        await message.answer("No pude enviar el link. El usuario debe abrir el bot o escribirle primero.")
        return
    except Exception as exc:
        logger.exception(
            "Could not create/send manual invite link telegram_id=%s channel_code=%s",
            telegram_id,
            requested_code,
        )
        await message.answer(f"No pude generar/enviar el link: {exc}")
        return

    await message.answer(f"Link enviado a {telegram_id}.")


@router.message(Command("ask_channel"))
async def ask_channel(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /ask_channel <telegram_id>")
        return

    try:
        channels = await asyncio.to_thread(get_access_channels, supabase, settings)
        if not channels:
            await message.answer("No hay canales activos configurados.")
            return
        await message.bot.send_message(
            telegram_id,
            "¿Qué contenido quieres recibir?",
            reply_markup=build_channel_choice_keyboard(channels, telegram_id),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM channel request telegram_id=%s", telegram_id, exc_info=True)
        await message.answer("No pude enviar la solicitud. El usuario debe abrir el bot o escribirle primero.")
        return
    except Exception as exc:
        logger.exception("Could not send channel request telegram_id=%s", telegram_id)
        await message.answer(f"No pude enviar la solicitud: {exc}")
        return

    await message.answer(f"Solicitud enviada a {telegram_id}.")


@router.message(Command("revoke_invite"))
async def revoke_invite(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /revoke_invite <telegram_id>")
        return

    revoked = await revoke_invite_for_user(
        message.bot,
        supabase,
        settings,
        telegram_id,
        "Invite link revoked by admin",
    )
    if not revoked:
        await message.answer("No invite link found.")
        return
    await message.answer("Invite link revoked.")


@router.message(Command("revoke_user"))
async def revoke_user(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /revoke_user <telegram_id>")
        return

    revoked = await revoke_invite_for_user(
        message.bot,
        supabase,
        settings,
        telegram_id,
        "Latest invite link revoked for user by admin",
        clear_link=True,
    )
    if not revoked:
        await message.answer("No invite link found.")
        return
    await message.answer(f"✅ Último link revocado para usuario {telegram_id}")


@router.message(Command("revoke_link"))
async def revoke_link(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer("Uso: /revoke_link <invite_link_name>")
        return
    invite_link_name = parts[1].strip()
    if invite_link_name.startswith("https://t.me/"):
        channels = await asyncio.to_thread(get_access_channels, supabase, settings)
        for channel in channels:
            telegram_chat_id = channel_telegram_chat_id(channel)
            logger.info(
                "Trying to revoke direct invite link channel=%s telegram_chat_id=%s",
                channel,
                telegram_chat_id,
            )
            if not telegram_chat_id:
                logger.warning("Skipping revoke attempt; channel missing telegram_chat_id: %s", channel)
                continue
            try:
                await message.bot.revoke_chat_invite_link(
                    chat_id=parse_stored_chat_id(telegram_chat_id),
                    invite_link=invite_link_name,
                )
                logger.info("Direct invite link revoked from channel=%s", channel)
                await message.answer(f"✅ Invite link revoked from {channel_label(channel)}")
                return
            except TelegramBadRequest as exc:
                logger.warning(
                    "Telegram error revoking direct invite link channel=%s error=%s",
                    channel,
                    exc,
                )
                continue
            except Exception as exc:
                logger.warning(
                    "Telegram error revoking direct invite link channel=%s error=%s",
                    channel,
                    exc,
                    exc_info=True,
                )
                continue
        await message.answer("❌ Invite link not found in managed channels.")
        return

    try:
        telegram_id = int(invite_link_name)
    except ValueError:
        telegram_id = None
    if telegram_id is not None:
        revoked = await revoke_invite_for_user(
            message.bot,
            supabase,
            settings,
            telegram_id,
            "Latest invite link revoked for user by admin",
            clear_link=True,
        )
        if not revoked:
            await message.answer("No invite link found.")
            return
        await message.answer(f"✅ Último link revocado para usuario {telegram_id}")
        return

    user = await asyncio.to_thread(get_user_by_invite_link_name, supabase, invite_link_name)
    invite_link = user.get("invite_link") if user else None
    if not user or not invite_link:
        await message.answer("No invite link found.")
        return

    try:
        await message.bot.revoke_chat_invite_link(
            chat_id=settings.content_channel_id,
            invite_link=invite_link,
        )
        await asyncio.to_thread(
            upsert_user_payload,
            supabase,
            int(user["telegram_id"]),
            {
                "telegram_id": int(user["telegram_id"]),
                "invite_link_revoked": True,
                "revoked_at": now_utc_iso(),
                "notes": "Invite link revoked by admin",
            },
        )
    except Exception as exc:
        logger.exception("Could not revoke invite by name invite_link_name=%s", invite_link_name)
        await message.answer(f"No pude revocar el link: {exc}")
        return

    await message.answer("✅ Link revocado correctamente")


@router.message(Command("approve"))
async def approve_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None or not message.from_user:
        await message.answer("Uso: /approve <telegram_id>")
        return
    try:
        result = await approve_payment(
            message.bot,
            supabase,
            settings,
            telegram_id,
            message.from_user.id,
            {GRUPO_CHANNEL_KEY},
        )
        if result.get("duplicate"):
            await message.answer(f"Pago ya aprobado recientemente; reenvié link existente para {telegram_id}.")
        else:
            await message.answer(f"Pago aprobado para {telegram_id}.")
    except Exception as exc:
        logger.exception("Could not approve telegram_id=%s", telegram_id)
        await message.answer(f"No pude aprobar: {exc}")


@router.message(Command("reject"))
async def reject_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /reject <telegram_id>")
        return
    await reject_payment(message.bot, supabase, settings, telegram_id, message.from_user.id if message.from_user else None)
    await message.answer(f"Pago rechazado para {telegram_id}.")


@router.message(Command("ask_receipt"))
async def ask_receipt_command(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    telegram_id = command_telegram_id(message)
    if telegram_id is None:
        await message.answer("Uso: /ask_receipt <telegram_id>")
        return
    await ask_new_receipt(message.bot, supabase, settings, telegram_id, message.from_user.id if message.from_user else None)
    await message.answer(f"Se pidió otra captura a {telegram_id}.")


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
        updated = await asyncio.to_thread(set_user_expiry_date, supabase, telegram_id, expiry)
    except Exception as exc:
        logger.exception("Could not set expiry for telegram_id=%s", telegram_id)
        await message.answer(f"No pude actualizar la fecha: {exc}")
        return

    if not updated:
        await message.answer("Usuario no encontrado en telegram_users.")
        return

    await message.answer(f"Vencimiento actualizado: {telegram_id} -> {expiry}")


@router.message(Command("expired"))
async def expired(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(expired_active_users, supabase)
    except Exception as exc:
        logger.exception("Could not fetch expired users")
        await message.answer(f"No pude consultar expirados: {exc}")
        return

    lines = [f"Usuarios activos expirados al {today_iso()}: {len(rows)}"]
    lines.extend(format_user(row) for row in rows)
    if not rows:
        lines.append("No hay usuarios activos expirados.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("renewal_preview"))
async def renewal_preview(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(active_users_expiring_next_7_days, supabase)
    except Exception as exc:
        logger.exception("Could not fetch renewal preview users")
        await message.answer(f"No pude consultar renovaciones próximas: {exc}")
        return

    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("expiry_date") or ""),
            str(row.get("first_name") or "").lower(),
            str(row.get("telegram_id") or ""),
        ),
    )
    lines = [f"Usuarios activos que expiran en los próximos 7 días: {len(rows)}"]
    current_expiry = None
    for row in rows:
        expiry = row.get("expiry_date") or "-"
        if expiry != current_expiry:
            lines.append(f"📅 {expiry}")
            current_expiry = expiry
        lines.append(
            "\n".join(
                [
                    f"- telegram_id: {row.get('telegram_id') or '-'}",
                    f"  username: {row.get('username') or '-'}",
                    f"  first_name: {row.get('first_name') or '-'}",
                    f"  expiry_date: {expiry}",
                    f"  days_remaining: {days_remaining(row.get('expiry_date'))}",
                    f"  renewal_notice_7d_sent_at: {row.get('renewal_notice_7d_sent_at') or '-'}",
                    f"  renewal_notice_3d_sent_at: {row.get('renewal_notice_3d_sent_at') or '-'}",
                    f"  renewal_notice_1d_sent_at: {row.get('renewal_notice_1d_sent_at') or '-'}",
                ]
            )
        )
    if not rows:
        lines.append("No hay usuarios activos expirando en los próximos 7 días.")
    await send_long_message(message, "\n\n".join(lines))


@router.message(Command("renewal_message_preview"))
async def renewal_message_preview(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(active_users_expiring_next_7_days, supabase)
    except Exception as exc:
        logger.exception("Could not fetch renewal message preview users")
        await message.answer(f"No pude consultar renovaciones próximas: {exc}")
        return

    lines = [f"Usuarios activos para recordatorio de renovación: {len(rows)}"]
    for row in rows:
        lines.append(
            "\n".join(
                [
                    f"telegram_id: {row.get('telegram_id') or '-'}",
                    f"username: {row.get('username') or '-'}",
                    f"first_name: {row.get('first_name') or '-'}",
                    f"expiry_date: {row.get('expiry_date') or '-'}",
                    f"days_remaining: {days_remaining(row.get('expiry_date'))}",
                ]
            )
        )
    if not rows:
        lines.append("No hay usuarios activos expirando en los próximos 7 días.")
    await send_long_message(message, "\n\n".join(lines))


@router.message(Command("renewal_message_confirm"))
async def renewal_message_confirm(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(active_users_expiring_next_7_days, supabase)
    except Exception as exc:
        logger.exception("Could not fetch renewal message users")
        await message.answer(f"No pude consultar renovaciones próximas: {exc}")
        return

    sent = 0
    failed_ids: list[str] = []
    for row in rows:
        telegram_id = row.get("telegram_id")
        if telegram_id is None:
            continue
        try:
            await message.bot.send_message(
                int(telegram_id),
                renewal_broadcast_text(row.get("expiry_date")),
            )
            await asyncio.to_thread(insert_renewal_message_recipient, supabase, row)
            sent += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not DM renewal message telegram_id=%s", telegram_id, exc_info=True)
            failed_ids.append(str(telegram_id))
        except Exception:
            logger.exception("Unexpected renewal message failure telegram_id=%s", telegram_id)
            failed_ids.append(str(telegram_id))

    lines = [
        f"Total users found: {len(rows)}",
        f"Messages sent: {sent}",
        f"Messages failed: {len(failed_ids)}",
        f"Failed telegram_ids: {', '.join(failed_ids) if failed_ids else '-'}",
    ]
    await send_long_message(message, "\n".join(lines))


@router.message(Command("renewal_message_status"))
async def renewal_message_status(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        rows = await asyncio.to_thread(latest_renewal_message_recipients, supabase)
    except Exception as exc:
        logger.exception("Could not fetch renewal message status")
        await message.answer(f"No pude consultar últimos recordatorios enviados: {exc}")
        return

    lines = [f"Últimos renewal_message_confirm exitosos: {len(rows)}"]
    for row in rows:
        lines.append(
            "\n".join(
                [
                    f"telegram_id: {row.get('telegram_id') or '-'}",
                    f"username: {row.get('username') or '-'}",
                    f"first_name: {row.get('first_name') or '-'}",
                    f"sent_at: {format_local_datetime(row.get('sent_at'))}",
                ]
            )
        )
    if not rows:
        lines.append("No hay envíos exitosos registrados todavía.")
    await send_long_message(message, "\n\n".join(lines))


@router.message(Command("prediction_results"))
async def prediction_results(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer("Uso: /prediction_results <game_code>")
        return
    game_code = parts[1].strip()
    scores = prediction_scores_for_game(game_code)
    if not scores:
        await message.answer("Juego no encontrado.")
        return
    rows = await asyncio.to_thread(prediction_votes_for_game, supabase, game_code)
    grouped: dict[str, list[dict[str, Any]]] = {score: [] for score in scores}
    for row in rows:
        grouped.setdefault(str(row.get("selected_score") or "-"), []).append(row)

    lines = [f"Resultados de pronóstico {game_code}: {len(rows)} votos"]
    for score, score_rows in grouped.items():
        lines.append(f"\n{score}: {len(score_rows)}")
        for row in score_rows:
            username = f"@{row.get('username')}" if row.get("username") else "-"
            lines.append(f"- {row.get('telegram_id')} | {username} | {row.get('first_name') or '-'}")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("prediction_winners"))
async def prediction_winners(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    try:
        parts = shlex.split(message.text or "")
    except ValueError:
        await message.answer('Uso: /prediction_winners mex_inglaterra "México 2-1 Inglaterra"')
        return
    if len(parts) < 3:
        await message.answer('Uso: /prediction_winners mex_inglaterra "México 2-1 Inglaterra"')
        return
    game_code = parts[1]
    score = " ".join(parts[2:])
    if not prediction_scores_for_game(game_code):
        await message.answer("Juego no encontrado.")
        return
    rows = await asyncio.to_thread(prediction_winner_rows, supabase, game_code, score)
    lines = [f"Ganadores {game_code} | {score}: {len(rows)}"]
    for row in rows:
        username = f"@{row.get('username')}" if row.get("username") else "-"
        lines.append(f"- {row.get('telegram_id')} | {username} | {row.get('first_name') or '-'}")
    if not rows:
        lines.append("Sin usuarios con ese pronóstico.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("send_prediction_winners_link"))
async def send_prediction_winners_link(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    try:
        parts = shlex.split(message.text or "")
    except ValueError:
        await message.answer('Uso: /send_prediction_winners_link mex_inglaterra "México 2-1 Inglaterra" mex_vs_inglaterra')
        return
    if len(parts) < 4:
        await message.answer('Uso: /send_prediction_winners_link mex_inglaterra "México 2-1 Inglaterra" mex_vs_inglaterra')
        return

    game_code = parts[1]
    channel_code_value = parts[-1]
    score = " ".join(parts[2:-1])
    if not prediction_scores_for_game(game_code):
        await message.answer("Juego no encontrado.")
        return
    channel = await asyncio.to_thread(get_access_channel_by_code, supabase, channel_code_value)
    if not channel:
        available_codes = await asyncio.to_thread(available_access_channel_codes, supabase, settings)
        await message.answer(f"Channel not found. Available active channel codes: {available_codes}")
        return
    telegram_chat_id = channel_telegram_chat_id(channel)
    if not telegram_chat_id:
        await message.answer(f"Canal {channel_code_value} no tiene telegram_chat_id configurado.")
        return

    rows = await asyncio.to_thread(prediction_winner_rows, supabase, game_code, score)
    sent = 0
    failed_ids: list[str] = []
    chat_id = parse_stored_chat_id(telegram_chat_id)
    for row in rows:
        telegram_id = int(row["telegram_id"])
        try:
            invite_link, _invite_name = await create_one_use_invite_link_for_chat(
                message.bot,
                chat_id,
                telegram_id,
                channel_code(channel),
            )
            await message.bot.send_message(
                telegram_id,
                f"Ganaste el pronóstico 🎉\n\nAquí está tu link de acceso: {invite_link}",
            )
            sent += 1
        except Exception:
            logger.exception("Could not send prediction winner link telegram_id=%s", telegram_id)
            failed_ids.append(str(telegram_id))

    summary = "\n".join(
        [
            f"Prediction winners link summary for {game_code}",
            f"Score: {score}",
            f"Channel: {channel_label(channel)} ({channel_code(channel)})",
            f"Total winners: {len(rows)}",
            f"Links sent: {sent}",
            f"Failed telegram_ids: {', '.join(failed_ids) if failed_ids else '-'}",
        ]
    )
    await message.bot.send_message(settings.admin_chat_id, summary)
    if message.chat.id != settings.admin_chat_id:
        await send_long_message(message, summary)


@router.message(Command("remove_expired_preview"))
async def remove_expired_preview(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    rows = await asyncio.to_thread(expired_active_users, supabase)
    lines = [f"Usuarios que serían removidos: {len(rows)}"]
    lines.extend(format_user(row) for row in rows)
    if not rows:
        lines.append("No hay usuarios para remover.")
    await send_long_message(message, "\n".join(lines))


@router.message(Command("remove_expired_confirm"))
async def remove_expired_confirm(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return
    rows = await asyncio.to_thread(expired_active_users, supabase)
    removed = 0
    errors: list[str] = []
    for row in rows:
        telegram_id = int(row["telegram_id"])
        try:
            await remove_user_from_channel(message.bot, supabase, settings, telegram_id, "expired_manual_confirm")
            removed += 1
        except Exception as exc:
            logger.exception("Could not remove expired telegram_id=%s", telegram_id)
            errors.append(f"{telegram_id}: {exc}")
    text = f"Removidos: {removed}/{len(rows)}"
    if errors:
        text += "\nErrores:\n" + "\n".join(errors[:10])
    await send_long_message(message, text)


@router.message(Command("sync_schema"))
async def sync_schema(message: Message, settings: Settings, supabase: Client) -> None:
    if not is_admin(message, settings):
        await reject_non_admin(message)
        return

    try:
        await asyncio.to_thread(run_schema_migration, supabase)
        await asyncio.to_thread(ensure_grupo_access_channel, supabase, settings)
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
async def want_more_content(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if callback_query.from_user and await asyncio.to_thread(
        should_ignore_blacklisted,
        supabase,
        settings,
        callback_query.from_user.id,
    ):
        return
    try:
        upsert_cta_user(supabase, callback_query)
        await callback_query.answer("Listo 🔥")
    except Exception:
        user_id = callback_query.from_user.id if callback_query.from_user else "unknown"
        logger.exception("Could not process CTA callback for user_id=%s", user_id)
        await callback_query.answer("Intenta de nuevo.", show_alert=False)


@router.callback_query(F.data == CONFIRM_SUBSCRIPTION_CALLBACK_DATA)
async def confirm_subscription(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if callback_query.from_user and await asyncio.to_thread(
        should_ignore_blacklisted,
        supabase,
        settings,
        callback_query.from_user.id,
    ):
        return
    try:
        upsert_confirmed_subscription_user(supabase, callback_query)
        await callback_query.answer("Suscripción confirmada ✅")
    except Exception:
        user_id = callback_query.from_user.id if callback_query.from_user else "unknown"
        logger.exception("Could not process subscription confirmation for user_id=%s", user_id)
        await callback_query.answer("Intenta de nuevo.", show_alert=False)


@router.callback_query(F.data.startswith("ask_channel:"))
async def ask_channel_selection(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    parts = (callback_query.data or "").split(":", maxsplit=2)
    if len(parts) != 3 or not callback_query.from_user:
        await callback_query.answer("Solicitud inválida.", show_alert=True)
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await callback_query.answer("Solicitud inválida.", show_alert=True)
        return
    if callback_query.from_user.id != telegram_id:
        await callback_query.answer("Solicitud inválida.", show_alert=True)
        return

    channel_key = parts[2]
    channel = await asyncio.to_thread(get_access_channel_by_code, supabase, channel_key)
    if not channel:
        available_codes = await asyncio.to_thread(available_access_channel_codes, supabase, settings)
        await callback_query.answer(f"Canal no disponible. Disponibles: {available_codes}", show_alert=True)
        return

    label = channel_label(channel)
    code = channel_code(channel)
    await callback_query.bot.send_message(
        settings.admin_chat_id,
        f"Usuario {telegram_id} seleccionó: {label} ({code})",
        reply_markup=build_send_selected_channel_link_keyboard(telegram_id, code),
    )
    await callback_query.answer("Selección enviada ✅")


@router.callback_query(F.data.startswith("send_channel_link:"))
async def send_selected_channel_link(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not is_admin_id(callback_query.from_user.id if callback_query.from_user else None, settings):
        await callback_query.answer("No autorizado.", show_alert=True)
        return

    parts = (callback_query.data or "").split(":", maxsplit=2)
    if len(parts) != 3:
        await callback_query.answer("Acción inválida.", show_alert=True)
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await callback_query.answer("Usuario inválido.", show_alert=True)
        return

    channel_key = parts[2]
    channel = await asyncio.to_thread(get_access_channel_by_code, supabase, channel_key)
    if not channel:
        available_codes = await asyncio.to_thread(available_access_channel_codes, supabase, settings)
        await callback_query.answer(f"Canal no disponible. Disponibles: {available_codes}", show_alert=True)
        return
    telegram_chat_id = channel_telegram_chat_id(channel)
    if not telegram_chat_id:
        logger.error("Selected channel missing telegram_chat_id: %s", channel)
        await callback_query.answer("Canal sin telegram_chat_id.", show_alert=True)
        return

    label = channel_label(channel)
    code = channel_code(channel)
    try:
        invite_link, invite_name = await create_one_use_invite_link_for_chat(
            callback_query.bot,
            parse_stored_chat_id(telegram_chat_id),
            telegram_id,
            code,
        )
    except Exception as exc:
        logger.exception("Could not create selected channel invite telegram_id=%s channel_code=%s", telegram_id, code)
        if callback_query.message:
            await callback_query.message.edit_text(f"No pude generar el link para {telegram_id}: {exc}")
        await callback_query.answer("No pude generar el link.", show_alert=True)
        return

    try:
        await callback_query.bot.send_message(
            telegram_id,
            f"Aquí está tu link de acceso a {label}: {invite_link}",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.warning("Could not DM selected channel invite telegram_id=%s", telegram_id, exc_info=True)
        if callback_query.message:
            await callback_query.message.edit_text(
                "No pude enviar el link. El usuario debe abrir el bot o escribirle primero."
            )
        await callback_query.answer("No pude enviar el link.", show_alert=True)
        return

    expires_at = None
    if channel_has_expiry(channel):
        expires_at = (datetime.now(APP_TIMEZONE).date() + timedelta(days=30)).isoformat()
    await asyncio.to_thread(
        save_user_channel_access,
        supabase,
        telegram_id,
        channel,
        invite_link,
        invite_name,
        expires_at,
    )
    if callback_query.message:
        await callback_query.message.edit_text(f"Link enviado a {telegram_id} para {label} ({code}).")
    await callback_query.answer("Link enviado ✅")


@router.callback_query(F.data.startswith("prediction:"))
async def prediction_vote(callback_query: CallbackQuery, supabase: Client) -> None:
    parts = (callback_query.data or "").split(":")
    if len(parts) != 3:
        await callback_query.answer("Pronóstico inválido.", show_alert=True)
        return
    game_code = parts[1]
    scores = prediction_scores_for_game(game_code)
    try:
        score_index = int(parts[2])
        selected_score = scores[score_index]
    except (ValueError, IndexError):
        await callback_query.answer("Pronóstico inválido.", show_alert=True)
        return

    try:
        await asyncio.to_thread(upsert_prediction_vote, supabase, game_code, callback_query, selected_score)
        await callback_query.answer("Tu pronóstico fue guardado ✅")
    except Exception:
        user_id = callback_query.from_user.id if callback_query.from_user else "unknown"
        logger.exception("Could not save prediction vote game_code=%s user_id=%s", game_code, user_id)
        await callback_query.answer("No pude guardar tu pronóstico.", show_alert=True)


@router.callback_query(F.data.startswith("raffle:"))
async def raffle_user_callback(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user:
        await callback_query.answer("Solicitud inválida.", show_alert=True)
        return
    parts = (callback_query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "start":
        raffle = await asyncio.to_thread(get_active_raffle, supabase)
        if not raffle:
            await callback_query.answer("No hay sorteo activo.", show_alert=True)
            return
        sent = await send_raffle_quantity_prompt(callback_query.bot, callback_query.from_user.id, raffle)
        if sent:
            await callback_query.answer("Te envié las opciones por privado ✅")
        else:
            await callback_query.answer("Abre el bot o escríbele primero para recibir tus boletos.", show_alert=True)
        return
    if action == "qty":
        if len(parts) != 4:
            await callback_query.answer("Cantidad inválida.", show_alert=True)
            return
        try:
            raffle_id = int(parts[2])
            quantity = int(parts[3])
        except ValueError:
            await callback_query.answer("Cantidad inválida.", show_alert=True)
            return
        if quantity < 1 or quantity > 5:
            await callback_query.answer("Cantidad inválida.", show_alert=True)
            return
        raffle = await asyncio.to_thread(get_raffle_by_id, supabase, raffle_id)
        if not raffle or raffle.get("status") != "active":
            await callback_query.answer("El sorteo ya no está activo.", show_alert=True)
            return
        try:
            rows = await asyncio.to_thread(reserve_raffle_tickets, supabase, raffle, callback_query.from_user, quantity)
        except ValueError as exc:
            await callback_query.answer(str(exc), show_alert=True)
            return
        except Exception as exc:
            logger.exception("Could not reserve raffle tickets")
            await callback_query.answer(f"No pude reservar boletos: {exc}", show_alert=True)
            return
        total = sum(int(row.get("amount_expected_mxn") or 0) for row in rows)
        text = (
            "🎟️ Tus boletos reservados son:\n\n"
            f"{format_raffle_numbers(rows)}\n\n"
            "Total a pagar:\n\n"
            f"${total} MXN\n\n"
            "Para bloquear definitivamente tus boletos,\n"
            "envía tu comprobante de pago."
        )
        if callback_query.message:
            await callback_query.message.answer(text)
        else:
            await callback_query.bot.send_message(callback_query.from_user.id, text)
        await callback_query.answer("Boletos reservados ✅")
        return
    await callback_query.answer("Acción inválida.", show_alert=True)


@router.callback_query(F.data.startswith("raffle_admin:"))
async def raffle_admin_callback(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not is_admin_id(callback_query.from_user.id if callback_query.from_user else None, settings):
        await callback_query.answer("No autorizado.", show_alert=True)
        return
    parts = (callback_query.data or "").split(":")
    if len(parts) < 3:
        await callback_query.answer("Acción inválida.", show_alert=True)
        return
    action = parts[1]
    rows: list[dict[str, Any]]
    telegram_id: int
    order_id = ""
    raffle_id = 0
    if action in {"confirm_user", "reject_user"}:
        if len(parts) != 4:
            await callback_query.answer("Acción inválida.", show_alert=True)
            return
        try:
            raffle_id = int(parts[2])
            telegram_id = int(parts[3])
        except ValueError:
            await callback_query.answer("Acción inválida.", show_alert=True)
            return
        rows = await asyncio.to_thread(get_reserved_raffle_tickets_for_user, supabase, raffle_id, telegram_id)
        if not rows:
            await callback_query.answer("No hay boletos reservados para confirmar.", show_alert=True)
            return
    else:
        order_id = parts[2]
        rows = await asyncio.to_thread(get_raffle_order, supabase, order_id)
        if not rows:
            await callback_query.answer("Orden no encontrada.", show_alert=True)
            return
        telegram_id = int(rows[0]["telegram_id"])
    if action == "confirm":
        confirmed_rows = await asyncio.to_thread(confirm_raffle_order, supabase, order_id, callback_query.from_user.id)
        confirmed_rows = [row for row in confirmed_rows if row.get("payment_status") == "confirmed"]
        if not confirmed_rows:
            await callback_query.answer("La orden ya no está reservada.", show_alert=True)
            return
        try:
            await callback_query.bot.send_message(
                telegram_id,
                "✅ Pago confirmado.\n\n"
                "Tus boletos oficiales son:\n\n"
                f"{format_raffle_numbers(confirmed_rows)}\n\n"
                "🍀 Mucha suerte.\n\n"
                "El ganador será anunciado el 30 de junio.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not DM raffle confirmation telegram_id=%s", telegram_id, exc_info=True)
        await callback_query.answer("Boletos confirmados ✅")
        if callback_query.message:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        return
    if action == "confirm_user":
        confirmed_rows = await asyncio.to_thread(confirm_reserved_raffle_tickets_for_user, supabase, raffle_id, telegram_id, callback_query.from_user.id)
        confirmed_rows = [row for row in confirmed_rows if row.get("payment_status") == "confirmed"]
        if not confirmed_rows:
            await callback_query.answer("La orden ya no está reservada.", show_alert=True)
            return
        try:
            await callback_query.bot.send_message(
                telegram_id,
                "✅ Pago confirmado.\n\n"
                "Tus boletos oficiales son:\n\n"
                f"{format_raffle_numbers(confirmed_rows)}\n\n"
                "🍀 Mucha suerte.\n\n"
                "El ganador será anunciado el 30 de junio.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not DM raffle confirmation telegram_id=%s", telegram_id, exc_info=True)
        await callback_query.answer("Boletos confirmados ✅")
        if callback_query.message:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        return
    if action == "reject":
        cancelled_rows = await asyncio.to_thread(cancel_raffle_order, supabase, order_id, callback_query.from_user.id)
        try:
            await callback_query.bot.send_message(
                telegram_id,
                "Tus boletos del sorteo fueron rechazados. Si necesitas ayuda, envía un nuevo comprobante.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not DM raffle rejection telegram_id=%s", telegram_id, exc_info=True)
        await delete_raffle_admin_messages(callback_query.bot, callback_query.message if isinstance(callback_query.message, Message) else None)
        logger.info("Raffle order rejected order_id=%s telegram_id=%s tickets=%s", order_id, telegram_id, len(cancelled_rows))
        await callback_query.answer("Boletos rechazados ❌")
        return
    if action == "reject_user":
        cancelled_rows = await asyncio.to_thread(cancel_reserved_raffle_tickets_for_user, supabase, raffle_id, telegram_id, callback_query.from_user.id)
        try:
            await callback_query.bot.send_message(
                telegram_id,
                "Tus boletos del sorteo fueron rechazados. Si necesitas ayuda, envía un nuevo comprobante.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Could not DM raffle rejection telegram_id=%s", telegram_id, exc_info=True)
        await delete_raffle_admin_messages(callback_query.bot, callback_query.message if isinstance(callback_query.message, Message) else None)
        logger.info("Raffle tickets rejected raffle_id=%s telegram_id=%s tickets=%s", raffle_id, telegram_id, len(cancelled_rows))
        await callback_query.answer("Boletos rechazados ❌")
        return
    await callback_query.answer("Acción inválida.", show_alert=True)


@router.callback_query(F.data.startswith("payment:"))
async def payment_admin_callback(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if callback_query.from_user and await asyncio.to_thread(
        should_ignore_blacklisted,
        supabase,
        settings,
        callback_query.from_user.id,
    ):
        return
    if not is_admin_id(callback_query.from_user.id if callback_query.from_user else None, settings):
        await callback_query.answer("No autorizado.", show_alert=True)
        return
    parts = (callback_query.data or "").split(":")
    if len(parts) < 3:
        await callback_query.answer("Acción inválida.", show_alert=True)
        return
    action = parts[1]
    try:
        telegram_id = int(parts[2])
    except ValueError:
        await callback_query.answer("Usuario inválido.", show_alert=True)
        return

    try:
        if action == "toggle":
            if len(parts) not in {4, 5}:
                await callback_query.answer("Acción inválida.", show_alert=True)
                return
            key = parts[-1]
            selection_key = payment_selection_key(callback_query, telegram_id)
            selected = set(PAYMENT_CHANNEL_SELECTIONS.get(selection_key, set())) if selection_key else set()
            if len(parts) == 5 and not selected:
                selected = selected_channel_keys_from_raw(parts[3])
            channels = await asyncio.to_thread(get_access_channels, supabase, settings)
            available_keys = {channel_code(channel) for channel in channels}
            if key not in available_keys:
                await callback_query.answer("Canal no disponible.", show_alert=True)
                return
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
            if selection_key:
                PAYMENT_CHANNEL_SELECTIONS[selection_key] = selected
            await callback_query.message.edit_reply_markup(
                reply_markup=await asyncio.to_thread(
                    pending_payment_keyboard,
                    supabase,
                    settings,
                    telegram_id,
                    selected,
                )
            )
            await callback_query.answer("Selección actualizada")
        elif action == "approve":
            selection_key = payment_selection_key(callback_query, telegram_id)
            selected = set(PAYMENT_CHANNEL_SELECTIONS.get(selection_key, set())) if selection_key else set()
            if len(parts) >= 4 and not selected:
                selected = selected_channel_keys_from_raw(parts[3])
            if not selected:
                await callback_query.answer("Select at least one channel before approving.", show_alert=True)
                return
            result = await approve_payment(
                callback_query.bot,
                supabase,
                settings,
                telegram_id,
                callback_query.from_user.id,
                selected,
            )
            if result.get("duplicate"):
                await callback_query.answer("Ya estaba aprobado; reenvié el link existente.", show_alert=True)
                summary = "✅ APROBADO (ya existía) — link reenviado"
            else:
                await callback_query.answer("Aprobado ✅")
                labels = ", ".join(item["label"] for item in result.get("channel_links", []))
                summary = f"✅ APROBADO — Enviado a: {labels}" if labels else "✅ APROBADO"
            if selection_key:
                PAYMENT_CHANNEL_SELECTIONS.pop(selection_key, None)
            try:
                original_text = callback_query.message.text or ""
                await callback_query.message.edit_text(
                    f"{original_text}\n\n{summary}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                )
            except Exception:
                logger.warning("Could not clean up approved payment message telegram_id=%s", telegram_id, exc_info=True)
        elif action == "reject":
            await reject_payment(callback_query.bot, supabase, settings, telegram_id, callback_query.from_user.id)
            selection_key = payment_selection_key(callback_query, telegram_id)
            if selection_key:
                PAYMENT_CHANNEL_SELECTIONS.pop(selection_key, None)
            await delete_pending_payment_admin_messages(callback_query.bot, selection_key)
            await callback_query.answer("Rechazado ❌")
        elif action == "ask_receipt":
            await ask_new_receipt(callback_query.bot, supabase, settings, telegram_id, callback_query.from_user.id)
            selection_key = payment_selection_key(callback_query, telegram_id)
            if selection_key:
                PAYMENT_CHANNEL_SELECTIONS.pop(selection_key, None)
            await callback_query.answer("Solicitud enviada 🔁")
        elif action == "confirm_renewal":
            sent = await send_renewal_confirmation(callback_query.bot, telegram_id)
            if sent:
                await callback_query.bot.send_message(
                    settings.admin_chat_id,
                    f"Renovación confirmada para {telegram_id} ✅",
                )
                await callback_query.answer("Confirmación enviada ✅")
            else:
                await callback_query.bot.send_message(
                    settings.admin_chat_id,
                    f"No pude confirmar renovación para {telegram_id}. El usuario debe abrir el bot o escribirle primero.",
                )
                await callback_query.answer(
                    "No pude enviar la confirmación. El usuario debe abrir el bot o escribirle primero.",
                    show_alert=True,
                )
        else:
            await callback_query.answer("Acción inválida.", show_alert=True)
            return
    except Exception as exc:
        logger.exception("Payment admin action failed action=%s telegram_id=%s", action, telegram_id)
        await callback_query.answer(f"Error: {exc}", show_alert=True)


@router.callback_query(F.data == "cart:join_grupo")
async def cart_join_grupo(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    await asyncio.to_thread(add_cart_item, supabase, telegram_id, GRUPO_CHANNEL_KEY)
    await callback_query.answer()
    await callback_query.message.edit_text(
        "Perfecto bebé, el Grupo ya quedó en tu carrito 💎\n\n¿Qué más te gustaría agregar?",
        reply_markup=build_category_picker_keyboard(),
    )


@router.callback_query(F.data.startswith("cart:category:"))
async def cart_show_category(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    category = callback_query.data.split(":", 2)[2]
    if category not in CART_CATEGORIES:
        await callback_query.answer()
        return
    existing_user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
    if not await can_browse_cart_catalog(supabase, telegram_id, existing_user):
        await callback_query.answer("Primero necesitas el Grupo Exclusivo bebé 💎", show_alert=True)
        return
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    category_channels = channels_in_category(channels, category)
    await callback_query.answer()
    if not category_channels:
        await callback_query.message.answer(f"{CART_CATEGORIES[category]}: aún no hay sets disponibles.")
        return
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    channel = category_channels[0]
    keyboard = build_carousel_keyboard(category, 0, len(category_channels), channel, cart_keys)
    photo = channel_photo_file_id(channel)
    if photo:
        await callback_query.message.answer_photo(photo, caption=carousel_caption(channel), reply_markup=keyboard)
    else:
        await callback_query.message.answer(carousel_caption(channel), reply_markup=keyboard)


@router.callback_query(F.data.startswith("carousel:nav:"))
async def carousel_nav(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    parts = callback_query.data.split(":")
    if len(parts) != 4:
        await callback_query.answer()
        return
    category = parts[2]
    try:
        index = int(parts[3])
    except ValueError:
        await callback_query.answer()
        return
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    category_channels = channels_in_category(channels, category)
    if not (0 <= index < len(category_channels)):
        await callback_query.answer()
        return
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    channel = category_channels[index]
    keyboard = build_carousel_keyboard(category, index, len(category_channels), channel, cart_keys)
    photo = channel_photo_file_id(channel)
    await callback_query.answer()
    if photo:
        await callback_query.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=carousel_caption(channel)),
            reply_markup=keyboard,
        )
    else:
        await callback_query.message.edit_caption(caption=carousel_caption(channel), reply_markup=keyboard)


@router.callback_query(F.data.startswith("carousel:toggle:"))
async def carousel_toggle(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    parts = callback_query.data.split(":")
    if len(parts) != 4:
        await callback_query.answer()
        return
    category = parts[2]
    try:
        index = int(parts[3])
    except ValueError:
        await callback_query.answer()
        return
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    category_channels = channels_in_category(channels, category)
    if not (0 <= index < len(category_channels)):
        await callback_query.answer()
        return
    channel = category_channels[index]
    code = channel_code(channel)
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    if code in cart_keys:
        await asyncio.to_thread(remove_cart_item, supabase, telegram_id, code)
        cart_keys.discard(code)
        await callback_query.answer("Quitado del carrito")
    else:
        await asyncio.to_thread(add_cart_item, supabase, telegram_id, code)
        cart_keys.add(code)
        await callback_query.answer("Agregado al carrito ✅")
    keyboard = build_carousel_keyboard(category, index, len(category_channels), channel, cart_keys)
    await callback_query.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(F.data == "cart:view")
async def cart_view(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    selected = cart_channels(channels, cart_keys)
    await callback_query.answer()
    if not selected:
        await callback_query.message.edit_text(
            "Tu carrito está vacío bebé.",
            reply_markup=build_category_picker_keyboard(),
        )
        return
    await callback_query.message.edit_text(
        cart_summary_text(selected),
        reply_markup=build_cart_summary_keyboard(selected),
    )


@router.callback_query(F.data.startswith("cart:remove:"))
async def cart_remove_item(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    code = callback_query.data.split(":", 2)[2]
    await asyncio.to_thread(remove_cart_item, supabase, telegram_id, code)
    await callback_query.answer("Quitado del carrito")
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    selected = cart_channels(channels, cart_keys)
    if not selected:
        await callback_query.message.edit_text(
            "Tu carrito está vacío bebé.",
            reply_markup=build_category_picker_keyboard(),
        )
        return
    await callback_query.message.edit_text(
        cart_summary_text(selected),
        reply_markup=build_cart_summary_keyboard(selected),
    )


@router.callback_query(F.data == "cart:checkout")
async def cart_checkout(callback_query: CallbackQuery, settings: Settings, supabase: Client) -> None:
    if not callback_query.from_user or not callback_query.message:
        return
    telegram_id = callback_query.from_user.id
    channels = await asyncio.to_thread(get_access_channels, supabase, settings)
    cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
    selected = cart_channels(channels, cart_keys)
    await callback_query.answer()
    if not selected:
        await callback_query.message.edit_text(
            "Tu carrito está vacío bebé.",
            reply_markup=build_category_picker_keyboard(),
        )
        return
    subtotal, discount, total = cart_discount(selected)
    discount_line = (
        f"Descuento por volumen aplicado: -${discount:.0f} MXN 🎉\n\n" if discount > 0 else ""
    )
    await callback_query.message.edit_text(
        f"Total a pagar: ${total:.0f} MXN\n\n"
        f"{discount_line}"
        f"{CART_PAYMENT_INFO}\n\n"
        "Manda tu comprobante de pago aquí mismo (foto o PDF) y en cuanto lo validemos te llegan tus links 🔓"
    )


@router.chat_member()
async def track_channel_membership(update: ChatMemberUpdated, bot: Bot, settings: Settings, supabase: Client) -> None:
    access_channel = await asyncio.to_thread(
        find_access_channel_for_chat,
        supabase,
        settings,
        update.chat.id,
        update.chat.username,
    )
    channel_matches = bool(access_channel)
    if not channel_matches:
        return

    user = update.new_chat_member.user
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status
    now = now_utc_iso()
    active_statuses = {"member", "administrator", "creator"}
    left_statuses = {"left", "kicked"}
    payload = {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "last_seen_at": now,
    }
    if new_status in active_statuses and old_status not in active_statuses:
        if await asyncio.to_thread(is_blacklisted_user, supabase, user.id):
            await bot.ban_chat_member(chat_id=update.chat.id, user_id=user.id)
            await bot.send_message(
                settings.admin_chat_id,
                f"Blacklisted user removed from {update.chat.title or update.chat.id}: {user.id}",
            )
            return

        payload.update(
            {
                "joined_channel_at": now,
                "status": "active",
                "source": "channel_join",
                "invite_link_used": True,
            }
        )
        invite_link_value = update.invite_link.invite_link if update.invite_link else None
        if invite_link_value:
            manual_link = await asyncio.to_thread(get_manual_invite_by_link, supabase, invite_link_value)
            if manual_link:
                await asyncio.to_thread(mark_manual_invite_used, supabase, invite_link_value, user.id)
                await asyncio.to_thread(
                    upsert_user_payload,
                    supabase,
                    user.id,
                    payload,
                )
                await asyncio.to_thread(
                    save_user_channel_access,
                    supabase,
                    user.id,
                    access_channel,
                    invite_link_value,
                    manual_link.get("invite_link_name") or "",
                    None,
                )
                username = f"@{user.username}" if user.username else "(sin username)"
                await bot.send_message(
                    settings.admin_chat_id,
                    f"Manual invite used by {username} ({user.id})",
                )
                logger.info(
                    "Manual invite link used telegram_id=%s channel=%s",
                    user.id,
                    channel_code(access_channel),
                )
                return
            expected_telegram_id = await asyncio.to_thread(
                find_payment_history_recipient_by_link, supabase, invite_link_value
            )
            username = f"@{user.username}" if user.username else "(sin username)"
            if expected_telegram_id is None:
                verdict = f"ℹ️ Link usado por telegram_id: {user.id} (no encontré a quién se le generó)"
            elif expected_telegram_id == user.id:
                verdict = f"✅ Link usado correctamente — telegram_id: {user.id}"
            else:
                verdict = (
                    f"⚠️ POSIBLE LINK COMPARTIDO — se generó para {expected_telegram_id}, "
                    f"pero lo usó {user.id}"
                )
            await bot.send_message(
                settings.admin_chat_id,
                f"{verdict}\nCanal: {channel_label(access_channel)}\nUsuario: {username}",
            )
    elif new_status in left_statuses:
        existing = await asyncio.to_thread(get_registered_user, supabase, user.id)
        current = bool(existing and existing.get("payment_status") == "paid" and days_remaining(existing.get("expiry_date")) is not None and days_remaining(existing.get("expiry_date")) >= 0)
        payload.update(
            {
                "left_channel_at": now,
                "notes": "Left channel or removed",
            }
        )
        if not current:
            payload["status"] = "inactive"
    else:
        return
    await asyncio.to_thread(upsert_user_payload, supabase, user.id, payload)
    logger.info("Tracked channel membership telegram_id=%s old=%s new=%s", user.id, old_status, new_status)


@router.my_chat_member()
async def track_bot_channel_membership(update: ChatMemberUpdated, settings: Settings) -> None:
    channel_matches = update.chat.id == settings.content_channel_id
    if isinstance(settings.content_channel_id, str):
        channel_matches = update.chat.username and f"@{update.chat.username}" == settings.content_channel_id
    if channel_matches:
        logger.info(
            "Bot membership changed in content channel old=%s new=%s",
            update.old_chat_member.status,
            update.new_chat_member.status,
        )


@router.error()
async def handle_error(event: ErrorEvent) -> None:
    logger.exception("Unhandled update error: %s", event.exception)


def get_bot_state(supabase: Client, key: str) -> str | None:
    try:
        response = (
            supabase.table("bot_state")
            .select("value")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0].get("value")
    except Exception:
        logger.warning("Could not read bot_state key=%s", key, exc_info=True)
    return None


def set_bot_state(supabase: Client, key: str, value: str) -> None:
    try:
        (
            supabase.table("bot_state")
            .upsert({"key": key, "value": value, "updated_at": now_utc_iso()}, on_conflict="key")
            .execute()
        )
    except Exception:
        logger.warning("Could not write bot_state key=%s", key, exc_info=True)


DAILY_NOTICE_STATE_KEY = "last_daily_notice_date"


async def run_daily_notice_if_needed(bot: Bot, supabase: Client, settings: Settings) -> None:
    """Runs notify_expiring_today at most once per calendar day (Mexico City).

    Called both from the 09:00 cron job and once at bot startup, so a missed
    9am run (e.g. Railway restarted the process around that time) still gets
    caught the same day instead of silently skipping that day's reminders.
    Guarded by bot_state so repeated restarts on the same day don't resend.
    """
    today = today_iso()
    last_run = await asyncio.to_thread(get_bot_state, supabase, DAILY_NOTICE_STATE_KEY)
    if last_run == today:
        logger.info("Daily renewal notice already sent today (%s); skipping", today)
        return
    await notify_expiring_today(bot, supabase, settings)
    await asyncio.to_thread(set_bot_state, supabase, DAILY_NOTICE_STATE_KEY, today)


async def send_cart_abandonment_reminders(bot: Bot, supabase: Client, settings: Settings) -> None:
    try:
        stale_ids = await asyncio.to_thread(get_stale_cart_telegram_ids, supabase, 24 * 60)
        if not stale_ids:
            return
        already = await asyncio.to_thread(already_reminded_telegram_ids, supabase, stale_ids)
        pending = await asyncio.to_thread(pending_review_telegram_ids, supabase, stale_ids)
        candidates = [tid for tid in stale_ids if tid not in already and tid not in pending]
        if not candidates:
            return
        channels = await asyncio.to_thread(get_access_channels, supabase, settings)
        sent = 0
        for telegram_id in candidates:
            cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
            selected = cart_channels(channels, cart_keys)
            if not selected:
                await asyncio.to_thread(mark_cart_reminded, supabase, telegram_id)
                continue
            text = (
                "Hola bebé 💕 vi que dejaste algo en tu carrito...\n\n"
                + cart_summary_text(selected)
                + "\n\n¿Seguimos? Dale a Confirmar y pagar cuando quieras 🔓"
            )
            try:
                await bot.send_message(telegram_id, text, reply_markup=build_cart_summary_keyboard(selected))
                sent += 1
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.warning("Could not DM cart reminder telegram_id=%s", telegram_id, exc_info=True)
            except Exception:
                logger.exception("Unexpected cart reminder failure telegram_id=%s", telegram_id)
            await asyncio.to_thread(mark_cart_reminded, supabase, telegram_id)
        if sent:
            logger.info("Sent %s cart abandonment reminders", sent)
    except Exception:
        logger.exception("Cart abandonment reminder job failed")


async def notify_expiring_today(bot: Bot, supabase: Client, settings: Settings) -> None:
    today = datetime.now(APP_TIMEZONE).date()
    try:
        sections: list[str] = []
        for notice_day in settings.renewal_notice_days:
            target = (today + timedelta(days=notice_day)).isoformat()
            column = f"renewal_notice_{notice_day}d_sent_at"
            rows = await asyncio.to_thread(fetch_users_for_notice_day, supabase, target, column)
            if rows:
                sections.append(f"Expiran en {notice_day} días ({target}): {len(rows)}")
                sections.extend(format_user(row) for row in rows)
                sent_ids: list[int] = []
                failed_ids: list[str] = []
                for row in rows:
                    telegram_id = row.get("telegram_id")
                    if telegram_id is None:
                        failed_ids.append("-")
                        continue
                    try:
                        await bot.send_message(
                            int(telegram_id),
                            scheduled_renewal_notice_text(row.get("expiry_date")),
                        )
                        sent_ids.append(int(telegram_id))
                    except (TelegramBadRequest, TelegramForbiddenError):
                        logger.warning(
                            "Could not DM scheduled renewal notice telegram_id=%s notice_day=%s",
                            telegram_id,
                            notice_day,
                            exc_info=True,
                        )
                        failed_ids.append(str(telegram_id))
                    except Exception:
                        logger.exception(
                            "Unexpected scheduled renewal notice failure telegram_id=%s notice_day=%s",
                            telegram_id,
                            notice_day,
                        )
                        failed_ids.append(str(telegram_id))

                if sent_ids:
                    await asyncio.to_thread(mark_notice_sent, supabase, column, sent_ids)
                sections.append(f"DMs enviados para aviso {notice_day}d: {len(sent_ids)}/{len(rows)}")
                if failed_ids:
                    sections.append(f"Fallidos aviso {notice_day}d: {', '.join(failed_ids)}")

        expired_rows = await asyncio.to_thread(expired_active_users, supabase)
        sections.append(f"Usuarios activos expirados: {len(expired_rows)}")
        sections.extend(format_user(row) for row in expired_rows)

        if settings.auto_remove_expired and expired_rows:
            removed = 0
            for row in expired_rows:
                try:
                    await remove_user_from_channel(
                        bot,
                        supabase,
                        settings,
                        int(row["telegram_id"]),
                        "expired_auto_remove",
                    )
                    removed += 1
                except Exception:
                    logger.exception("Auto remove failed telegram_id=%s", row.get("telegram_id"))
            sections.append(f"AUTO_REMOVE_EXPIRED=true, removidos: {removed}/{len(expired_rows)}")
        elif expired_rows:
            sections.append("AUTO_REMOVE_EXPIRED=false, no se removió a nadie.")

        text = "\n".join(sections) if sections else f"Sin avisos de renovación para {today.isoformat()}."
        await bot.send_message(settings.admin_chat_id, text[:3900])
        logger.info("Sent daily renewal notification")
    except Exception:
        logger.exception("Could not send daily renewal notification")


async def run_telegram_bot(bot: Bot, supabase: Client, settings: Settings) -> None:
    dp = Dispatcher()
    blacklist_middleware = BlacklistMiddleware()
    router.message.outer_middleware(blacklist_middleware)
    router.callback_query.outer_middleware(blacklist_middleware)
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    scheduler.add_job(
        run_daily_notice_if_needed,
        CronTrigger(hour=9, minute=0, timezone=APP_TIMEZONE),
        args=[bot, supabase, settings],
        id="daily_expiry_notification",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_cart_abandonment_reminders,
        IntervalTrigger(hours=1),
        args=[bot, supabase, settings],
        id="cart_abandonment_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()

    asyncio.create_task(
        run_daily_notice_if_needed(bot, supabase, settings),
        name="daily-notice-startup-catchup",
    )

    logger.info("Starting Telegram bot polling")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            settings=settings,
            supabase=supabase,
            fsm_manager=dp.fsm,
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


def dashboard_redirect(
    user_filter: str = "all",
    search: str = "",
    page: int = 1,
    message: str | None = None,
    error: str | None = None,
    invite_link: str | None = None,
) -> RedirectResponse:
    params: dict[str, Any] = {"filter": user_filter, "page": page}
    if search:
        params["search"] = search
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    if invite_link:
        params["invite_link"] = invite_link
    return RedirectResponse(url=f"/dashboard?{urlencode(params)}", status_code=303)


def create_web_app(settings: Settings, supabase: Client, bot: Bot) -> FastAPI:
    templates = Jinja2Templates(directory="templates")
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key=f"{settings.bot_token}:{settings.admin_password}",
        same_site="lax",
        https_only=bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_NAME")),
    )

    def is_logged_in(request: Request) -> bool:
        return bool(request.session.get("admin_authenticated"))

    @app.get("/health", response_model=None)
    async def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, response_model=None)
    async def root(request: Request):
        if is_logged_in(request):
            return RedirectResponse(url="/dashboard", status_code=303)
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse, response_model=None)
    async def login_page(request: Request):
        if is_logged_in(request):
            return RedirectResponse(url="/dashboard", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})

    @app.post("/login", response_model=None)
    async def login(request: Request, password: str = Form(...)):
        if secrets.compare_digest(password, settings.admin_password):
            request.session["admin_authenticated"] = True
            return RedirectResponse(url="/dashboard?message=Login%20successful", status_code=303)

        logger.warning("Failed dashboard login")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Invalid password"},
            status_code=401,
        )

    @app.post("/logout", response_model=None)
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse, response_model=None)
    async def dashboard(
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
        message: str | None = None,
        error: str | None = None,
        invite_link: str | None = None,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)

        safe_filter = (
            filter
            if filter
            in {
                "all",
                "active",
                "pending_payments",
                "paid",
                "needs_new_receipt",
                "rejected",
                "removed_inactive",
                "confirmed",
                "not_confirmed",
                "source_confirm_subscription",
                "expiring_7",
                "expired",
                "no_expiry",
                "has_payment_history",
            }
            else "all"
        )
        try:
            page_data = await asyncio.to_thread(list_dashboard_users, supabase, safe_filter, search, page)
        except Exception as exc:
            logger.exception("Could not load dashboard users")
            page_data = {
                "rows": [],
                "total": 0,
                "page": 1,
                "per_page": 25,
                "total_pages": 1,
                "has_previous": False,
                "has_next": False,
            }
            error = f"Could not load users: {exc}"

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "users": page_data["rows"],
                "active_filter": safe_filter,
                "search": search,
                "page": page_data["page"],
                "per_page": page_data["per_page"],
                "total_users": page_data["total"],
                "total_pages": page_data["total_pages"],
                "has_previous": page_data["has_previous"],
                "has_next": page_data["has_next"],
                "message": message,
                "error": error,
                "invite_link": invite_link,
                "today": today_iso(),
            },
        )

    @app.post("/dashboard/users/{telegram_id}/renew/today", response_model=None)
    async def dashboard_renew_today(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            expiry = await asyncio.to_thread(renew_user_from_today, supabase, telegram_id)
            return dashboard_redirect(
                filter,
                search,
                page,
                message=f"Renewed from today. New expiry: {expiry} for {telegram_id}.",
            )
        except Exception as exc:
            logger.exception("Could not renew from today for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not renew user: {exc}")

    @app.post("/dashboard/users/{telegram_id}/renew/current-expiry", response_model=None)
    async def dashboard_renew_current_expiry(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            expiry = await asyncio.to_thread(renew_user_from_current_expiry, supabase, telegram_id)
            return dashboard_redirect(
                filter,
                search,
                page,
                message=f"Renewed from current expiry_date. New expiry: {expiry} for {telegram_id}.",
            )
        except Exception as exc:
            logger.exception("Could not renew from current expiry for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not renew from current expiry_date: {exc}")

    @app.post("/dashboard/users/{telegram_id}/confirm-renewal", response_model=None)
    async def dashboard_confirm_renewal(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        sent = await send_renewal_confirmation(bot, telegram_id)
        if sent:
            return dashboard_redirect(
                filter,
                search,
                page,
                message=f"Confirmación de renovación enviada a {telegram_id}.",
            )
        return dashboard_redirect(
            filter,
            search,
            page,
            error="No pude enviar la confirmación. El usuario debe abrir el bot o escribirle primero.",
        )

    @app.post("/dashboard/users/{telegram_id}/paid", response_model=None)
    async def dashboard_mark_paid(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(mark_user_paid, supabase, telegram_id)
            return dashboard_redirect(filter, search, page, message=f"User {telegram_id} marked paid.")
        except Exception as exc:
            logger.exception("Could not mark paid telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not mark paid: {exc}")

    @app.post("/dashboard/users/{telegram_id}/membership-start", response_model=None)
    async def dashboard_set_membership_start(
        telegram_id: int,
        request: Request,
        membership_start_date: str = Form(...),
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            expiry = await asyncio.to_thread(
                set_membership_start_date,
                supabase,
                telegram_id,
                membership_start_date,
            )
            return dashboard_redirect(
                filter,
                search,
                page,
                message=f"Membership start updated. New expiry: {expiry} for {telegram_id}.",
            )
        except Exception as exc:
            logger.exception("Could not set membership start for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not set membership start date: {exc}")

    @app.post("/dashboard/users/{telegram_id}/approve-payment", response_model=None)
    async def dashboard_approve_payment(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            cart_keys = await asyncio.to_thread(get_cart_channel_keys, supabase, telegram_id)
            result = await approve_payment(
                bot,
                supabase,
                settings,
                telegram_id,
                next(iter(settings.admin_user_ids)),
                {GRUPO_CHANNEL_KEY} | cart_keys,
            )
            if result.get("duplicate"):
                return dashboard_redirect(filter, search, page, message=f"Payment was already approved recently; existing link resent for {telegram_id}.")
            return dashboard_redirect(filter, search, page, message=f"Payment approved for {telegram_id}.")
        except Exception as exc:
            logger.exception("Dashboard approve failed telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not approve payment: {exc}")

    @app.post("/dashboard/users/{telegram_id}/reject-payment", response_model=None)
    async def dashboard_reject_payment(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        await reject_payment(bot, supabase, settings, telegram_id, next(iter(settings.admin_user_ids)))
        return dashboard_redirect(filter, search, page, message=f"Payment rejected for {telegram_id}.")

    @app.post("/dashboard/users/{telegram_id}/ask-receipt", response_model=None)
    async def dashboard_ask_receipt(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        await ask_new_receipt(bot, supabase, settings, telegram_id, next(iter(settings.admin_user_ids)))
        return dashboard_redirect(filter, search, page, message=f"Requested another receipt from {telegram_id}.")

    @app.post("/dashboard/users/{telegram_id}/confirmed", response_model=None)
    async def dashboard_mark_confirmed(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(set_confirmation_status, supabase, telegram_id, True)
            return dashboard_redirect(filter, search, page, message=f"User {telegram_id} marked confirmed.")
        except Exception as exc:
            logger.exception("Could not mark confirmed telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not mark confirmed: {exc}")

    @app.post("/dashboard/users/{telegram_id}/not-confirmed", response_model=None)
    async def dashboard_mark_not_confirmed(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(set_confirmation_status, supabase, telegram_id, False)
            return dashboard_redirect(filter, search, page, message=f"User {telegram_id} marked not confirmed.")
        except Exception as exc:
            logger.exception("Could not mark not confirmed telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not mark not confirmed: {exc}")

    @app.post("/dashboard/users/{telegram_id}/inactive", response_model=None)
    async def dashboard_mark_inactive(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await asyncio.to_thread(mark_user_inactive, supabase, telegram_id)
            return dashboard_redirect(filter, search, page, message=f"User {telegram_id} marked inactive.")
        except Exception as exc:
            logger.exception("Could not mark inactive telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not mark inactive: {exc}")

    @app.post("/dashboard/users/{telegram_id}/invite", response_model=None)
    async def dashboard_invite(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            invite_link = await create_invite_if_no_active(bot, supabase, settings, telegram_id)
            return dashboard_redirect(
                filter,
                search,
                page,
                message=f"One-use invite link generated for {telegram_id}.",
                invite_link=invite_link,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.exception("Could not create invite link for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not create invite link: {exc}")
        except Exception as exc:
            logger.exception("Unexpected invite link error for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=str(exc))

    @app.post("/dashboard/users/{telegram_id}/revoke-current-invite", response_model=None)
    async def dashboard_revoke_current_invite(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            revoked = await revoke_invite_for_user(
                bot,
                supabase,
                settings,
                telegram_id,
                "Invite link revoked from dashboard",
                clear_link=True,
            )
            if not revoked:
                return dashboard_redirect(filter, search, page, error="No invite link found.")
            return dashboard_redirect(filter, search, page, message=f"Invite link revoked for {telegram_id}.")
        except Exception as exc:
            logger.exception("Dashboard revoke invite failed telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not revoke invite link: {exc}")

    @app.post("/dashboard/users/{telegram_id}/send-existing-invite", response_model=None)
    async def dashboard_send_existing_invite(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            await create_or_send_existing_invite(bot, supabase, settings, telegram_id)
            return dashboard_redirect(filter, search, page, message=f"Invite send attempted for {telegram_id}.")
        except Exception as exc:
            logger.exception("Dashboard send invite failed telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not send invite: {exc}")

    @app.get("/dashboard/users/{telegram_id}/history", response_class=HTMLResponse, response_model=None)
    async def dashboard_payment_history(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
            rows = await asyncio.to_thread(get_payment_history, supabase, telegram_id, None)
            return templates.TemplateResponse(
                request,
                "payment_history.html",
                {
                    "request": request,
                    "user": user or {"telegram_id": telegram_id},
                    "history": rows,
                    "active_filter": filter,
                    "search": search,
                    "page": page,
                },
            )
        except Exception as exc:
            logger.exception("Could not load payment history telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not load payment history: {exc}")

    @app.get("/dashboard/payments", response_class=HTMLResponse, response_model=None)
    async def dashboard_payments(
        request: Request,
        search: str = "",
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            rows = await asyncio.to_thread(list_approved_payments, supabase, search)
            return templates.TemplateResponse(
                request,
                "payment_history.html",
                {
                    "request": request,
                    "payments_page": True,
                    "history": rows,
                    "search": search,
                    "active_filter": "all",
                    "page": 1,
                },
            )
        except Exception as exc:
            logger.exception("Could not load approved payments")
            return dashboard_redirect("all", error=f"Could not load approved payments: {exc}")

    @app.get("/dashboard/payments/file", response_model=None)
    async def dashboard_payment_file(
        request: Request,
        file_id: str,
    ):
        if not is_logged_in(request):
            return Response(status_code=403)
        try:
            telegram_file = await bot.get_file(file_id)
            if not telegram_file.file_path:
                return Response(status_code=404)
            buffer = BytesIO()
            await bot.download_file(telegram_file.file_path, destination=buffer)
            path = telegram_file.file_path.lower()
            media_type = "image/jpeg"
            if path.endswith(".png"):
                media_type = "image/png"
            elif path.endswith(".webp"):
                media_type = "image/webp"
            elif path.endswith(".pdf"):
                media_type = "application/pdf"
            return Response(content=buffer.getvalue(), media_type=media_type)
        except Exception:
            logger.warning("Could not proxy Telegram payment receipt file", exc_info=True)
            return Response(status_code=404)

    @app.get("/dashboard/users/{telegram_id}/remove", response_class=HTMLResponse, response_model=None)
    async def dashboard_remove_confirm(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=303)
        try:
            user = await asyncio.to_thread(get_registered_user, supabase, telegram_id)
            if not user:
                return dashboard_redirect(filter, search, page, error=f"User {telegram_id} not found.")
            return templates.TemplateResponse(
                request,
                "confirm_remove.html",
                {
                    "request": request,
                    "user": user,
                    "active_filter": filter,
                    "search": search,
                    "page": page,
                },
            )
        except Exception as exc:
            logger.exception("Could not load remove confirmation for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not load confirmation: {exc}")

    @app.post("/dashboard/users/{telegram_id}/remove/confirm", response_model=None)
    async def dashboard_remove_confirmed(
        telegram_id: int,
        request: Request,
        filter: str = "all",
        search: str = "",
        page: int = 1,
    ):
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
            return dashboard_redirect(filter, search, page, message=f"User {telegram_id} removed from channel.")
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.exception("Could not remove telegram_id=%s from channel", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not remove user from channel: {exc}")
        except Exception as exc:
            logger.exception("Unexpected remove error for telegram_id=%s", telegram_id)
            return dashboard_redirect(filter, search, page, error=f"Could not remove user from channel: {exc}")

    return app


async def run_web_server(app: FastAPI) -> None:
    PORT = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting web dashboard on port {PORT}")
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_startup_migration(supabase: Client, settings: Settings) -> None:
    try:
        await asyncio.to_thread(run_schema_migration, supabase)
        await asyncio.to_thread(ensure_grupo_access_channel, supabase, settings)
        logger.info("Schema migration completed")
    except Exception:
        logger.warning("Schema migration skipped or failed; use /sync_schema or run README SQL", exc_info=True)


async def main() -> None:
    configure_logging()
    settings = load_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    bot = Bot(settings.bot_token)
    app = create_web_app(settings, supabase, bot)

    asyncio.create_task(run_startup_migration(supabase, settings), name="schema-migration")
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
