# New & Used Hard Drives — Telegram bot + Mini App + Admin panel

Guangzhou Unetik Technology uchun HDD ulgurji savdo platformasi. Hammasi Python:
**FastAPI** (API + server tomonida render qilinadigan Mini App va admin panel, Jinja2 + HTMX + CSS animatsiyalar),
**aiogram 3** (Telegram bot), **PostgreSQL** (SQLAlchemy 2 async + Alembic). Paket menejeri: **uv**, Python 3.12.

## Arxitektura

```
Telegram mijoz ──/start──▶ aiogram bot (app/bot)        ──┐
         │                                                 │  bitta FastAPI jarayoni
         └──Mini App (WebApp tugma)──▶ /app/* (app/web)    ├─ app/main.py
Admin brauzer ─────────────────────▶ /admin/* (app/admin) │
JSON / SSE ────────────────────────▶ /api/*  (app/api)   ──┘
                                            │
                                     app/services/*  (biznes mantiq: buyurtma, 30/70 to'lov, auksion, chat)
                                            │
                                       PostgreSQL (app/models)
```

- Mini App birinchi ochilganda `/app` splash sahifasi Telegram `initData` ni `/api/auth/telegram` ga yuboradi, server HMAC ni tekshiradi va imzolangan cookie sessiya ochadi. Keyingi sahifalar oddiy server render + HTMX.
- Auksion jonli yangilanishlari `/api/auctions/{id}/stream` (SSE). Pub/sub jarayon ichida, shuning uchun **1 worker** bilan ishga tushiriladi (ko'p worker kerak bo'lsa Redis pub/sub ga o'tkazish kerak).
- Bot va Mini App bir xil `users` jadvalidan foydalanadi (`tg_id` bo'yicha).

## Papkalar

```
app/
  main.py            FastAPI ilova, lifespan (auksion ticker, bot start), middleware
  config.py          .env sozlamalari (pydantic-settings)
  db.py              async engine/session
  enums.py           holatlar: Condition, OrderStatus, Role, ...
  models/            SQLAlchemy modellari
  services/          biznes mantiq (orders, auctions, support, notifications, reports, media, settings)
  api/               JSON + SSE endpointlar
  web/               Mini App sahifalari (/app)
  admin/             Admin panel (/admin)
  bot/               aiogram: runner, handlers/, keyboards, middlewares, broadcast
  templates/         Jinja2 shablonlar (miniapp/, admin/)
  static/            css, js (htmx, alpine), img, uploads/
  locales/{uz,ru,en}/*.json   tarjimalar (uz — kirill)
alembic/             migratsiyalar
scripts/             seed, create_staff, set_webhook, dev_auction, broadcast_new_arrivals
tests/               pytest (alohida nuhdbot_test bazasi)
deploy/              systemd, Caddy, nginx namunalari
```

## O'rnatish

```bash
brew install uv postgresql@16 && brew services start postgresql@16   # macOS misoli
createdb nuhdbot
uv sync
cp .env.example .env            # BOT_TOKEN, SECRET_KEY, BASE_URL, DATABASE_URL ni to'ldiring
uv run alembic upgrade head
uv run python -m scripts.seed --demo     # ma'lumotnoma + NAMUNA mahsulotlar (--demo siz faqat ma'lumotnoma)
uv run uvicorn app.main:app --reload     # http://localhost:8000
```

Makefile qisqartmalari: `make install migrate demo dev lint test webhook`.

Admin panel: `http://localhost:8000/admin` — login/parol `.env` dagi `ADMIN_LOGIN` / `ADMIN_PASSWORD` (birinchi ishga tushganda yaratiladi).
Qo'shimcha xodim: `uv run python -m scripts.create_staff --login manager1 --password 'S3cret!' --role orders --tg-id 123456789`.

Dev rejimda Telegramsiz kirish: `DEBUG=true` bo'lsa `http://localhost:8000/app/home?dev_tg=1001`.

## HTTPS va BotFather

Telegram Mini App **faqat https** manzilda ishlaydi. Devda tunnel oching:

```bash
cloudflared tunnel --url http://localhost:8000     # yoki: ngrok http 8000
```

Chiqqan `https://...` manzilni `.env` da `BASE_URL` ga yozing va serverni qayta ishga tushiring.
Ishga tushganda bot o'zi: buyruqlar ro'yxatini (`/start /catalog /orders /auction /help /language`) 3 tilda o'rnatadi va
menyu tugmasini (`Menu` → Mini App `/app`) qo'yadi. BotFather da qo'lda qilish shart emas; xohlasangiz
`/setmenubutton` orqali ham xuddi shu URL ni berish mumkin. `/setdomain` kerak emas (Login Widget ishlatilmaydi).

Bot rejimlari (`BOT_MODE`): `polling` (dev), `webhook` (prod: `{BASE_URL}/tg/webhook`, `WEBHOOK_SECRET` bilan), `off`.
Webhookni qo'lda boshqarish: `uv run python -m scripts.set_webhook set|delete|info`.
Xodimlar guruhi: `ADMIN_CHAT_ID` berilsa, yangi buyurtma/to'lov/murojaat xabarlari shu guruhga tushadi va
xodim guruhdagi `#thread_<id>` xabariga reply qilib mijozga javob yozadi (mijoz admin profilini ko'rmaydi).

## Rollar

| Rol | Vazifa |
|---|---|
| admin | hamma narsa, sozlamalar, xodim huquqlari |
| catalog | mahsulot, narx, rasm |
| warehouse | qoldiq, qadoqlash, jo'natish |
| tester | test natijalari, seriya raqamlar |
| orders | buyurtmalarni tasdiqlash va yuritish |
| finance | to'lovlarni tasdiqlash, hisobotlar |
| marketing | reklama postlari, obunalar |

Mijoz: katalog ro'yxatsiz ochiq; buyurtma va auksion uchun ro'yxat (ism, telefon — Telegram kontakt orqali, davlat, shahar, til).

## Buyurtma oqimi (30/70)

| # | Holat | Kim | Izoh |
|---|---|---|---|
| 1 | new → awaiting_admin | mijoz | savatdan buyurtma; qoldiq atomar bron qilinadi |
| 2 | awaiting_advance | admin/orders | mavjudlik, narx, shart tasdiqlanadi; mijoz taklifga rozi bo'ladi |
| 3 | advance_confirmed | finance | 30% avans **haqiqatan** tushgani tasdiqlanadi (skrinshot dalil emas) |
| 4 | testing → test_ready | tester | disklar tekshiriladi, seriya raqam va natijalar kiritiladi |
| 5 | awaiting_customer | mijoz | natijalar, manzil, kargo kodini tasdiqlaydi |
| 6 | awaiting_balance → paid | finance | 70% qoldiq tasdiqlanadi |
| 7 | packing → shipped | warehouse | qadoq, trek raqam; omborda qoldiq ayriladi |
| 8 | delivered → completed | | |
| × | cancelled / returned / disputed | | bekor qilinganda bron qaytariladi |

Hech qachon to'liq to'lovsiz jo'natilmaydi; har bir o'tish `order_status_history` va `audit_log` da saqlanadi.

## Auksion qoidalari

- Lot: model, sig'im, holat, soni, test, kafolat, boshlang'ich narx (lot bo'yicha), qadam (dona bo'yicha).
  Masalan 20 dona, $500, qadam $1/dona → lot qadami $20: 500 → 520 → 540.
- Birinchi stavka = boshlang'ich narx; keyingilari faqat qadamga karrali.
- Oxirgi 2 daqiqada stavka kelsa tugash vaqti yana 2 daqiqaga uzayadi (anti-sniping).
- Stavkalar serverda `SELECT ... FOR UPDATE` bilan ketma-ket qabul qilinadi; bir vaqtdagi ikkita stavkadan faqat bittasi o'tadi.
- Depozit: lotda `require_deposit` yoqilsa, depozit tasdiqlanmaguncha stavka qo'yib bo'lmaydi. Miqdor admin tomonidan belgilanadi.
- Yutqazgan ishtirokchiga shaxsiy xabar, yakunda hammaga natija; stavkalar guruhga yog'dirilmaydi.
- QA uchun: `uv run python -m scripts.dev_auction --minutes 10`.

## Testlar

```bash
uv run pytest -q        # nuhdbot_test bazasini o'zi yaratadi (psql orqali)
uv run ruff check app scripts tests --fix
```

Qamrov: buyurtma bron/bekor/jo'natish, holat o'tishlari, to'lov tasdig'i; auksion qadam, anti-sniping, parallel stavkalar, tick;
Telegram initData imzosi; i18n kalitlari uch tilda bir xilligi.

## Deploy (qisqa)

1. Server: `/opt/nuhdbot`, `uv sync`, `.env` (DEBUG=false, https BASE_URL, BOT_MODE=webhook).
2. `deploy/nuhdbot.service` → systemd (`alembic upgrade head` avtomatik). 1 worker.
3. `deploy/Caddyfile` (avto-HTTPS) yoki `deploy/nginx.conf` + certbot. SSE uchun buffering o'chirilgan.
4. Zaxira: `pg_dump nuhdbot` kunlik; `app/static/uploads/` ham zaxiralanadi.

## v1 da ataylab yo'q (mijoz bilan kelishilgan)

- Partiyalar (партиялар) — mahsulotning o'zi narx/qoldiq/holat/kafolatni saqlaydi; sxema keyin Batch jadvaliga kengayadi.
- Ombor kirim/chiqim harakatlari jurnali — admin qoldiqni to'g'ridan-to'g'ri tahrirlaydi, bron/jo'natish avtomatik.
- Videolar — faqat rasmlar (WebP, thumbnail, galereya).
- Onlayn to'lov integratsiyasi — to'lovlar qo'lda, moliya xodimi tasdiqlaydi.
