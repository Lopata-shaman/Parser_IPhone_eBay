"""
debug_parser2.py — Диагностика извлечения данных из карточек

Запустите: python debug_parser2.py
Скрипт покажет что именно парсится из первых 3 карточек:
  - какой селектор сработал для заголовка
  - какой текст цены извлекается
  - HTML карточки целиком
"""

import asyncio
import re
from playwright.async_api import async_playwright


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

QUERY = "iPhone 13"
URL = f"https://www.ebay.de/sch/i.html?_nkw={QUERY.replace(' ', '+')}&LH_BIN=1&_sop=15"


async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="de-DE",
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['de-DE', 'de'] });
        """)

        page = await context.new_page()

        print(f"\n🌐 Открываю: {URL}\n")
        await page.goto("https://www.ebay.de/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)

        # Ждём загрузки
        for sel in [".srp-results", ".srp-river-results", "ul.srp-results"]:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                print(f"✅ Контейнер найден: {sel}")
                break
            except Exception:
                continue

        await asyncio.sleep(2)

        # Находим карточки
        cards = []
        for sel in ["li.s-item", ".s-item", "li[id^='item']"]:
            cards = await page.query_selector_all(sel)
            if cards:
                print(f"✅ Карточки найдены: {sel!r} — {len(cards)} шт.\n")
                break

        if not cards:
            print("❌ Карточки не найдены!")
            await browser.close()
            return

        # Анализируем первые 5 карточек
        print("=" * 60)
        print("АНАЛИЗ ПЕРВЫХ 5 КАРТОЧЕК")
        print("=" * 60)

        for i, card in enumerate(cards[:5], 1):
            print(f"\n--- Карточка #{i} ---")

            # Пробуем все селекторы заголовка
            title_selectors = [
                ".s-item__title",
                "h3.s-item__title",
                "[class*='item__title']",
                "span[role='heading']",
            ]
            for sel in title_selectors:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    print(f"  📝 Заголовок ({sel}): {text[:80]!r}")
                    break
            else:
                print("  ❌ Заголовок: НЕ НАЙДЕН")

            # Пробуем все селекторы цены
            price_selectors = [
                ".s-item__price",
                "[class*='item__price']",
                ".x-price-primary span",
                "span.s-item__price",
            ]
            for sel in price_selectors:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    print(f"  💶 Цена ({sel}): {text!r}")
                    # Парсим число
                    cleaned = text.replace("EUR", "").replace("€", "").replace("\xa0", " ").strip()
                    numbers = re.findall(r"\d+(?:[.,]\d+)*", cleaned)
                    if numbers:
                        raw = numbers[0].replace(".", "").replace(",", ".")
                        try:
                            price = float(raw)
                            print(f"  ✅ Распарсено: {price} EUR")
                        except ValueError:
                            print(f"  ❌ Не удалось распарсить: {numbers[0]!r}")
                    else:
                        print(f"  ❌ Числа не найдены в: {cleaned!r}")
                    break
            else:
                print("  ❌ Цена: НЕ НАЙДЕНА")

            # Ссылка
            link_el = await card.query_selector("a.s-item__link, a[href*='ebay.de/itm'], a[href*='ebay.com/itm']")
            if link_el:
                href = await link_el.get_attribute("href")
                print(f"  🔗 Ссылка: {str(href)[:60]}...")
            else:
                print("  ❌ Ссылка: НЕ НАЙДЕНА")

            # Состояние
            for sel in [".SECONDARY_INFO", ".s-item__subtitle", "[class*='SECONDARY_INFO']"]:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    print(f"  📦 Состояние ({sel}): {text!r}")
                    break

            # Локация
            for sel in [".s-item__location", ".s-item__itemLocation"]:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    print(f"  📍 Локация ({sel}): {text!r}")
                    break

        # Сохраняем HTML первой карточки для детального анализа
        print("\n" + "=" * 60)
        print("HTML ПЕРВОЙ КАРТОЧКИ (для анализа селекторов):")
        print("=" * 60)
        if cards:
            html = await cards[1].inner_html()  # берём 2-ю (1-я часто заглушка)
            # Выводим первые 2000 символов
            print(html[:2000])
            with open("card_html.html", "w", encoding="utf-8") as f:
                f.write(f"<ul>{html}</ul>")
            print("\n✅ Полный HTML сохранён: card_html.html")

        await asyncio.sleep(5)
        await browser.close()
        print("\n✅ Готово!")


asyncio.run(debug())
