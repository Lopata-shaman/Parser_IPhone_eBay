"""
handlers.py — Логика Telegram-бота (FSM + диалог с пользователем)

Состояния диалога:
  1. Выбор модели iPhone (13 / 14 / 15 / 16 / 17)
  2. Выбор версии (обычный / Pro / Pro Max)
  3. Ввод максимальной цены
  4. Парсинг eBay + отправка результатов
"""

import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from parser import parse_ebay

logger = logging.getLogger(__name__)
router = Router()


# ──────────────────────────────────────────────
#  FSM — машина состояний диалога
# ──────────────────────────────────────────────
class SearchForm(StatesGroup):
    choosing_model = State()    # шаг 1: какой iPhone
    choosing_version = State()  # шаг 2: какая версия
    entering_price = State()    # шаг 3: максимальная цена


# ──────────────────────────────────────────────
#  Вспомогательные клавиатуры
# ──────────────────────────────────────────────
def model_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="iPhone 13"), KeyboardButton(text="iPhone 14")],
        [KeyboardButton(text="iPhone 15"), KeyboardButton(text="iPhone 16")],
        [KeyboardButton(text="iPhone 17")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


def version_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="Обычный")],
        [KeyboardButton(text="Pro")],
        [KeyboardButton(text="Pro Max")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


# ──────────────────────────────────────────────
#  Хендлеры
# ──────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Запуск бота — предлагаем выбрать модель."""
    await state.clear()
    await message.answer(
        "👋 Привет! Я помогу найти iPhone на eBay по лучшей цене.\n\n"
        "📱 Выберите модель:",
        reply_markup=model_keyboard(),
    )
    await state.set_state(SearchForm.choosing_model)


@router.message(SearchForm.choosing_model, F.text.in_({
    "iPhone 13", "iPhone 14", "iPhone 15", "iPhone 16", "iPhone 17"
}))
async def process_model(message: Message, state: FSMContext) -> None:
    """Пользователь выбрал модель → спрашиваем версию."""
    await state.update_data(model=message.text)
    await message.answer(
        f"✅ Выбрано: {message.text}\n\nТеперь выберите версию:",
        reply_markup=version_keyboard(),
    )
    await state.set_state(SearchForm.choosing_version)


@router.message(SearchForm.choosing_model)
async def process_model_invalid(message: Message) -> None:
    """Пользователь ввёл что-то не то на шаге выбора модели."""
    await message.answer("⚠️ Пожалуйста, выберите модель из списка ниже:", reply_markup=model_keyboard())


@router.message(SearchForm.choosing_version, F.text.in_({"Обычный", "Pro", "Pro Max"}))
async def process_version(message: Message, state: FSMContext) -> None:
    """Пользователь выбрал версию → спрашиваем цену."""
    await state.update_data(version=message.text)
    data = await state.get_data()
    query_preview = _build_query(data["model"], message.text)
    await message.answer(
        f"✅ Версия: {message.text}\n"
        f"🔍 Буду искать: <b>{query_preview}</b>\n\n"
        f"💶 Введите максимальную цену в евро (только число, например: <code>500</code>):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(SearchForm.entering_price)


@router.message(SearchForm.choosing_version)
async def process_version_invalid(message: Message) -> None:
    await message.answer("⚠️ Выберите версию из кнопок:", reply_markup=version_keyboard())


@router.message(SearchForm.entering_price)
async def process_price(message: Message, state: FSMContext) -> None:
    """Пользователь ввёл цену → запускаем парсер."""
    # Валидация цены
    price_text = message.text.strip().replace("€", "").replace(",", ".").strip()
    try:
        max_price = float(price_text)
        if max_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введите корректное число, например: <code>500</code>", parse_mode="HTML")
        return

    data = await state.get_data()
    search_query = _build_query(data["model"], data["version"])

    await state.clear()

    # Уведомляем пользователя о начале поиска
    status_msg = await message.answer(
        f"🔍 Ищу <b>{search_query}</b> до <b>{max_price:.0f}€</b> на eBay...\n"
        f"⏳ Это может занять 20–40 секунд, подождите.",
        parse_mode="HTML",
    )

    # Запускаем парсер
    try:
        items = await parse_ebay(search_query, max_price, pages=10, max_results=20)
    except Exception as e:
        logger.error(f"Ошибка парсера: {e}", exc_info=True)
        await status_msg.edit_text(
            "❌ Произошла ошибка при парсинге eBay. Попробуйте позже.\n"
            f"Детали: <code>{e}</code>",
            parse_mode="HTML",
        )
        return

    # Удаляем статусное сообщение
    await status_msg.delete()

    if not items:
        await message.answer(
            f"😔 По запросу <b>{search_query}</b> до <b>{max_price:.0f}€</b> ничего не найдено.\n"
            f"Попробуйте увеличить бюджет или выбрать другую модель.\n\n"
            f"Напишите /start чтобы начать заново.",
            parse_mode="HTML",
        )
        return

    # Заголовок
    await message.answer(
        f"✅ Найдено <b>{len(items)}</b> предложений для <b>{search_query}</b> до {max_price:.0f}€\n"
        f"📋 Показываю самые дешёвые:",
        parse_mode="HTML",
    )

    # Отправляем каждый товар отдельным сообщением
    for i, item in enumerate(items, start=1):
        text = _format_item(i, item)
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        # Небольшая задержка чтобы не спамить
        import asyncio
        await asyncio.sleep(0.3)

    await message.answer("🔄 Напишите /start для нового поиска.", parse_mode="HTML")


# ──────────────────────────────────────────────
#  Вспомогательные функции
# ──────────────────────────────────────────────
def _build_query(model: str, version: str) -> str:
    """Формирует поисковый запрос из модели и версии."""
    if version == "Обычный":
        return model  # например: "iPhone 14"
    return f"{model} {version}"  # например: "iPhone 14 Pro Max"


def _format_item(index: int, item: dict) -> str:
    """Форматирует один товар для отправки в Telegram."""
    condition = item.get("condition") or "—"
    price = item.get("price_display") or f"{item.get('price_eur', '?')}€"

    return (
        f"<b>#{index} {item['title']}</b>\n"
        f"💶 <b>{price}</b>\n"
        f"🔗 <a href='{item['url']}'>Открыть на eBay</a>"
    )
