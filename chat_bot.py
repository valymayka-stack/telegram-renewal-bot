import asyncio
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic
from dotenv import load_dotenv
from supabase import Client, create_client
from telethon import TelegramClient, events
from telethon.tl.custom import Button

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELEGRAM_PHONE = os.environ["TELEGRAM_PHONE"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

_BASE_EXCLUDED_IDS: set[int] = {
    8975085777, 1804109661, -1003519906778, -1003915464312, -1003956578337,
    -1003932586512, -1003748850332, -1003962307050, -1003688039502, -1003933266476,
    -1003985972142, -1003891489063, -1004313113427, -1004351462290, -1004349372693,
    -1004319292984, -1003948203572, -1004491989027, -1004422598831, -1003550416043,
    -1004345600368, -1003734978794, -1004478138758, -1003932473574, -1003929923166,
    -1004362002342, 6594597876,
}
EXCLUDED_CHAT_IDS: set[int] = _BASE_EXCLUDED_IDS | {
    int(x.strip())
    for x in os.getenv("EXCLUDED_CHAT_IDS", "").split(",")
    if x.strip()
}
ADMIN_NOTIFY_ID = int(os.getenv("ADMIN_NOTIFY_ID", "8975085777"))
ADMIN_CHANNEL_ID: int | None = (
    int(os.getenv("ADMIN_CHANNEL_ID")) if os.getenv("ADMIN_CHANNEL_ID") else None
)
ASISTENCIA_CHANNEL_ID = int(os.getenv("ASISTENCIA_CHANNEL_ID", "-1003630207029"))
BOT_ENABLED = os.getenv("BOT_ENABLED", "true").lower()

SCHEDULE_START = int(os.getenv("SCHEDULE_START", "9"))   # 9am CDMX
SCHEDULE_END = int(os.getenv("SCHEDULE_END", "2"))        # 2am CDMX
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Mexico_City"))

# ── static messages ──────────────────────────────────────────────────────────

FULL_GROUP_MESSAGE = (
    "💎🔥 GRUPO EXCLUSIVO CHIVIS MONTALVO 🔥💎\n"
    "✨ Topless • Nudes • Videos • Fotos diarias • Muchas dinámicas ✨\n\n"
    "💳 Cuenta CLABE (BBVA)\n"
    "Silvia Montalvo\n"
    "🔢 012700015287595938\n\n"
    "📩 Manda tu comprobante de pago a este bot:\n"
    "🤖 @renaaaa_bot\n\n"
    "✅ Después de corroborar tu captura de pago, recibirás acceso directo al grupo 🔓✨\n\n"
    "💸 COSTO: $300 MXN\n\n"
    "✨ Dinámica: a nuevos usuarios se les regala un videito 📹 y audio 🎤 personalizado ✨"
)

BANK_DATA = (
    "💳 BBVA — Silvia Montalvo\n"
    "CLABE: 012700015287595938\n\n"
    "manda tu comprobante al @renaaaa_bot bb 🔑"
)

INTERNATIONAL_DATA = (
    "Puedes usar Remitly, Xoom o Felix bb, te mando los datos: "
    "Silvia Montalvo, CLABE 012700015287595938, Estado: Guanajuato"
)

CONTENT_MENU = (
    "Esto es lo que tengo disponible bb 🔥\n\n"
    "📸 Sexting — $1,000 MXN / 10 min (incluye fotita hot)\n"
    "👙 Lencería — $1,500 MXN (foto usándola + nota de voz personalizada)\n\n"
    "🎬 Videos personalizados:\n"
    "  • Lencería — $800 MXN\n"
    "  • Topless — $1,500 MXN\n"
    "  • Full nude — $2,000 MXN\n"
    "(Puedo: bailar, canción, pose sensual, quitarme ropa. Pago adelantado, listo en un par de horas)\n\n"
    "🏠 Videos caseros — contenido íntimo grabado en casa\n"
    "📦 Sets caseros — colección de fotos/videos caseros\n"
    "🎁 Packs personalizados — dime qué buscas y lo hacemos bb\n\n"
    "📹 Videollamada — $1,000 USD\n\n"
    "Si te interesa algo me avisas bb 💕"
)

# ── AI system prompt ──────────────────────────────────────────────────────────

AI_SYSTEM_PROMPT = """Eres Chivi Montalvo (@chivi01), creadora de contenido mexicana de 24 años de Guanajuato.
Tienes un grupo exclusivo de fans en Telegram por $300 MXN/mes.

SERVICIOS Y PRECIOS:
- Grupo exclusivo: $300 MXN/mes
- Sexting: $1,000 MXN por 10 minutos (incluye fotita hot, NO explícito)
- Lencería: $1,500 MXN (foto usándola + nota de voz personalizada)
- Videos personalizados:
  • Lencería: $800 MXN | Topless: $1,500 MXN | Full nude: $2,000 MXN
  (Puedo: bailar, canción, pose sensual, quitarme ropa. NO masturbación ni explícito)
  Pago adelantado, entrego en un par de horas.
- Videos caseros: contenido íntimo grabado en casa
- Sets caseros: colección de fotos/videos caseros
- Packs personalizados: según lo que el cliente pida (siempre escalar para cerrar)
- Videollamada: $1,000 USD

DATOS DE PAGO:
- México: BBVA Silvia Montalvo, CLABE 012700015287595938 → comprobante a @renaaaa_bot
- Internacional: Remitly, Xoom o Felix → mismos datos CLABE, Estado: Guanajuato

RESPUESTAS EXACTAS que debes usar:
- Pago ya enviado: "excelente bb, en cuanto el sistema valide tu pago te enviará un link para unirte al grupo 🔓"
- ¿Cuándo me aceptan?: "en cuanto se valide tu pago bb ✨"
- Link de pago: "en estos momentos el procesador no funciona pero puedes pagar por depósito directo a través de Xoom, Felix o Remitly"
- Descuento: "los precios son establecidos bebe no hago excepciones"
- Encuentros (1ª vez): "No, solo contenido 🔥"
- Encuentros (reiteración): "lo siento no hago encuentros, solo contenido delicioso bb, si te interesa algo de mi contenido me avisas y con gusto bebe"
- Pack personalizado: "Sí hago videos y fotitas personalizadas. ¿Qué estás buscando?"
- Grupo free vs exclusivo: "Las fotitas del grupo free son con emojis, en el grupo exclusivo el contenido es sin emoji y sin censura bb"
- Descargar/compartir: "Todo el contenido se comparte en Telegram y una vez completado y validado tu pago, tienes acceso al contenido"
- Muestra antes de pagar: "Mira aquí puedes ver muchas fotitas de muestra: @chivilovers0"
- ¿Tienes novio?: "Sip tengo esposo"
- ¿Cuántos años?: "24 años"
- ¿Dónde vives?: "Guanajuato"

TONO (CRÍTICO):
- Máximo 1-2 líneas por mensaje. NUNCA más.
- "bb", "amor", "bebe", "hermosa" ocasionalmente
- Usa "sip" en lugar de "sí"
- Emojis naturales, no exagerados
- Cálida, coqueta, cercana — NUNCA suenas como robot ni asistente de IA
- Con clientes que ya compraron antes: tono más cercano, pregunta cómo están
- Bromea con "jajaja" cuando se equivocan o dicen algo gracioso
- Respuestas CORTAS siempre

CUÁNDO PARAR:
- Si el cliente dice "ok", "listo", "gracias", "ya", "👍" después de confirmar → responde MUY corto y no sigas
- No sobre-expliques, no preguntes si necesitan algo más

LO QUE NO HACES:
- Encuentros, reuniones ni nada en persona
- Contenido explícito/pornográfico ni masturbación
- Descuentos (los precios son fijos)""".strip()

# ── regex patterns ────────────────────────────────────────────────────────────

GREET_RE = re.compile(
    r"\b(hola|buenos\s*d[ií]as|buenas\s*tardes|buenas\s*noches|hey|hi|info|saludos|qué\s*tal|que\s*tal|ola|buenas)\b",
    re.IGNORECASE,
)
BANK_RE = re.compile(
    r"\b(clabe|cuenta|transferi|a\s*d[oó]nde|datos|datos\s*de\s*pago|c[oó]mo\s*pago|precio|costo|cu[aá]nto|n[uú]mero|depositar|deposito)\b",
    re.IGNORECASE,
)
PAID_RE = re.compile(
    r"\b(ya\s*pagu[eé]|ya\s*mand[eé]|ya\s*envi[eé]|ya\s*realic[eé]|comprobante|te\s*mand[eé]|acabo\s*de\s*pagar|ya\s*lo\s*mand[eé])\b",
    re.IGNORECASE,
)
PENDING_RE = re.compile(
    r"\b(cu[aá]ndo\s*(me\s*)?(aceptan|validan|llega|agregan|une|meten)|ya\s*me\s*aceptan|ya\s*valida(ron)?|cu[aá]ndo\s*me\s*dan)\b",
    re.IGNORECASE,
)
PAYMENT_LINK_RE = re.compile(
    r"\b(link\s*de\s*pago|pagar\s*con\s*link|pago\s*online|link\s*para\s*pagar|tienen?\s*link|puedo\s*pagar\s*con)\b",
    re.IGNORECASE,
)
DEFER_RE = re.compile(
    r"\b(deja\s*lo\s*pienso|lo\s*pienso|ahorita\s*(est[aá]\s*bien)?|luego\s*te\s*aviso|despu[eé]s\s*te\s*aviso|m[aá]s\s*rato\s*te\s*aviso)\b",
    re.IGNORECASE,
)
CONV_END_RE = re.compile(
    r"^(ok|okay|listo|gracias|ya|entendido|perfecto|de\s*acuerdo|sale|va|👍|✅|🙏|de\s*nada|np|no\s*hay\s*pedo)[\s!.,]*$",
    re.IGNORECASE,
)
VIDEOCALL_RE = re.compile(
    r"\b(videollamada|video\s*llamada|videocall|facetime|llamada\s*de\s*video|llamada\s*video)\b",
    re.IGNORECASE,
)
MEET_RE = re.compile(
    r"\b(nos\s*vemos|te\s*puedo\s*ver|en\s*persona|encuentro|presencial|conocernos|quedar|quedamos|salir\s*contigo|verte\s*en\s*persona|cita)\b",
    re.IGNORECASE,
)
INTL_RE = re.compile(
    r"\b(internacional|remitly|xoom|felix|extranjero|otro\s*pa[ií]s|usa|estados\s*unidos|d[oó]lares|fuera\s*de\s*m[eé]xico|canadá|canada)\b",
    re.IGNORECASE,
)
SETS_RE = re.compile(
    r"\b(sets?|cat[aá]logo|qu[eé]\s*(tienes|vendes|ofreces|m[aá]s)|contenido\s*disponible|sexting|lencer[ií]a|videos?\s*personali|fotograf[ií]as?\s*personal)\b",
    re.IGNORECASE,
)
EXPLICIT_RE = re.compile(
    r"\b(video\s*sexual|porno|xxx|contenido\s*explicit|follar|sexo\s*oral|masturbaci|coger|cogida|hardcore|sexo\s*explicito)\b",
    re.IGNORECASE,
)
SET_PRICE_RE = re.compile(
    r"\b(cu[aá]nto\s*(cuesta|vale|cobras)\s*(el\s*)?set|precio\s*(de\s*)?set|comprar\s*set|quiero\s*(el\s*)?set|cu[aá]nto\s*por\s*(el\s*)?set)\b",
    re.IGNORECASE,
)
DISCOUNT_RE = re.compile(
    r"\b(descuento|rebaja|m[aá]s\s*barato|tan\s*caro|muy\s*caro|demasiado\s*caro|por\s*qu[eé]\s*(tan|cuesta)|hacen?\s*descuento|te\s*pago\s*menos|solo\s*tengo)\b",
    re.IGNORECASE,
)
OFFER_AMOUNT_RE = re.compile(
    r"\b(te\s*pago\s*\$?\s*\d+|pago\s*\$?\s*\d+|tengo\s*\$?\s*\d+|solo\s*tengo\s*\$?\s*\d+|te\s*doy\s*\$?\s*\d+)\b",
    re.IGNORECASE,
)
EXPIRED_LINK_RE = re.compile(
    r"\b(link\s*(expir[oó]|caducó|ya\s*no|no\s*funciona|venci[oó]|no\s*sirve|caduc)|enlace\s*(no|expir|caduc)|el\s*link\s*no)\b",
    re.IGNORECASE,
)
PERSONAL_PARTNER_RE = re.compile(
    r"\b(tienes?\s*(novio|pareja|esposo|marido)|est[aá]s?\s*soltera?|est[aá]s?\s*disponible|eres?\s*soltera?)\b",
    re.IGNORECASE,
)
PERSONAL_AGE_RE = re.compile(
    r"\b(cu[aá]ntos?\s*a[ñn]os?|qu[eé]\s*edad|a[ñn]os?\s*tienes?|edad\s*tienes?)\b",
    re.IGNORECASE,
)
PERSONAL_LOCATION_RE = re.compile(
    r"\b(d[oó]nde\s*vives?|de\s*d[oó]nde\s*eres?|en\s*qu[eé]\s*(ciudad|estado|lugar)|de\s*qu[eé]\s*(ciudad|estado))\b",
    re.IGNORECASE,
)
CUSTOM_PACK_RE = re.compile(
    r"\b(pack[s]?\s*personali|haces?\s*pack[s]?|pack\s*exclusivo|tienes?\s*pack[s]?)\b",
    re.IGNORECASE,
)
FREE_GROUP_RE = re.compile(
    r"\b(grupo\s*free|fotos?\s*free|contenido\s*free|diferencia\s*entre\s*(grupos?|plan)|grupo\s*gratuito)\b",
    re.IGNORECASE,
)
DOWNLOAD_SHARE_RE = re.compile(
    r"\b(puedo\s*(descargar|compartir|guardar)|descargar\s*(los?\s*)?videos?|compartir\s*(los?\s*)?videos?|guardar\s*(el\s*)?(contenido|video))\b",
    re.IGNORECASE,
)
SAMPLE_RE = re.compile(
    r"\b(muestra|foto\s*de\s*muestra|antes\s*de\s*pagar|prueba\s*(gratis|antes|sin\s*pagar)|dame\s*una?\s*foto\s*de?\s*muestra)\b",
    re.IGNORECASE,
)
LIFETIME_RE = re.compile(
    r"\b(plan\s*(ilimitado|de\s*vida|vitalicio)|de\s*por\s*vida|pago\s*[uú]nico|acceso\s*vitalicio|ilimitado\s*de\s*por\s*vida)\b",
    re.IGNORECASE,
)
COMING_RE = re.compile(
    r"^(ya\s+voy|ahorita\s+voy|voy(\s+ahorita|\s+a\s+pagar|\s+ya)?|ah[ií]\s+voy|ya\s+voy\s+a\s+pagar)[\s!.,]*$",
    re.IGNORECASE,
)
ALT_ACCOUNT_RE = re.compile(
    r"\b(hay\s+otra\s+cuenta|otra\s+cuenta|otro\s+n[uú]mero|tienen?\s+otra|n[uú]mero\s+alternativ|otra\s+forma\s+de\s+pagar|otro\s+m[eé]todo\s+de\s+pago)\b",
    re.IGNORECASE,
)
CONCEPT_RE = re.compile(
    r"\b(qu[eé]\s+concepto|concepto\s+(pongo|escribo|uso|anoto)|qu[eé]\s+(pongo|escribo|anoto)\s+(en\s+(el\s+)?)?concepto|concepto\s+de\s+pago)\b",
    re.IGNORECASE,
)
GIFT_RE = re.compile(
    r"\bno\s*me\s*lleg[oó]\b"
    r"|\bd[oó]nde\s*(est[aá]|qued[oó]).{0,20}(regalo|nota\s*de\s*voz|video)\b"
    r"|\bno\s*(he?\s*)?(recibi[oó]?|llegado).{0,20}(regalo|nota\s*de\s*voz)\b"
    r"|\bmi\s*regalo\b",
    re.IGNORECASE,
)
NOT_JOINED_RE = re.compile(
    r"\b(a[uú]n|todav[ií]a)\s*no\s*(entr[eé]|me\s*(uni[oó]|han?\s*unido|agreg[ao]|aceptaron|metieron?|met[ií]))\b"
    r"|\bno\s*me\s*(han?\s*)?(unido|agregado|aceptado|metido)\b"
    r"|\bsigo\s*sin\s*(entrar|acceso)\b",
    re.IGNORECASE,
)

_MONTH_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# ── in-memory state ───────────────────────────────────────────────────────────

_ai_use_count: dict[int, int] = {}
_pending_admin_replies: dict[int, int] = {}
_meet_count: dict[int, int] = {}         # number of times meeting was requested
_videocall_count: dict[int, int] = {}    # number of times videocall was requested
# conversation states: "open", "awaiting_close", "closed"
_conv_state: dict[int, str] = {}
_gift_pending: dict[int, bool] = {}      # waiting for user's name after gift inquiry

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── schedule ──────────────────────────────────────────────────────────────────

def is_within_schedule() -> bool:
    hour = datetime.now(TZ).hour
    if SCHEDULE_END < SCHEDULE_START:  # crosses midnight (e.g. 9 → 2)
        return hour >= SCHEDULE_START or hour < SCHEDULE_END
    return SCHEDULE_START <= hour < SCHEDULE_END


# ── DB helpers ────────────────────────────────────────────────────────────────

CHAT_CONVERSATIONS_SQL = """
create table if not exists public.chat_conversations (
  id bigserial primary key,
  chat_id bigint not null,
  role text not null,
  content text not null,
  created_at timestamptz default now()
);
create index if not exists chat_conversations_chat_id_idx
  on public.chat_conversations (chat_id);
create index if not exists chat_conversations_created_at_idx
  on public.chat_conversations (created_at desc);
""".strip()


def ensure_table() -> None:
    try:
        supabase.rpc("exec_sql", {"sql": CHAT_CONVERSATIONS_SQL}).execute()
        logger.info("chat_conversations table ensured")
    except Exception:
        logger.warning("Could not ensure chat_conversations table", exc_info=True)


def load_history(chat_id: int, limit: int = 20) -> list[dict]:
    try:
        rows = (
            supabase.table("chat_conversations")
            .select("role, content")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception:
        logger.warning("Could not load history chat_id=%s", chat_id, exc_info=True)
        return []


def save_turn(chat_id: int, role: str, content: str) -> None:
    try:
        supabase.table("chat_conversations").insert(
            {
                "chat_id": chat_id,
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception:
        logger.warning("Could not save turn chat_id=%s role=%s", chat_id, role, exc_info=True)


def is_repeat_customer(chat_id: int) -> bool:
    """True if this user has a prior approved payment."""
    try:
        response = (
            supabase.table("payment_history")
            .select("telegram_id")
            .eq("telegram_id", chat_id)
            .eq("action", "approved")
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except Exception:
        return False


# ── intent + reply logic ──────────────────────────────────────────────────────

def is_conversation_reopener(text: str) -> bool:
    """Returns True if the message should re-open a closed conversation."""
    return bool(
        SETS_RE.search(text)
        or VIDEOCALL_RE.search(text)
        or BANK_RE.search(text)
        or PAID_RE.search(text)
        or EXPLICIT_RE.search(text)
        or SET_PRICE_RE.search(text)
        or DISCOUNT_RE.search(text)
        or OFFER_AMOUNT_RE.search(text)
        or GREET_RE.search(text)
        or MEET_RE.search(text)
        or PAYMENT_LINK_RE.search(text)
        or INTL_RE.search(text)
        or CUSTOM_PACK_RE.search(text)
        or SAMPLE_RE.search(text)
        or LIFETIME_RE.search(text)
        or FREE_GROUP_RE.search(text)
        or COMING_RE.search(text)
        or ALT_ACCOUNT_RE.search(text)
        or GIFT_RE.search(text)
        or NOT_JOINED_RE.search(text)
    )


def classify_intent(text: str) -> str | None:
    # Hard escalations first
    if EXPIRED_LINK_RE.search(text):
        return "escalate_now"
    if EXPLICIT_RE.search(text):
        return "escalate_now"
    if SET_PRICE_RE.search(text):
        return "escalate_now"
    if OFFER_AMOUNT_RE.search(text):
        return "escalate_now"

    if GIFT_RE.search(text):
        return "gift"
    if NOT_JOINED_RE.search(text):
        return "not_joined"

    # Greet before bank so "hola cuánto cuesta" goes to greet path
    if GREET_RE.search(text) and not BANK_RE.search(text) and not PAID_RE.search(text):
        return "greet"

    if PAID_RE.search(text):
        return "paid"
    if PENDING_RE.search(text):
        return "pending"
    if PAYMENT_LINK_RE.search(text):
        return "payment_link"
    if COMING_RE.search(text):
        return "coming"
    if DEFER_RE.search(text):
        return "defer"
    if ALT_ACCOUNT_RE.search(text):
        return "alt_account"
    if CONCEPT_RE.search(text):
        return "concept"
    if CONV_END_RE.search(text):
        return "conv_end"
    if VIDEOCALL_RE.search(text):
        return "videocall"
    if MEET_RE.search(text):
        return "meet"
    if DISCOUNT_RE.search(text):
        return "discount"
    if INTL_RE.search(text):
        return "international"
    if CUSTOM_PACK_RE.search(text):
        return "custom_pack"
    if FREE_GROUP_RE.search(text):
        return "free_group"
    if DOWNLOAD_SHARE_RE.search(text):
        return "download_share"
    if SAMPLE_RE.search(text):
        return "sample"
    if LIFETIME_RE.search(text):
        return "lifetime_plan"
    if SETS_RE.search(text):
        return "sets"
    if PERSONAL_PARTNER_RE.search(text):
        return "personal_partner"
    if PERSONAL_AGE_RE.search(text):
        return "personal_age"
    if PERSONAL_LOCATION_RE.search(text):
        return "personal_location"
    if BANK_RE.search(text):
        return "bank"
    return None


def build_fixed_reply(intent: str, chat_id: int) -> str | None:
    if intent == "bank":
        return BANK_DATA
    if intent == "paid":
        return "excelente bb, en cuanto el sistema valide tu pago te enviará un link para unirte al grupo 🔓"
    if intent == "pending":
        return "en cuanto se valide tu pago bb ✨"
    if intent == "payment_link":
        return "en estos momentos el procesador no funciona pero puedes pagar por depósito directo a través de Xoom, Felix o Remitly bb 💕"
    if intent == "defer":
        return "perfecto entonces en unos momentos recibirás tu link para el grupo bb 🔓"
    if intent == "conv_end":
        return "sip bb 😊"
    if intent == "videocall":
        return "Videollamada es $1,000 USD bb 💕"
    if intent == "meet":
        count = _meet_count.get(chat_id, 0)
        if count >= 1:
            return "lo siento no hago encuentros, solo contenido delicioso bb, si te interesa algo de mi contenido me avisas y con gusto bebe"
        return "No, solo contenido 🔥"
    if intent == "discount":
        return "los precios son establecidos bebe no hago excepciones 💕"
    if intent == "international":
        return INTERNATIONAL_DATA
    if intent == "sets":
        return CONTENT_MENU
    if intent == "personal_partner":
        return "Sip tengo esposo bb 😊"
    if intent == "personal_age":
        return "24 años bb 😊"
    if intent == "personal_location":
        return "Guanajuato bb ✨"
    if intent == "custom_pack":
        return "Sí hago videos y fotitas personalizadas. ¿Qué estás buscando?"
    if intent == "free_group":
        return "Las fotitas del grupo free son con emojis, en el grupo exclusivo el contenido es sin emoji y sin censura bb"
    if intent == "download_share":
        return "Todo el contenido se comparte en Telegram y una vez completado y validado tu pago, tienes acceso al contenido"
    if intent == "sample":
        return "Mira aquí puedes ver muchas fotitas de muestra: @chivilovers0"
    if intent == "lifetime_plan":
        renewal = datetime.now(TZ) + timedelta(days=30)
        renewal_str = f"{renewal.day} de {_MONTH_ES[renewal.month]} de {renewal.year}"
        return f"El pago es mensual. Si entras hoy, tu renovación sería el {renewal_str}"
    if intent == "coming":
        return "claro que sí bb, en cuanto hagas tu pago envía el comprobante al bot para su validación 🔓"
    if intent == "alt_account":
        return "Nop es la única cuenta bb 💳"
    if intent == "concept":
        return "El que tú quieras bb, no es necesario ninguno en específico 😊"
    return None


# ── AI fallback ───────────────────────────────────────────────────────────────

def ai_reply(chat_id: int, user_message: str) -> str:
    history = load_history(chat_id)
    messages = history + [{"role": "user", "content": user_message}]
    response = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        system=AI_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text.strip()


_LOW_CONFIDENCE_RE = re.compile(
    r"\b(no\s*puedo|no\s*sé|no\s*tengo\s*información|disculpa|como\s*ia|"
    r"inteligencia\s*artificial|soy\s*un\s*bot|soy\s*una?\s*ia|"
    r"no\s*estoy\s*segura?|no\s*tengo\s*acceso|no\s*tengo\s*la\s*capacidad)\b"
    r"|assistant|claude|anthropic|openai",
    re.IGNORECASE,
)


def ai_response_has_confidence(response: str) -> bool:
    if len(response) > 300:
        return False
    if _LOW_CONFIDENCE_RE.search(response):
        return False
    return True


# ── admin / channel notifications ─────────────────────────────────────────────

async def escalate_to_channel(
    client: TelegramClient,
    chat_id: int,
    sender_name: str,
    message_text: str,
    reason: str = "",
) -> None:
    target = ASISTENCIA_CHANNEL_ID
    notification = (
        f"⚠️ ESCALAR — {reason}\n\n"
        f"👤 {sender_name} (ID: `{chat_id}`)\n"
        f"💬 {message_text[:400]}"
    )
    try:
        await client.send_message(target, notification)
        logger.info("Escalated chat_id=%s reason=%s target=%s", chat_id, reason, target)
    except Exception:
        logger.error("Could not escalate chat_id=%s", chat_id, exc_info=True)


async def notify_admin(
    client: TelegramClient,
    chat_id: int,
    sender_name: str,
    message_text: str,
) -> None:
    notification = (
        f"⚠️ Mensaje sin respuesta automática\n\n"
        f"👤 {sender_name} (ID: `{chat_id}`)\n"
        f"💬 {message_text[:400]}"
    )
    try:
        sent = await client.send_message(
            ADMIN_NOTIFY_ID,
            notification,
            buttons=[
                [Button.inline("💳 Mandar datos de pago", data=f"reply_bank:{chat_id}")],
                [Button.inline("✅ Ya validado, espera link", data=f"reply_validated:{chat_id}")],
                [Button.inline("👋 Skip / ya lo atiendo yo", data=f"ack:{chat_id}")],
            ],
        )
        _pending_admin_replies[sent.id] = chat_id
        logger.info("Admin notified chat_id=%s notif_id=%s", chat_id, sent.id)
    except Exception:
        logger.warning("Could not send admin notification with buttons", exc_info=True)
        try:
            await client.send_message(
                ADMIN_NOTIFY_ID,
                notification + f"\n\n👉 Chat ID: {chat_id}",
            )
        except Exception:
            logger.error("Could not notify admin at all chat_id=%s", chat_id, exc_info=True)


# ── main message handler ──────────────────────────────────────────────────────

async def handle_private_message(event: events.NewMessage.Event, client: TelegramClient) -> None:
    sender = await event.get_sender()
    chat_id: int = event.chat_id

    if chat_id in EXCLUDED_CHAT_IDS:
        return

    if BOT_ENABLED == "false":
        return

    sender_name = getattr(sender, "first_name", None) or f"ID:{chat_id}"
    is_sticker = bool(event.sticker)
    is_photo = bool(event.photo)
    raw_text: str = (event.raw_text or "").strip()
    message_text = raw_text if raw_text else (
        "[sticker]" if is_sticker else ("[photo]" if is_photo else "")
    )

    if not message_text:
        return

    logger.info("Incoming chat_id=%s text=%r", chat_id, message_text[:80])

    # ── schedule gate ──
    if not is_within_schedule():
        await asyncio.to_thread(save_turn, chat_id, "user", message_text)
        logger.info("Outside schedule — saved but not replied chat_id=%s", chat_id)
        return

    # ── gift pending: next message from user is their name ──
    if _gift_pending.get(chat_id) and not is_sticker:
        del _gift_pending[chat_id]
        await escalate_to_channel(
            client, chat_id, sender_name,
            f"Nombre: {message_text}",
            "Regalo — identificar cliente",
        )
        await asyncio.to_thread(save_turn, chat_id, "user", message_text)
        logger.info("Gift name captured chat_id=%s name=%r", chat_id, message_text)
        return

    intent = None if is_sticker else classify_intent(message_text)
    conv_state = _conv_state.get(chat_id, "open")

    # ── conversation closed guard ──
    if conv_state == "closed":
        if not (is_sticker or is_conversation_reopener(message_text)):
            logger.info("Conversation closed, ignoring chat_id=%s", chat_id)
            return
        _conv_state[chat_id] = "open"

    # ── awaiting_close guard: only allow closers and reopeners ──
    if conv_state == "awaiting_close":
        if intent == "conv_end":
            pass  # allow → will respond + close
        elif is_sticker or is_conversation_reopener(message_text):
            _conv_state[chat_id] = "open"
        else:
            logger.info("Awaiting close, ignoring non-closer chat_id=%s", chat_id)
            return

    # ── hard escalations ──
    if not is_sticker and intent == "escalate_now":
        if EXPIRED_LINK_RE.search(message_text):
            reason = "Link expirado"
        elif OFFER_AMOUNT_RE.search(message_text):
            reason = "Ofrece cantidad diferente (negocia precio)"
        elif EXPLICIT_RE.search(message_text):
            reason = "Solicita contenido explícito"
        else:
            reason = "Pide set específico / precio de set"
        await escalate_to_channel(client, chat_id, sender_name, message_text, reason)
        return

    # ── videocall: give price once, escalate on insistence ──
    if not is_sticker and intent == "videocall":
        vc_count = _videocall_count.get(chat_id, 0) + 1
        _videocall_count[chat_id] = vc_count
        if vc_count >= 2:
            await escalate_to_channel(client, chat_id, sender_name, message_text, "Insiste en videollamada")
            return

    # ── meet: reject twice, then escalate ──
    if not is_sticker and intent == "meet":
        mt_count = _meet_count.get(chat_id, 0) + 1
        _meet_count[chat_id] = mt_count
        if mt_count >= 3:
            await escalate_to_channel(client, chat_id, sender_name, message_text, "Insiste en encuentro")
            return

    # ── discount escalation if offering specific amount ──
    if not is_sticker and intent == "discount" and OFFER_AMOUNT_RE.search(message_text):
        await escalate_to_channel(client, chat_id, sender_name, message_text, "Ofrece cantidad diferente (negocia precio)")
        return

    # ── gift / nota de voz: ask for name then escalate ──
    if not is_sticker and intent == "gift":
        _gift_pending[chat_id] = True
        ask = "¿Cuál es tu nombre para poder identificarte? 😊"
        await asyncio.sleep(random.uniform(60, 120))
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(random.uniform(2, 5))
            await client.send_message(chat_id, ask)
        await asyncio.to_thread(save_turn, chat_id, "user", message_text)
        await asyncio.to_thread(save_turn, chat_id, "assistant", ask)
        logger.info("Gift inquiry — asked for name chat_id=%s", chat_id)
        return

    # ── not joined: short reply for repeat customers, full info for new ones ──
    if not is_sticker and intent == "not_joined":
        if is_repeat_customer(chat_id):
            reply_msg = "Porque necesitas pagar amor 💳"
            await asyncio.sleep(random.uniform(60, 120))
            async with client.action(chat_id, "typing"):
                await asyncio.sleep(random.uniform(2, 5))
                await client.send_message(chat_id, reply_msg)
            await asyncio.to_thread(save_turn, chat_id, "user", message_text)
            await asyncio.to_thread(save_turn, chat_id, "assistant", reply_msg)
            logger.info("Not-joined repeat customer chat_id=%s", chat_id)
        else:
            first_msg = "Buenos días bebe, te comparto info de mi grupo 💎"
            await asyncio.sleep(random.uniform(60, 120))
            async with client.action(chat_id, "typing"):
                await asyncio.sleep(random.uniform(2, 5))
                await client.send_message(chat_id, first_msg)
            await asyncio.to_thread(save_turn, chat_id, "user", message_text)
            await asyncio.to_thread(save_turn, chat_id, "assistant", first_msg)
            await asyncio.sleep(60)
            async with client.action(chat_id, "typing"):
                await asyncio.sleep(random.uniform(2, 5))
                await client.send_message(chat_id, FULL_GROUP_MESSAGE)
            await asyncio.to_thread(save_turn, chat_id, "assistant", FULL_GROUP_MESSAGE)
            logger.info("Not-joined new customer — sent full info chat_id=%s", chat_id)
        return

    # ── greet / sticker: two-message flow ──
    if is_sticker or intent == "greet":
        first_msg = (
            "Hola bb, qué bueno verte de nuevo 💕"
            if is_repeat_customer(chat_id)
            else "Buenos días bebe, te comparto info de mi grupo 💎"
        )
        await asyncio.sleep(random.uniform(60, 120))
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(random.uniform(2, 5))
            await client.send_message(chat_id, first_msg)
        await asyncio.to_thread(save_turn, chat_id, "user", message_text)
        await asyncio.to_thread(save_turn, chat_id, "assistant", first_msg)
        await asyncio.sleep(60)
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(random.uniform(2, 5))
            await client.send_message(chat_id, FULL_GROUP_MESSAGE)
        await asyncio.to_thread(save_turn, chat_id, "assistant", FULL_GROUP_MESSAGE)
        logger.info("Replied greet chat_id=%s (two-message flow)", chat_id)
        return

    # ── build reply ──
    reply: str | None = None

    # Photo sent here instead of @renaaaa_bot (comprobante in wrong place)
    if is_photo and intent not in ("paid", "pending"):
        reply = "¿Ya lo enviaste al bot? Está en validación bebe, si aún no lo envías por fa envíalo a @renaaaa_bot para su validación 🔓"
    elif intent and intent != "escalate_now":
        reply = build_fixed_reply(intent, chat_id)
    else:
        # AI fallback for unrecognized messages
        ai_count = _ai_use_count.get(chat_id, 0)
        if ai_count >= 2:
            await escalate_to_channel(client, chat_id, sender_name, message_text, "Sin respuesta automática (límite IA alcanzado)")
            _ai_use_count[chat_id] = 0
            return
        try:
            ai_text = await asyncio.to_thread(ai_reply, chat_id, message_text)
            if not ai_response_has_confidence(ai_text):
                logger.info("AI low-confidence response chat_id=%s — escalating to #asistencia", chat_id)
                await escalate_to_channel(client, chat_id, sender_name, message_text, "Respuesta IA de baja confianza")
                _ai_use_count[chat_id] = 0
                return
            reply = ai_text
            _ai_use_count[chat_id] = ai_count + 1
        except Exception:
            logger.warning("AI reply failed chat_id=%s", chat_id, exc_info=True)
            await escalate_to_channel(client, chat_id, sender_name, message_text, "Error en IA — escalado automático")
            return

    if not reply:
        return

    # ── update conversation state ──
    if intent == "paid" or intent == "pending":
        _conv_state[chat_id] = "awaiting_close"
    elif intent == "conv_end" or intent == "defer":
        _conv_state[chat_id] = "closed"

    # ── typing delay (realistic) ──
    delay = random.uniform(60, 120)
    await asyncio.sleep(delay)

    async with client.action(chat_id, "typing"):
        await asyncio.sleep(random.uniform(2, 5))
        await client.send_message(chat_id, reply)

    await asyncio.to_thread(save_turn, chat_id, "user", message_text)
    await asyncio.to_thread(save_turn, chat_id, "assistant", reply)

    if intent == "custom_pack":
        await escalate_to_channel(client, chat_id, sender_name, message_text, "Pack personalizado solicitado")

    logger.info("Replied chat_id=%s intent=%s conv_state=%s", chat_id, intent or "ai", _conv_state.get(chat_id, "open"))


async def handle_admin_callback(event: events.CallbackQuery.Event, client: TelegramClient) -> None:
    data = event.data.decode()
    await event.answer()

    if data.startswith("ack:"):
        await event.edit("👋 Marcado — tú lo atiendes")
        return

    if data.startswith("reply_bank:"):
        chat_id = int(data.split(":", 1)[1])
        reply = BANK_DATA
    elif data.startswith("reply_validated:"):
        chat_id = int(data.split(":", 1)[1])
        reply = "excelente bb, en cuanto el sistema valide tu pago te enviará un link para unirte al grupo 🔓"
    else:
        return

    try:
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(random.uniform(1, 3))
            await client.send_message(chat_id, reply)
        await event.edit(f"✅ Enviado al usuario {chat_id}")
        await asyncio.to_thread(save_turn, chat_id, "assistant", reply)
    except Exception:
        logger.warning("Could not send admin reply to chat_id=%s", chat_id, exc_info=True)
        await event.edit(f"❌ No se pudo enviar al usuario {chat_id}")


async def main() -> None:
    await asyncio.to_thread(ensure_table)

    client = TelegramClient("chivi01", TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start(phone=TELEGRAM_PHONE)

    me = await client.get_me()
    logger.info("Userbot started as @%s (ID: %s)", me.username, me.id)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_message(event: events.NewMessage.Event) -> None:
        await handle_private_message(event, client)

    @client.on(events.CallbackQuery(func=lambda e: e.sender_id == ADMIN_NOTIFY_ID))
    async def on_callback(event: events.CallbackQuery.Event) -> None:
        await handle_admin_callback(event, client)

    logger.info("Listening for private messages... schedule %02d:00–%02d:00 CDMX", SCHEDULE_START, SCHEDULE_END)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
