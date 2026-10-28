"""Manage the Telegram webhook.  uv run python -m scripts.set_webhook set|delete|info"""
import asyncio
import sys

from app.bot.instance import close_bot, get_bot
from app.config import settings


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    bot = get_bot()
    if bot is None:
        sys.exit("BOT_TOKEN is not set")
    try:
        if cmd == "set":
            url = settings.base_url.rstrip("/") + "/tg/webhook"
            if not url.startswith("https://"):
                sys.exit("BASE_URL must be https for webhooks")
            await bot.set_webhook(url, secret_token=settings.webhook_secret)
            print("webhook set:", url)
        elif cmd == "delete":
            await bot.delete_webhook(drop_pending_updates="--drop" in sys.argv)
            print("webhook deleted")
        info = await bot.get_webhook_info()
        print(info.model_dump_json(indent=2))
    finally:
        await close_bot()


if __name__ == "__main__":
    asyncio.run(main())
