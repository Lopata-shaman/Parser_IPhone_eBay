"""
parser.py v3 — Парсер eBay через Playwright
"""

import asyncio
import logging
import random
import re
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

DELAY_BETWEEN_PAGES = (4.0, 8.0)
DELAY_AFTER_LOAD    = (2.0, 4.0)

ITEM_SELECTORS = ["li.s-item", ".s-item", "li[id^='item']", ".srp-river-results li"]


# ──────────────────────────────────────────────────────────────
async def parse_ebay(query: str, max_price: float, pages: int = 3, max_results: int = 10) -> list[dict]:
    all_items: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "DNT": "1",
            }
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
            Object.defineProperty(navigator, 'languages', { get: () => ['de-DE', 'de', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        page = await context.new_page()

        # Создаём сессию через главную страницу
        try:
            logger.info("Открываю главную eBay.de для создания сессии...")
            await page.goto("https://www.ebay.de/", wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(random.uniform(2.0, 3.5))
        except Exception as e:
            logger.warning(f"Не удалось открыть главную: {e}")

        try:
            for page_num in range(1, pages + 1):
                logger.info(f"Парсинг страницы {page_num} для: '{query}'")
                url = _build_url(query, page_num)
                items_on_page = await _parse_page(page, url)

                if not items_on_page:
                    logger.info(f"Страница {page_num}: пусто, останавливаемся.")
                    break

                all_items.extend(items_on_page)
                logger.info(f"Страница {page_num}: найдено {len(items_on_page)} товаров.")

                if page_num < pages:
                    delay = random.uniform(*DELAY_BETWEEN_PAGES)
                    await asyncio.sleep(delay)

        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            raise
        finally:
            await browser.close()

    filtered = [i for i in all_items if i["price_eur"] is not None and i["price_eur"] <= max_price]
    filtered.sort(key=lambda x: x["price_eur"])

    seen, unique = set(), []
    for item in filtered:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"Итого после фильтрации: {len(unique)} до {max_price}€")
    return unique[:max_results]


def _build_url(query: str, page: int = 1) -> str:
    encoded = quote_plus(query)
    return f"https://www.ebay.de/sch/i.html?_nkw={encoded}&_pgn={page}&LH_BIN=1&_sop=15"


# ──────────────────────────────────────────────────────────────
async def _parse_page(page: Page, url: str) -> list[dict]:
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if resp and resp.status == 429:
            logger.warning("HTTP 429 — rate limit. Ждём 15 сек...")
            await asyncio.sleep(15)
            return []
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout: {url}")
        return []
    except Exception as e:
        logger.warning(f"Ошибка загрузки: {e}")
        return []

    # Ждём контент
    content_loaded = False
    for sel in [".srp-results", ".srp-river-results", "ul.srp-results", "#srp-river-results"]:
        try:
            await page.wait_for_selector(sel, timeout=10_000)
            content_loaded = True
            logger.info(f"Контент найден: {sel}")
            break
        except PlaywrightTimeoutError:
            continue

    if not content_loaded:
        logger.warning(f"Контент не найден. Заголовок: {await page.title()!r}")
        try:
            await page.screenshot(path="blocked_screenshot.png")
        except Exception:
            pass
        return []

    await _human_scroll(page)
    await asyncio.sleep(random.uniform(*DELAY_AFTER_LOAD))

    # Ищем карточки
    item_cards = []
    used_sel = None
    for sel in ITEM_SELECTORS:
        cards = await page.query_selector_all(sel)
        if cards:
            item_cards = cards
            used_sel = sel
            logger.info(f"Карточки: {sel!r} — {len(cards)} шт.")
            break

    if not item_cards:
        logger.warning("Карточки не найдены.")
        return []

    # Диагностика: смотрим HTML первой карточки
    if item_cards:
        first_html = await item_cards[0].inner_html()
        logger.info(f"HTML первой карточки (первые 400 символов):\n{first_html[:400]}")

    items = []
    skipped = 0
    for card in item_cards:
        item = await _extract_item_data(card)
        if item:
            items.append(item)
        else:
            skipped += 1

    logger.info(f"Извлечено: {len(items)}, пропущено: {skipped}")
    return items


async def _human_scroll(page: Page) -> None:
    try:
        await page.evaluate("""
            () => new Promise((resolve) => {
                let n = 0;
                const step = () => {
                    window.scrollBy(0, Math.floor(Math.random() * 150 + 80));
                    if (++n < 5) setTimeout(step, Math.floor(Math.random() * 300 + 200));
                    else resolve();
                };
                step();
            })
        """)
        await asyncio.sleep(random.uniform(0.5, 1.0))
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
async def _extract_item_data(card) -> Optional[dict]:
    try:
        # ── ЗАГОЛОВОК: пробуем все варианты ───────────────────
        title = None
        for sel in [
            ".s-item__title",
            "h3.s-item__title",
            "[class*='item__title']",
            "span[role='heading']",
            "h3", "h2",
        ]:
            el = await card.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                t = re.sub(r"^New listing\s*", "", t, flags=re.IGNORECASE).strip()
                if t and t.lower() not in ("shop on ebay", ""):
                    title = t
                    break

        # Последний шанс — первая строка текста карточки
        if not title:
            all_text = (await card.inner_text()).strip()
            lines = [l.strip() for l in all_text.split("\n") if l.strip()]
            for line in lines[:3]:
                if len(line) > 8 and line.lower() not in ("shop on ebay", "new listing"):
                    title = line
                    break

        if not title:
            logger.info("  ПРОПУСК: заголовок не найден совсем")
            return None

        # ── ССЫЛКА ────────────────────────────────────────────
        url = None
        for sel in ["a.s-item__link", "a[href*='/itm/']", "a[href*='ebay']", "a[href]"]:
            el = await card.query_selector(sel)
            if el:
                href = await el.get_attribute("href")
                if href and "ebay" in href:
                    url = href.split("?")[0]
                    break

        if not url:
            logger.info(f"  ПРОПУСК (нет url): {title[:50]!r}")
            return None

        # ── ЦЕНА ──────────────────────────────────────────────
        price_text = ""
        for sel in [
            ".s-item__price",
            "[class*='item__price']",
            ".x-price-primary span",
            "span.s-item__price",
            "[class*='price']",
        ]:
            el = await card.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if t:
                    price_text = t
                    break

        price_eur, price_display = _parse_price(price_text)
        logger.info(f"  ✅ {title[:40]!r} | цена: {price_text!r} → {price_eur}€")

        return {
            "title": title,
            "price_eur": price_eur,
            "price_display": price_display,
            "url": url,
        }

    except Exception as e:
        logger.warning(f"  Ошибка карточки: {e}")
        return None


# ──────────────────────────────────────────────────────────────
def _parse_price(price_text: str) -> tuple[Optional[float], str]:
    """
    Парсит немецкий формат цены.
    1.299,00 EUR  →  1299.0
    EUR 399,00    →  399.0
    399,00        →  399.0
    """
    if not price_text:
        return None, "цена не указана"

    cleaned = (
        price_text
        .replace("EUR", "").replace("€", "")
        .replace("\xa0", " ").replace("\u202f", " ")
        .strip()
    )

    # Немецкий формат: 1.299,00 (точка=тысячи, запятая=дробь)
    m = re.search(r"(\d{1,3}(?:\.\d{3})*),(\d{2})", cleaned)
    if m:
        integer_part = m.group(1).replace(".", "")
        decimal_part = m.group(2)
        try:
            price = float(f"{integer_part}.{decimal_part}")
            return price, f"{price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        except ValueError:
            pass

    # Просто целое число: 399
    m = re.search(r"(\d+)", cleaned)
    if m:
        try:
            price = float(m.group(1))
            return price, f"{price:.0f} €"
        except ValueError:
            pass

    return None, price_text
