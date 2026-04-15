import asyncio
import hashlib
import logging
import os
from urllib.parse import urlencode

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== КОНФИГ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Robokassa
ROBOKASSA_LOGIN      = os.getenv("ROBOKASSA_LOGIN")       # Логин магазина
ROBOKASSA_PASS1      = os.getenv("ROBOKASSA_PASS1")       # Пароль #1 (для формирования ссылки)
ROBOKASSA_PASS2      = os.getenv("ROBOKASSA_PASS2")       # Пароль #2 (для проверки Result URL)
ROBOKASSA_TEST_MODE  = os.getenv("ROBOKASSA_TEST_MODE", "1") == "1"  # 1 = тест, 0 = боевой

# Адрес, на котором будет слушать вебхук для Robokassa
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

# Публичный URL для Robokassa Result URL
# Настройте в ЛК Robokassa: http://qp1t-734u-r1t9.gw-1a.dockhost.net/webhook/robokassa/result
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://qp1t-734u-r1t9.gw-1a.dockhost.net/webhook")

# Товары: название -> цена
PRODUCTS = {
    "avatar":           {"name": "🖼 Аватарка",                     "price": 300},
    "video_edit":       {"name": "🎬 Монтаж видео для YouTube",      "price": 1500},
    "marketplace_card": {"name": "📦 Карточка для маркетплейса",     "price": 1200},
    "logo":             {"name": "✨ Логотип",                       "price": 800},
    "banner":           {"name": "📢 Баннер для соцсетей",           "price": 500},
    "presentation":     {"name": "📊 Презентация (5 слайдов)",       "price": 1000},
    "instagram_post":   {"name": "📸 Пост для Instagram",            "price": 400},
    "packaging":        {"name": "📦 Дизайн упаковки",               "price": 1800},
}

# ========== FSM ==========
class OrderState(StatesGroup):
    waiting_for_confirmation = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Хранилище заказов: invoice_id -> {chat_id, product_name, amount}
# В продакшене замените на БД (Redis / PostgreSQL)
pending_orders: dict[int, dict] = {}
_invoice_counter = 0

def _next_invoice_id() -> int:
    global _invoice_counter
    _invoice_counter += 1
    return _invoice_counter

# ========== ROBOKASSA ==========
def _robokassa_signature(password: str, merchant_login: str, out_sum: str, inv_id: int,
                          extra: dict | None = None) -> str:
    """
    Подпись для Robokassa.
    Формула: MD5( MerchantLogin:OutSum:InvId[:Shp_...]:Password )
    Shp-параметры добавляются в алфавитном порядке.
    """
    base = f"{merchant_login}:{out_sum}:{inv_id}"
    if extra:
        shp_parts = ":".join(f"{k}={v}" for k, v in sorted(extra.items()))
        base = f"{base}:{shp_parts}"
    base = f"{base}:{password}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def build_payment_url(invoice_id: int, amount: int, description: str, chat_id: int) -> str:
    """Формирует ссылку на оплату Robokassa."""
    out_sum = str(amount) + ".00"
    # Передаём chat_id как Shp-параметр, чтобы в Result URL знать, кому писать
    shp = {"Shp_chat_id": str(chat_id)}

    sign = _robokassa_signature(ROBOKASSA_PASS1, ROBOKASSA_LOGIN, out_sum, invoice_id, shp)

    params = {
        "MerchantLogin": ROBOKASSA_LOGIN,
        "OutSum": out_sum,
        "InvId": invoice_id,
        "Description": description,
        "SignatureValue": sign,
        "IsTest": 1 if ROBOKASSA_TEST_MODE else 0,
        **{k: v for k, v in shp.items()},
    }
    return "https://auth.robokassa.ru/Merchant/Index.aspx?" + urlencode(params)


def verify_result_signature(out_sum: str, inv_id: int, sign_from_robokassa: str,
                             shp: dict | None = None) -> bool:
    """Проверяет подпись входящего Result URL от Robokassa (используется Пароль #2)."""
    expected = _robokassa_signature(ROBOKASSA_PASS2, ROBOKASSA_LOGIN, out_sum, inv_id, shp)
    return expected.lower() == sign_from_robokassa.lower()

# ========== КЛАВИАТУРЫ ==========
def get_main_menu() -> InlineKeyboardMarkup:
    buttons = []
    for key, prod in PRODUCTS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{prod['name']} — {prod['price']}₽",
            callback_data=f"buy_{key}"
        )])
    buttons.append([InlineKeyboardButton(text="📜 Публичная оферта", callback_data="offer")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_keyboard(product_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, подтверждаю", callback_data=f"confirm_{product_key}")],
        [InlineKeyboardButton(text="❌ Отмена",          callback_data="cancel")],
    ])

# ========== ОБРАБОТЧИКИ БОТА ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🎨 *Добро пожаловать в магазин дизайна\\!*\n\n"
        "Я помогаю создавать стильные визуальные решения:\n"
        "• Аватарки\n"
        "• Монтаж видео\n"
        "• Карточки для маркетплейсов\n"
        "• Логотипы, баннеры и многое другое\n\n"
        "Выберите товар ниже:",
        reply_markup=get_main_menu(),
        parse_mode="MarkdownV2",
    )


@dp.callback_query(F.data == "offer")
async def show_offer(callback: CallbackQuery):
    offer_text = (
        "📄 *Публичная оферта*\n\n"
        "1\\. *Общие положения*\n"
        "   Индивидуальный предприниматель / самозанятый \\[Ваше Имя\\] предлагает услуги дизайна через Telegram\\-бота\\.\n\n"
        "2\\. *Предмет договора*\n"
        "   Исполнитель обязуется выполнить дизайн\\-услуги согласно выбранному тарифу, Заказчик — оплатить и принять работу\\.\n\n"
        "3\\. *Стоимость и оплата*\n"
        "   Стоимость указана в боте\\. Оплата 100% до начала работы\\.\n\n"
        "4\\. *Сроки*\n"
        "   Срок выполнения — от 1 до 5 рабочих дней в зависимости от сложности\\.\n\n"
        "5\\. *Порядок сдачи\\-приёмки*\n"
        "   Готовый макет отправляется в чат\\. Заказчик подтверждает приёмку или даёт замечания\\.\n\n"
        "6\\. *Возврат*\n"
        "   Если работа не начата — возврат 100%\\; если начата — пропорционально\\.\n\n"
        "7\\. *Реквизиты*\n"
        "   \\[Ваше Имя\\], ИНН: 123456789012, г\\. \\[Ваш город\\]\n"
        "   Email: your@email\\.com\n"
        "   Telegram: @ваш\\_username"
    )
    await callback.message.answer(offer_text, parse_mode="MarkdownV2")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data.split("_", 1)[1]
    product = PRODUCTS.get(product_key)
    if not product:
        await callback.answer("Товар не найден")
        return

    await state.update_data(
        product_key=product_key,
        product_name=product["name"],
        product_price=product["price"],
    )
    await state.set_state(OrderState.waiting_for_confirmation)

    await callback.message.answer(
        f"🛒 *Заказ:* {product['name']}\n"
        f"💰 *Цена:* {product['price']}₽\n\n"
        f"Подтверждаете заказ?",
        reply_markup=get_confirm_keyboard(product_key),
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_name: str  = data.get("product_name", "Неизвестно")
    product_price: int = data.get("product_price", 0)
    chat_id = callback.from_user.id

    # Создаём заказ
    invoice_id = _next_invoice_id()
    pending_orders[invoice_id] = {
        "chat_id": chat_id,
        "product_name": product_name,
        "amount": product_price,
    }

    # Формируем ссылку на оплату
    payment_url = build_payment_url(
        invoice_id=invoice_id,
        amount=product_price,
        description=product_name,
        chat_id=chat_id,
    )

    pay_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

    await callback.message.answer(
        f"✅ *Заказ оформлен\\!*\n\n"
        f"Товар: {product_name}\n"
        f"Сумма: {product_price}₽\n\n"
        f"Нажмите кнопку ниже, чтобы перейти к оплате через Robokassa\\.",
        reply_markup=pay_button,
        parse_mode="MarkdownV2",
    )
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "❌ Заказ отменён\\. Можете выбрать другой товар\\.",
        reply_markup=get_main_menu(),
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@dp.message()
async def fallback(message: types.Message):
    await message.answer("Используйте кнопки меню.", reply_markup=get_main_menu())


# ========== ВЕБХУК ДЛЯ ROBOKASSA ==========
# Robokassa шлёт POST/GET на Result URL после успешной оплаты.
# Мы поднимаем отдельный aiohttp-сервер ТОЛЬКО для этого.

async def robokassa_result_handler(request: web.Request) -> web.Response:
    """
    Result URL: вызывается Robokassa сразу после оплаты (серверный запрос).
    Нужно проверить подпись и ответить 'OK<InvId>'.
    """
    if request.method == "POST":
        data = await request.post()
    else:
        data = request.rel_url.query

    out_sum  = data.get("OutSum", "")
    inv_id   = int(data.get("InvId", 0))
    sign     = data.get("SignatureValue", "")
    chat_id  = data.get("Shp_chat_id", "")       # наш кастомный Shp-параметр

    shp = {"Shp_chat_id": chat_id} if chat_id else None

    logging.info(f"Robokassa Result: InvId={inv_id}, OutSum={out_sum}, chat_id={chat_id}")

    if not verify_result_signature(out_sum, inv_id, sign, shp):
        logging.warning(f"Robokassa: неверная подпись для InvId={inv_id}")
        return web.Response(text="bad sign", status=400)

    order = pending_orders.pop(inv_id, None)
    if order is None:
        # Уже обработан или не найден — всё равно отвечаем OK, чтобы Robokassa не ретраила
        logging.warning(f"Robokassa: заказ {inv_id} не найден (возможно, дубль)")
        return web.Response(text=f"OK{inv_id}")

    # Уведомляем пользователя в Telegram
    try:
        await bot.send_message(
            chat_id=order["chat_id"],
            text=(
                f"🎉 *Оплата получена\\!*\n\n"
                f"Товар: {order['product_name']}\n"
                f"Сумма: {order['amount']}₽\n\n"
                f"Мы приступаем к работе\\. Ожидайте результат в течение 1–5 рабочих дней\\."
            ),
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение пользователю {order['chat_id']}: {e}")

    # Обязательный ответ Robokassa
    return web.Response(text=f"OK{inv_id}")


def build_webhook_app() -> web.Application:
    app = web.Application()
    # Полный путь Result URL в Robokassa:
    # http://qp1t-734u-r1t9.gw-1a.dockhost.net/webhook/robokassa/result
    app.router.add_route("*", "/webhook/robokassa/result", robokassa_result_handler)
    return app


# ========== ЗАПУСК ==========
async def main():
    webhook_app = build_webhook_app()
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
    await site.start()
    result_url = f"{WEBHOOK_BASE_URL}/robokassa/result"
    logging.info(f"Robokassa webhook слушает на порту {WEBHOOK_PORT}")
    logging.info(f"Result URL для Robokassa: {result_url}")

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
