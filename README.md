# Telegram Renewal Management Bot

Production-ready Telegram renewal bot built with Python 3.11, aiogram 3, Supabase, and Railway. It uses long polling, not webhooks.

## Features

- Admin-only `/send_poll` command that sends a non-anonymous poll to `CONTENT_CHANNEL_ID`.
- Captures `poll_answer` updates and stores or updates users in Supabase.
- Admin-only `/users` command with total registered users and latest 10 users.
- Admin-only `/set_expiry <telegram_id> <YYYY-MM-DD>` command.
- Admin-only `/expired` command that lists expired users without removing anyone.
- Daily scheduled notification to `ADMIN_CHAT_ID` for users expiring today.
- Structured logging and defensive error handling.

## Supabase schema

Create this table in Supabase SQL editor:

```sql
create table if not exists telegram_users (
  telegram_id bigint primary key,
  username text,
  first_name text,
  last_name text,
  last_poll_id text,
  selected_option text,
  registered_at timestamptz not null default now(),
  expiry_date date
);

create index if not exists telegram_users_registered_at_idx
  on telegram_users (registered_at desc);

create index if not exists telegram_users_expiry_date_idx
  on telegram_users (expiry_date);
```

Use the Supabase service role key only on Railway/server-side infrastructure. Never expose it in client code.

## Telegram setup

1. Create a bot with BotFather and copy the token.
2. Add the bot to your content channel.
3. Promote the bot to admin in the channel so it can send polls.
4. Disable privacy mode if you later need group command behavior. Channel poll answers are delivered to the bot when the bot created the poll.
5. Get your numeric Telegram admin user ID and add it to `ADMIN_USER_IDS`.

## Environment variables

Set these in Railway:

```bash
BOT_TOKEN=123456:telegram-token
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ADMIN_CHAT_ID=123456789
CONTENT_CHANNEL_ID=-1001234567890
ADMIN_USER_IDS=123456789,987654321
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

## Commands

```text
/send_poll
/users
/set_expiry <telegram_id> <YYYY-MM-DD>
/expired
```

Only users listed in `ADMIN_USER_IDS` can run admin commands.

## Daily expiry notification

The bot runs an in-process scheduler while long polling is active. It sends a daily message to `ADMIN_CHAT_ID` at `09:00 America/Mexico_City` listing users whose `expiry_date` equals the current date in that timezone.

## Railway deployment

1. Push this repository to GitHub.
2. Create a new Railway project from the repo.
3. Add all required environment variables.
4. Railway will use `Procfile` / `railway.json` to run:

```bash
python main.py
```

Run this service as a worker. Do not configure a webhook for the bot.
