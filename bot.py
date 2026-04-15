import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== КОНФИГ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Товары: название -> цена
PRODUCTS = {
    "avatar": {"name": "🖼 Аватарка", "price": 300},
    "video_edit": {"name": "🎬 Монтаж видео для YouTube", "price": 1500},
    "marketplace_card": {"name": "📦 Карточка для маркетплейса", "price": 1200},
    "logo": {"name": "✨ Логотип", "price": 800},
    "banner": {"name": "📢 Баннер для соцсетей", "price": 500},
    "presentation": {"name": "📊 Презентация (5 слайдов)", "price": 1000},
    "instagram_post": {"name": "📸 Пост для Instagram", "price": 400},
    "packaging": {"name": "📦 Дизайн упаковки", "price": 1800},
}

# ========== FSM ==========
class OrderState(StatesGroup):
    waiting_for_product = State()
    waiting_for_confirmation = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# ========== КЛАВИАТУРЫ ==========
def get_main_menu():
    """Главное меню с товарами"""
    buttons = []
    for key, prod in PRODUCTS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{prod['name']} — {prod['price']}₽",
            callback_data=f"buy_{key}"
        )])
    buttons.append([InlineKeyboardButton(text="📜 Публичная оферта", callback_data="offer")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_confirm_keyboard(product_key):
    """Кнопки подтверждения заказа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, подтверждаю", callback_data=f"confirm_{product_key}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

# ========== ОБРАБОТЧИКИ ==========
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
        parse_mode="MarkdownV2"
    )

@dp.callback_query(F.data == "offer")
async def show_offer(callback: CallbackQuery):
    offer_text = (
        "📄 *Публичная оферта*\n\n"
        "1\\. *Общие положения*\n"
        "   Индивидуальный предприниматель / самозанятый [Ваше Имя] предлагает услуги дизайна через Telegram\\-бота\\.\n\n"
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
        "   [Ваше Имя], ИНН: 123456789012, г\\. [Ваш город]\n"
        "   Email: your@email\\.com\n"
        "   Telegram: @ваш_username"
    )
    await callback.message.answer(offer_text, parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    if not product:
        await callback.answer("Товар не найден")
        return

    await state.update_data(product_key=product_key, product_name=product["name"], product_price=product["price"])
    await state.set_state(OrderState.waiting_for_confirmation)

    await callback.message.answer(
        f"🛒 *Заказ:* {product['name']}\n"
        f"💰 *Цена:* {product['price']}₽\n\n"
        f"Подтверждаете заказ?",
        reply_markup=get_confirm_keyboard(product_key),
        parse_mode="MarkdownV2"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data.split("_")[1]
    data = await state.get_data()
    product_name = data.get("product_name")
    product_price = data.get("product_price")

    # Здесь можно вставить реальную оплату через YooKassa / Stripe / Telegram Stars
    await callback.message.answer(
        f"✅ *Заказ оформлен\\!*\n\n"
        f"Товар: {product_name}\n"
        f"Сумма: {product_price}₽\n\n"
        f"💳 *Способ оплаты:*\n"
        f"Переведите сумму на карту \\*\\*\\*\\* \\*\\*\\*\\* \\*\\*\\*\\* 1234\n"
        f"После оплаты пришлите чек сюда\\.\n\n"
        f"📌 *Важно:* работа начнётся после подтверждения оплаты\\.",
        parse_mode="MarkdownV2"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Заказ отменён. Можете выбрать другой товар.", reply_markup=get_main_menu())
    await callback.answer()

@dp.message()
async def fallback(message: types.Message):
    await message.answer("Используйте кнопки меню.", reply_markup=get_main_menu())

# ========== ЗАПУСК ==========
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())