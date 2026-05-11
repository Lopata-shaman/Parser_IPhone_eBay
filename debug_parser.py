"""
debug_parser.py — Диагностический скрипт
Запустите его ОТДЕЛЬНО чтобы понять что происходит:
    python debug_parser.py

Он сохранит скриншот и HTML страницы — посмотрим что видит браузер.
"""

import asyncio
from playwright.async_api import async_playwright


async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # ВИДИМЫЙ браузер — чтобы видеть что происходит
            args=["--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="de-DE",
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()

        url = "https://www.ebay.de/sch/i.html?_nkw=iPhone+14+Pro&LH_BIN=1&_sop=15"
        print(f"Открываю: {url}")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Сохраняем скриншот
        await page.screenshot(path="debug_screenshot.png", full_page=False)
        print("✅ Скриншот сохранён: debug_screenshot.png")

        # Сохраняем HTML
        html = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ HTML сохранён: debug_page.html")

        # Проверяем разные селекторы
        selectors_to_check = [
            ".s-item",
            ".srp-results",
            ".s-item__title",
            "li.s-item",
            "[data-testid='srp-search-results']",
            ".srp-river-results",
            "ul.srp-results",
        ]

        print("\n🔍 Проверка селекторов:")
        for sel in selectors_to_check:
            elements = await page.query_selector_all(sel)
            count = len(elements)
            status = "✅" if count > 0 else "❌"
            print(f"  {status} {sel!r}: {count} элементов")

        # Проверяем заголовок страницы
        title = await page.title()
        print(f"\n📄 Заголовок страницы: {title}")

        # Проверяем URL (возможно редирект)
        current_url = page.url
        print(f"🔗 Текущий URL: {current_url}")

        # Ищем капчу
        captcha = await page.query_selector("#captcha, .captcha, [id*='captcha']")
        if captcha:
            print("\n⚠️  ОБНАРУЖЕНА КАПЧА! eBay блокирует запрос.")
        else:
            print("\n✅ Капча не обнаружена")

        print("\nБраузер открыт 10 секунд — посмотрите что на экране...")
        await asyncio.sleep(10)
        await browser.close()


asyncio.run(debug())
