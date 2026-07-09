# Project Context

## Deployment Boundary

This repository is the live production Telegram bot and the master production project. All future changes must be applied only to this production project unless the user explicitly directs work elsewhere.

Preserve the current production Railway deployment, Supabase project, channels, users, payment approval flow, renewals, expiration reminders, user removals, dashboard, manual invite links, and prediction system.

## Customer Deployment Boundary

Do not create client-specific customizations in this repository. If a request is for a new customer, new creator, or separate deployment, stop and recommend using the client-template repository instead.

## Environment Assumptions

- Do not hard-code secrets, bot tokens, database URLs, admin passwords, channel IDs, or hosting identifiers.
- Runtime configuration should come from the existing production environment variables or production database rows.
- Preserve current configured channels and access behavior unless the user explicitly requests a production change.
- Keep all modifications inside this repository unless the user explicitly asks otherwise.

## Application Shape

- Python application using `aiogram`, `FastAPI`, `APScheduler`, Supabase, and Jinja templates.
- `main.py` contains the bot handlers, scheduled jobs, Supabase access, schema migration SQL, and web dashboard routes.
- `templates/` contains dashboard and admin confirmation views.
- `requirements.txt`, `Procfile`, and `railway.json` describe runtime dependencies and deployment startup behavior.

## Data Model

The app manages production Telegram user records, payment history, channel access, manual invite links, renewal message recipients, and prediction votes through Supabase tables. Schema changes must preserve current production data and remain compatible with the existing migration flow in `main.py`.

## Working Rules

- Preserve existing production functionality unless the user explicitly requests removal.
- Treat payment approval, renewals, expiration reminders, user removals, dashboard operations, manual invite links, and predictions as production-critical behavior.
- Prefer additive, backward-compatible changes for production data and workflows.
- Keep README, code comments, and future documentation aligned with this production context.
