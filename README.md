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
  pending_payment_file_id text,
  pending_payment_file_type text,
  pending_payment_at timestamptz,
  approved_by_admin_id bigint,
  approved_at timestamptz,
  rejected_at timestamptz,
  needs_new_receipt_at timestamptz,
  last_payment_at timestamptz,
  invite_link text,
  invite_link_created_at timestamptz,
  invite_link_name text,
  invite_link_revoked boolean default false,
  invite_link_used boolean default false,
  revoked_at timestamptz,
  joined_channel_at timestamptz,
  left_channel_at timestamptz,
  last_seen_at timestamptz,
  renewal_notice_7d_sent_at timestamptz,
  renewal_notice_3d_sent_at timestamptz,
  renewal_notice_1d_sent_at timestamptz,
  removed_at timestamptz,
  removal_reason text,
  confirmed_subscription boolean default false,
  confirmed_at timestamptz,
  confirmation_campaign text,
  source text
);

create index if not exists telegram_users_registered_at_idx
  on telegram_users (registered_at desc);

create index if not exists telegram_users_expiry_date_idx
  on telegram_users (expiry_date);

create table if not exists payment_history (
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

create index if not exists payment_history_telegram_id_idx
  on payment_history (telegram_id);

create index if not exists payment_history_created_at_idx
  on payment_history (created_at desc);

create index if not exists payment_history_payment_status_idx
  on payment_history (payment_status);

create table if not exists access_channels (
  channel_key text primary key,
  label text not null,
  chat_id text not null,
  active boolean default true,
  is_active boolean default true,
  expires_membership boolean default false,
  has_expiry boolean default false,
  created_at timestamptz default now()
);

create table if not exists user_channel_access (
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
  status text default 'active',
  access_status text default 'active',
  granted_at timestamptz,
  joined_channel_at timestamptz,
  expires_at date,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (telegram_id, channel_key)
);

create index if not exists user_channel_access_telegram_id_idx
  on user_channel_access (telegram_id);

create index if not exists user_channel_access_channel_key_idx
  on user_channel_access (channel_key);

create table if not exists manual_invite_links (
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
  on manual_invite_links (invite_link);

create index if not exists manual_invite_links_channel_code_idx
  on manual_invite_links (channel_code);
```

For existing tables, `/sync_schema` and startup migration attempt to run:

```sql
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
  expires_membership boolean default false,
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
alter table public.user_channel_access add column if not exists joined_channel_at timestamptz;
alter table public.user_channel_access add column if not exists expires_at date;
alter table public.user_channel_access add column if not exists created_at timestamptz default now();
alter table public.user_channel_access add column if not exists updated_at timestamptz default now();
create index if not exists user_channel_access_telegram_id_idx
  on public.user_channel_access (telegram_id);
create index if not exists user_channel_access_channel_key_idx
  on public.user_channel_access (channel_key);
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
```

Supabase REST does not expose DDL by default. To let the bot run this automatically, create a tightly controlled `exec_sql` RPC for your server-side service role, or run the SQL manually in the Supabase SQL editor.

Use the Supabase service role key only on Railway/server-side infrastructure. Never expose it in client code.

## Telegram setup

1. Create a bot with BotFather and copy the token.
2. Add the bot to your content channel.
3. Promote the bot to admin in the channel so it can send messages.
4. Give the bot permission to invite users, ban users, and receive member updates for invite/removal and join/leave tracking.
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
AUTO_REMOVE_EXPIRED=false
RENEWAL_NOTICE_DAYS=7,3,1
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
/chat_id
/pending_payments
/user <telegram_id>
/payment_history <telegram_id>
/send_invite <telegram_id>
/manual_open_link CHANNEL_CODE
/revoke_invite <telegram_id>
/revoke_user <telegram_id>
/revoke_link <invite_link_name>
/approve <telegram_id>
/reject <telegram_id>
/ask_receipt <telegram_id>
/set_expiry <telegram_id> <YYYY-MM-DD>
/expired
/remove_expired_preview
/remove_expired_confirm
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
- `payment_status`
- `status`
- `confirmed_subscription`
- `confirmed_at`
- `source`
- Registered / Join Date
- `membership_start_date`
- `expiry_date`
- days remaining
- `joined_channel_at`
- `left_channel_at`
- `invite_link`
- `notes`
- latest 5 payment history records per user row

Dashboard filters:

- All
- Pending payments
- Paid
- Needs new receipt
- Rejected
- Active
- Confirmed
- Not confirmed
- Source: confirm_subscription_button
- Expiring in 7 days
- Expired
- No expiry date
- Has payment history
- Removed/inactive

Dashboard actions:

- Approve pending payment
- Reject payment
- Ask for another receipt
- Renew +30 days from today
- Renew +30 days from current expiry date if still active
- Set membership start date
- Mark paid
- Mark confirmed manually
- Mark not confirmed
- Mark inactive
- Generate one-use invite link using Telegram Bot API for `CONTENT_CHANNEL_ID`
- Send existing invite link
- Revoke current invite
- Remove from channel using a confirmation page, then Telegram ban/unban

The dashboard stores signed session cookies and does not expose the Supabase service role key to the browser.

## Payment approval and renewal jobs

Users send payment receipts to the bot in private chat as a photo or document. The bot marks them `pending_review` and sends admin buttons to `ADMIN_CHAT_ID`. If a user sends another receipt while still pending review, the bot replaces the stored receipt reference and does not send another admin alert or create another approval button. Invite links are generated and sent only after an admin approves the payment.

Multi-channel approval:

- Pending payment admin messages include channel selection buttons before approval.
- `Grupo` is the existing `CONTENT_CHANNEL_ID` channel and keeps membership expiration, renewal reminders, and expired-user removal.
- `Lady in Red` appears when `access_channels.channel_key='lady_in_red'` has `is_active=true`; it does not expire and does not trigger renewal reminders.
- `has_expiry` controls renewal/expiry logic only. It does not control button visibility.
- Channels without an active `access_channels` row are hidden from the pending-payment approval buttons.
- Generated links for every selected channel are stored separately in `user_channel_access`.
- Use `/chat_id` in a channel or group to send its chat ID and title to `ADMIN_CHAT_ID` before adding it to `access_channels`.
- Use `/manual_open_link CHANNEL_CODE` to create a one-hour, one-use invite link for an active channel when you do not know the user's Telegram ID yet. The link is sent only to `ADMIN_CHAT_ID`, saved in `manual_invite_links`, and does not create payment history or mark anyone paid.
- When a user joins with a manual open link, the bot records the Telegram user, marks the manual link as used, creates `user_channel_access`, and notifies `ADMIN_CHAT_ID`.
- If a joining user is blacklisted in `telegram_users` or `blacklisted_users`, the bot bans them immediately and notifies `ADMIN_CHAT_ID`.

Example `access_channels` rows:

```sql
insert into public.access_channels (channel_key, label, chat_id, is_active, has_expiry)
values
  ('grupo', 'Grupo', '-1001234567890', true, true),
  ('lady_in_red', 'Lady in Red', '-1009876543210', true, false)
on conflict (channel_key) do update
set label = excluded.label,
    chat_id = excluded.chat_id,
    is_active = excluded.is_active,
    has_expiry = excluded.has_expiry;
```

Payment history:

- Only approved payments are appended to `payment_history`.
- Pending receipts, rejected receipts, requests for another capture, and invite revocations are not stored as payment history.
- Receipt file IDs are copied into payment history only for approved payments so the dashboard can show a protected screenshot preview.
- Payment history writes are best-effort: if the history table is unavailable, the main payment flow continues and the bot logs a warning.
- Use `/payment_history <telegram_id>`, `/dashboard/users/{telegram_id}/history`, or `/dashboard/payments` to review approved payment history.

Invite security:

- Approval reuses an existing active unused invite link instead of creating duplicates.
- The dashboard refuses to generate another link while a user already has an active unused link.
- Use `Revoke current invite`, `/revoke_user <telegram_id>`, or `/revoke_link <invite_link_name>` before generating a replacement.
- Invite links use `member_limit=1` and expire after one hour.
- When Telegram reports the user joined the channel, `invite_link_used` is marked `true`.
- Recent duplicate approvals are blocked with a warning instead of generating another link.

The bot runs an in-process scheduler while long polling is active. It sends daily renewal notices to `ADMIN_CHAT_ID` at `09:00 America/Mexico_City` for the days in `RENEWAL_NOTICE_DAYS`, includes expired users, and only removes expired active users when `AUTO_REMOVE_EXPIRED=true`.

## Testing checklist

1. Run `/sync_schema` or execute the SQL migration above in Supabase.
2. Send a photo or PDF receipt to the bot in a private chat from a non-admin account.
3. Confirm `ADMIN_CHAT_ID` receives the pending payment message with approval buttons.
4. Click `Aprobar ✅` and verify the user receives a private one-use invite link.
5. Join the channel with that link and confirm `joined_channel_at` updates.
6. Test `/pending_payments`, `/user <telegram_id>`, `/remove_expired_preview`, and the dashboard filters.
7. Keep `AUTO_REMOVE_EXPIRED=false` until manual preview/removal looks correct.

## Railway deployment

1. Push this repository to GitHub.
2. Create a new Railway project from the repo.
3. Add all required environment variables.
4. Railway will use `railway.json` to run:

```bash
python main.py
```

Run this service as a web service. The FastAPI dashboard and Telegram long-polling bot run in the same process. Do not configure a webhook for the bot.
