import asyncio
import os
import random
from datetime import date, datetime, timedelta

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------- НАСТРОЙКИ ----------
TOKEN = "8729169250:AAFlprl9SEzhNRXSlF8oPMl9QgF98z1ejmM"
DB_NAME = "cards.db"
IMAGES_DIR = "images"

# Список всех карт
CARDS = [
    {"id": 1, "name": "Заражённая Узи", "rarity": "legendary", "image": "Заражённая_Узи.png"},
    {"id": 2, "name": "Узи Дверченко", "rarity": "common", "image": "Узи.png"},
    {"id": 3, "name": "Эн", "rarity": "common", "image": "N.png"},
    {"id": 4, "name": "Ворона Узи", "rarity": "epic", "image": "Узи_Ворона.png"},
    {"id": 5, "name": "Дворецкий Эн", "rarity": "rare", "image": "Дворецкий_Эн.png"},
    {"id": 6, "name": "Дрон Демонтажник Эн", "rarity": "legendary", "image": "Дрон_Демонтажник_Эн.png"},
    {"id": 7, "name": "Ви", "rarity": "common", "image": "Ви.png"},
    {"id": 8, "name": "Ви Вожатая", "rarity": "rare", "image": "Ви_Вожатая.png"},
    {"id": 9, "name": "Джей", "rarity": "common", "image": "Джей.png"},
    {"id": 10, "name": "Эн Вожатый", "rarity": "rare", "image": "Эн_Вожатый.png"},
]

RARITY_WEIGHTS = {
    "common": 60,
    "rare": 25,
    "epic": 12,
    "legendary": 3,
}

# ---------- БАЗА ДАННЫХ ----------
async def get_db():
    db = await aiosqlite.connect(DB_NAME)
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_daily TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id INTEGER,
            card_id INTEGER,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id)
        )
    """)
    await db.commit()
    await db.close()

async def add_card_to_user(user_id: int, card_id: int):
    db = await get_db()
    await db.execute("""
        INSERT INTO user_cards (user_id, card_id, quantity)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, card_id) DO UPDATE SET quantity = quantity + 1
    """, (user_id, card_id))
    await db.commit()
    await db.close()

async def get_user_collection(user_id: int):
    db = await get_db()
    cursor = await db.execute("""
        SELECT uc.card_id, uc.quantity
        FROM user_cards uc
        WHERE uc.user_id = ?
        ORDER BY uc.card_id
    """, (user_id,))
    rows = await cursor.fetchall()
    await db.close()
    collection = []
    for row in rows:
        card_info = next((c for c in CARDS if c["id"] == row[0]), None)
        if card_info:
            collection.append({
                "card_id": row[0],
                "quantity": row[1],
                "name": card_info["name"],
                "rarity": card_info["rarity"],
                "image": card_info["image"],
            })
    return collection

async def can_get_daily(user_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    await db.close()
    if row is None:
        return True
    last = row[0]
    if last is None:
        return True
    last_time = datetime.fromisoformat(last)
    if datetime.now() - last_time > timedelta(hours=5):
        return True
    return False

async def set_daily_claimed(user_id: int, username: str = ""):
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute("""
        INSERT INTO users (user_id, username, last_daily) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_daily = ?, username = ?
    """, (user_id, username, now, now, username))
    await db.commit()
    await db.close()

async def get_last_daily(user_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    await db.close()
    if row and row[0]:
        return datetime.fromisoformat(row[0])
    return None

async def user_has_card(user_id: int, card_id: int) -> int:
    db = await get_db()
    cursor = await db.execute(
        "SELECT quantity FROM user_cards WHERE user_id = ? AND card_id = ?",
        (user_id, card_id),
    )
    row = await cursor.fetchone()
    await db.close()
    return row[0] if row else 0

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_random_card():
    rarities = [card["rarity"] for card in CARDS]
    weights = [RARITY_WEIGHTS[r] for r in rarities]
    return random.choices(CARDS, weights=weights, k=1)[0]

def rarity_to_emoji(rarity: str) -> str:
    mapping = {
        "common": "⚪ Обычная",
        "rare": "🔵 Редкая",
        "epic": "🟣 Эпическая",
        "legendary": "🟡 Легендарная",
    }
    return mapping.get(rarity, "⚪ Обычная")

def get_image_path(card: dict) -> str:
    return os.path.join(IMAGES_DIR, card["image"])

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎴 Привет! Я бот-коллекционер карточек.\n\n"
        "Команды:\n"
        "/card — получить одну случайную карту (раз в 5 часов)\n"
        "/collection — посмотреть свою коллекцию\n"
        "/album — альбом твоих карт с перелистыванием\n"
        "/cardinfo ID — информация о карте\n"
        "Удачи в собирательстве!"
    )

async def card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await can_get_daily(user.id):
        last_time = await get_last_daily(user.id)
        if last_time:
            next_time = last_time + timedelta(hours=5)
            remaining = next_time - datetime.now()
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await update.message.reply_text(
                f"⏳ Ты уже получал карту.\n"
                f"Следующая будет доступна через {hours} ч. {minutes} мин."
            )
        return

    new_card = get_random_card()
    await add_card_to_user(user.id, new_card["id"])
    await set_daily_claimed(user.id, user.username or "")

    caption = (
        f"🎉 {user.first_name}, ты получил новую карту!\n\n"
        f"▸ {new_card['name']}\n"
        f"Редкость: {rarity_to_emoji(new_card['rarity'])}\n"
        f"ID карты: {new_card['id']}"
    )

    image_path = get_image_path(new_card)

    if os.path.exists(image_path):
        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(caption + "\n\n⚠️ (изображение не найдено)")

async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cards = await get_user_collection(user.id)

    if not cards:
        await update.message.reply_text("😕 Твоя коллекция пуста. Напиши /card, чтобы получить первую карту!")
        return

    rarity_order = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}
    cards.sort(key=lambda x: rarity_order.get(x["rarity"], 99))

    msg = f"📚 Коллекция {user.first_name}:\n\n"
    for i, c in enumerate(cards, 1):
        msg += f"{i}. {c['name']} {rarity_to_emoji(c['rarity'])} ×{c['quantity']}\n"
        if i % 10 == 0:
            await update.message.reply_text(msg)
            msg = ""
    if msg:
        await update.message.reply_text(msg)

async def album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Альбом с перелистыванием карт пользователя"""
    user = update.effective_user
    user_cards = await get_user_collection(user.id)

    if not user_cards:
        await update.message.reply_text("😕 У тебя нет карт! Напиши /card, чтобы получить первую.")
        return

    context.user_data["album_cards"] = user_cards
    await show_album_card(update, context, 0, new_message=True)

async def album_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки альбома"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "album_none":
        return

    parts = data.split("_")
    direction = parts[1]
    old_index = int(parts[2])

    user_cards = context.user_data.get("album_cards", [])
    if not user_cards:
        user_cards = await get_user_collection(query.from_user.id)
        context.user_data["album_cards"] = user_cards

    if not user_cards:
        try:
            await query.message.edit_caption(caption="😕 У тебя больше нет карт.")
        except:
            pass
        return

    total = len(user_cards)

    if direction == "next":
        new_index = old_index + 1
        if new_index >= total:
            new_index = 0
    else:
        new_index = old_index - 1
        if new_index < 0:
            new_index = total - 1

    await show_album_card(update, context, new_index, new_message=False)

async def show_album_card(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int, new_message: bool):
    """Показывает карту в альбоме"""
    from telegram import InputMediaPhoto

    user = update.effective_user if new_message else update.callback_query.from_user
    user_cards = context.user_data.get("album_cards", [])
    total = len(user_cards)
    card = user_cards[index]
    qty = card["quantity"]

    caption = (
        f"🃏 {card['name']}\n"
        f"Редкость: {rarity_to_emoji(card['rarity'])}\n"
        f"ID: {card['card_id']}\n"
        f"У тебя: {qty} шт."
    )

    keyboard = [
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"album_prev_{index}"),
            InlineKeyboardButton(f"📇 {index + 1}/{total}", callback_data="album_none"),
            InlineKeyboardButton("Вперёд ➡️", callback_data=f"album_next_{index}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    image_path = get_image_path(card)

    if new_message:
        if os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        else:
            await update.message.reply_text(caption + "\n\n⚠️ (изображение не найдено)", reply_markup=reply_markup)
    else:
        query = update.callback_query
        if os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                await query.message.edit_media(
                    media=InputMediaPhoto(media=photo, caption=caption),
                    reply_markup=reply_markup
                )
        else:
            await query.message.edit_text(caption + "\n\n⚠️ (изображение не найдено)", reply_markup=reply_markup)

async def cardinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /cardinfo ID\nПример: /cardinfo 3")
        return

    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    card = next((c for c in CARDS if c["id"] == card_id), None)
    if card is None:
        await update.message.reply_text("❌ Карта с таким ID не найдена.")
        return

    user = update.effective_user
    qty = await user_has_card(user.id, card_id)

    caption = (
        f"🃏 {card['name']}\n"
        f"Редкость: {rarity_to_emoji(card['rarity'])}\n"
        f"ID: {card['id']}\n"
        f"У тебя: {qty} шт."
    )

    image_path = get_image_path(card)

    if os.path.exists(image_path):
        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(caption + "\n\n⚠️ (изображение не найдено)")

# ---------- ЗАПУСК ----------
def main():
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)
        print(f"Создана папка {IMAGES_DIR}/ — положи туда картинки карт!")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("card", card))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("album", album))
    app.add_handler(CommandHandler("cardinfo", cardinfo))
    app.add_handler(CallbackQueryHandler(album_callback, pattern="^album_"))

    print("Запуск бота...")
    asyncio.run(init_db())
    app.run_polling()

if __name__ == "__main__":
    main()
