import asyncio
import logging
import os
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from config import Client

_bot_ready: bool = False


async def _health(request):
    if _bot_ready:
        return web.Response(text="✅ Bot is running", status=200)
    return web.Response(text="⏳ Bot is starting...", status=503)

async def _start_health_server():
    port = int(os.environ.get("PORT", 10000))
    app  = web.Application()
    app.router.add_get("/", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check server on port %d", port)


async def _preload_games_data():
    """يُحمِّل بيانات الألعاب (191KB) في الخلفية عند الإقلاع"""
    try:
        import importlib
        await asyncio.get_running_loop().run_in_executor(
            None, importlib.import_module, "helpers.games_data"
        )
        logger.info("بيانات الألعاب جاهزة ✅")
    except Exception as e:
        logger.warning("تعذّر تحميل بيانات الألعاب مسبقاً: %s", e)


async def main():
    from Plugins.auto_clean import _auto_clean_loop
    import Plugins.private_sudos as _ps

    await _start_health_server()

    async with Client:
        global _bot_ready
        me = await Client.get_me()
        _bot_ready = True
        logger.info("البوت شغال: @%s", me.username)

        _running_loop = asyncio.get_running_loop()
        _running_loop.create_task(_auto_clean_loop(Client))
        logger.info("حلقة التنظيف التلقائي تعمل")

        _running_loop.create_task(_preload_games_data())

        try:
            await asyncio.sleep(float("inf"))
        finally:
            import Plugins.downloader as _dl

            # إغلاق httpx clients
            await _ps._http.aclose()
            await _dl._http.aclose()

            # ✅ إصلاح 4: إغلاق aiohttp ClientSession عند إيقاف البوت
            # كانت تبقى مفتوحة → resource leak تحذيرات عند الإيقاف
            if _dl._aio_session and not _dl._aio_session.closed:
                await _dl._aio_session.close()

            # إغلاق httpx client من get_create
            try:
                from helpers.get_create import close_client as _gc_close
                await _gc_close()
            except Exception:
                pass

            logger.info("تم إغلاق جميع HTTP clients ✅")


if __name__ == "__main__":
    loop.run_until_complete(main())
