# Telegram Renewal Management Bot

Production-ready Telegram renewal bot built with Python 3.11, aiogram 3, Supabase, and Railway. It uses long polling, not webhooks.

## Features

- Admin-only `/send_poll` command that sends a CTA message with one inline button to `CONTENT_CHANNEL_ID`.
- Captures CTA button clicks and stores or updates users in Supabase.
- Admin-only `/users` command with total registered users and latest 10 users.
- Admin-only `/set_expiry <telegram_id> <YYYY-MM-DD>` command.
- Admin-only `/expired` command that lists expired users without removing anyone.
- Admin-only `/sync_schema` command that safely adds missing dashboard lifecycle columns when a Supabase `exec_sql` RPC is available.
- Daily scheduled notification to `ADMIN_CHAT_ID` for users expiring today.
- Secure FastAPI admin dashboard with password login, filters, renewal actions, one-use invite links, and channel removal.
- Structured logging and defensive error handling.

## Supabase schema

Create this table in Supabase SQL editor:

```sql
create table if not exists telegram_users (
  telegram_id bigint primary key,
  username text,
  first_name text,
  last_name text,
  status text,
  notes text,
  registered_at timestamptz not null default now(),
  joined_at timestamptz,
  membership_start_date date,
  expiry_date date,
  payment_status text default 'unpaid',
  last_payment_at timestamptz,
  invite_link text,
  invite_link_created_at timestamptz,
  removed_at timestamptz,
  confirmed_subscription boolean default false,
  confirmed_at timestamptz,
  confirmation_campaign text,
  source text
);

create index if not exists telegram_users_registered_at_idx
  on telegram_users (registered_at desc);

create index if not exists telegram_users_expiry_date_idx
  on telegram_users (expiry_date);
```

For existing tables, `/sync_schema` and startup migration attempt to run:

```sql
alter table public.telegram_users add column if not exists joined_at timestamptz;
alter table public.telegram_users add column if not exists membership_start_date date;
alter table public.telegram_users add column if not exists payment_status text default 'unpaid';
alter table public.telegram_users add column if not exists last_payment_at timestamptz;
alter table public.telegram_users add column if not exists invite_link text;
alter table public.telegram_users add column if not exists invite_link_created_at timestamptz;
alter table public.telegram_users add column if not exists removed_at timestamptz;
alter table public.telegram_users add column if not exists confirmed_subscription boolean default false;
alter table public.telegram_users add column if not exists confirmed_at timestamptz;
alter table public.telegram_users add column if not exists confirmation_campaign text;
alter table public.telegram_users add column if not exists source text;
alter table public.telegram_users add column if not exists status text;
alter table public.telegram_users add column if not exists notes text;
alter table public.telegram_users add column if not exists expiry_date date;
alter table public.telegram_users alter column payment_status set default 'unpaid';
alter table public.telegram_users alter column confirmed_subscription set default false;
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
set expiry_date = (joined_at + interval '30 days')::date
where expiry_date is null and membership_start_date is null and joined_at is not null;
update public.telegram_users
set expiry_date = membership_start_date + 30
where expiry_date is null and membership_start_date is not null;
```

Supabase REST does not expose DDL by default. To let the bot run this automatically, create a tightly controlled `exec_sql` RPC for your server-side service role, or run the SQL manually in the Supabase SQL editor.

Use the Supabase service role key only on Railway/server-side infrastructure. Never expose it in client code.

## Telegram setup

1. Create a bot with BotFather and copy the token.
2. Add the bot to your content channel.
3. Promote the bot to admin in the channel so it can send messages.
4. Give the bot permission to invite users and ban users if you want dashboard invite/removal actions.
5. Disable privacy mode if you later need group command behavior.
6. Get your numeric Telegram admin user ID and add it to `ADMIN_USER_IDS`.

## Environment variables

Set these in Railway:

```bash
BOT_TOKEN=123456:telegram-token
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ADMIN_CHAT_ID=123456789
CONTENT_CHANNEL_ID=-1001234567890
ADMIN_USER_IDS=123456789,987654321
ADMIN_PASSWORD=use-a-long-random-password
```

`CONTENT_CHANNEL_ID` can be a numeric channel ID or a public `@channelusername`.

## Local development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Optional local `.env` files are supported through `python-dotenv`.

The local web dashboard runs on `http://localhost:8080` unless `PORT` is set.

## Commands

```text
/send_poll
/send_confirm_subscription
/users
/set_expiry <telegram_id> <YYYY-MM-DD>
/expired
/unconfirmed
/sync_schema
```

Only users listed in `ADMIN_USER_IDS` can run admin commands.

## Web dashboard

Open `/login` and sign in with `ADMIN_PASSWORD`. The dashboard is available at `/dashboard`.

Dashboard columns:

- `telegram_id`
- `username`
- `first_name`
- `status`
- `confirmed_subscription`
- `confirmed_at`
- `source`
- Registered / Join Date
- `membership_start_date`
- `expiry_date`
- days remaining
- `notes`

Dashboard filters:

- All
- Active
- Confirmed
- Not confirmed
- Source: confirm_subscription_button
- Expiring in 7 days
- Expired
- No expiry date

Dashboard actions:

- Renew +30 days from today
- Renew +30 days from current expiry date if still active
- Set membership start date
- Mark paid
- Mark confirmed manually
- Mark not confirmed
- Mark inactive
- Generate one-use invite link using Telegram Bot API for `CONTENT_CHANNEL_ID`
- Remove from channel using a confirmation page, then Telegram ban/unban

The dashboard stores signed session cookies and does not expose the Supabase service role key to the browser.

## Daily expiry notification

The bot runs an in-process scheduler while long polling is active. It sends a daily message to `ADMIN_CHAT_ID` at `09:00 America/Mexico_City` listing users whose `expiry_date` equals the current date in that timezone.

## Railway deployment

1. Push this repository to GitHub.
2. Create a new Railway project from the repo.
3. Add all required environment variables.
4. Railway will use `railway.json` to run:

```bash
python main.py
```

Run this service as a web service. The FastAPI dashboard and Telegram long-polling bot run in the same process. Do not configure a webhook for the bot.
