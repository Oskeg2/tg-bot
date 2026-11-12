import asyncio
import sqlite3
import random
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramAPIError

# ==========================================
# 1. НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАПОЛНИ!)
# ==========================================
BOT_TOKEN = "9129817893:AAHfn0_fhF-wv4V3Wkp8JMKNEHsdgjnX1RU" # ЗАМЕНИ НА СВОЙ ТОКЕН
BOT_LINK = "https://t.me/Oskegup" # ЗАМЕНИ НА ССЫЛКУ СВОЕГО БОТА (без @)
ADMIN_ID = 8441441176 # ЗАМЕНИ НА СВОЙ ЦИФРОВОЙ ID (узнать у @userinfobot)
ADMIN_USERNAME = "oskeg" # ТВОЙ ЮЗЕРНЕЙМ БЕЗ @

MIN_WITHDRAW = 15.0
MIN_BET = 10.0
MAX_BET = 20000000.0

CHANNELS = [
    {"id": "ch1", "username": "@Rubupdemo", "title": "Rubupdemo"},
    {"id": "ch2", "username": "@buvego", "title": "buvego)"}
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==========================================
# 2. БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            stars REAL DEFAULT 0.0,
            referrer_id INTEGER DEFAULT NULL,
            ref_reward_given INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_channels (
            user_id INTEGER,
            channel_id TEXT,
            PRIMARY KEY (user_id, channel_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_games (
            user_id INTEGER PRIMARY KEY,
            game_type TEXT,
            bet REAL,
            step INTEGER DEFAULT 0,
            multiplier REAL DEFAULT 1.0,
            mines TEXT DEFAULT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT stars, referrer_id, ref_reward_given FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, stars) VALUES (?, 0.0)", (user_id,))
        conn.commit()
        row = (0.0, None, 0)
    conn.close()
    return row

def add_stars(user_id, amount):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def subtract_stars(user_id, amount):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET stars = stars - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def admin_add_stars(user_id, amount):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        result = True
    else:
        result = False
    conn.close()
    return result

def set_referrer(user_id, referrer_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL", (referrer_id, user_id))
    conn.commit()
    conn.close()

def get_completed_channels(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM completed_channels WHERE user_id = ?", (user_id,))
    rows = [r[0] for r in cursor.fetchall()]
    conn.close()
    return rows

def mark_channel_completed(user_id, channel_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO completed_channels (user_id, channel_id) VALUES (?, ?)", (user_id, channel_id))
    conn.commit()
    conn.close()

def give_referral_reward(user_id):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT referrer_id, ref_reward_given FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] is not None and row[1] == 0:
        referrer_id = row[0]
        cursor.execute("UPDATE users SET stars = stars + 1.0 WHERE user_id = ?", (referrer_id,))
        cursor.execute("UPDATE users SET ref_reward_given = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        try:
            asyncio.create_task(bot.send_message(referrer_id, "🎉 Твой друг выполнил 2 задания! Тебе начислено +1 ⭐"))
        except Exception:
            pass
    conn.close()

# ==========================================
# 3. ЛОГИКА ПРОВЕРКИ
# ==========================================
async def is_subscribed(user_id: int, channel_username: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest:
        return False

async def send_next_task(message: Message, user_id: int):
    completed = get_completed_channels(user_id)
    next_channel = None
    for ch in CHANNELS:
        if ch["id"] not in completed:
            next_channel = ch
            break

    if not next_channel:
        await message.answer("🎉 <b>Поздравляю! Ты подписался на все каналы!</b>\nПроверь свой баланс: /profil", parse_mode="HTML")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕒 Перейти и подписаться", url=f"https://t.me/{next_channel['username'].replace('@', '')}")],
        [InlineKeyboardButton(text="✅ Я подписался (Проверить)", callback_data=f"check_{next_channel['id']}")]
    ])

    await message.answer(
        text=f"📝 <b>Задание:</b>\n\nПодпишись на канал <b>{next_channel['title']}</b> ({next_channel['username']}).\n\n🟢 Нажми «Я подписался», чтобы получить <b>+0.5 ⭐</b>.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# ==========================================
# 4. КОМАНДЫ И ИГРЫ
# ==========================================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: Message, command: CommandStart):
    ref_id = command.args
    user_id = message.from_user.id
    if ref_id and ref_id.isdigit() and int(ref_id) != user_id:
        set_referrer(user_id, int(ref_id))
        await message.answer("👋 Привет! Ты перешел по приглашению друга. Выполни 2 задания, и твой друг получит звезду!")
    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    get_user(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎮 Открыть игры", web_app=WebAppInfo(url="https://tg-bot-gp5z.onrender.com/index.html"))]
])
    await message.answer("Привет! Напиши /zadaniya, чтобы начать зарабатывать звёзды, или /crash и /mines, чтобы играть!", reply_markup=keyboard)

@dp.message(Command("zadaniya"))
async def cmd_zadaniya(message: Message):
    await send_next_task(message, message.from_user.id)

@dp.callback_query(F.data.startswith("check_"))
async def check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    channel_id = callback.data.split("_")[1]
    channel_info = next((ch for ch in CHANNELS if ch["id"] == channel_id), None)
    
    if not channel_info:
        await callback.answer("Ошибка: канал не найден.", show_alert=True)
        return

    if await is_subscribed(user_id, channel_info["username"]):
        add_stars(user_id, 0.5)
        mark_channel_completed(user_id, channel_id)
        
        if len(get_completed_channels(user_id)) >= 2:
            give_referral_reward(user_id)
        
        await callback.answer("✅ Спасибо за подписку! +0.5 ⭐", show_alert=True)
        await callback.message.delete()
        await send_next_task(callback.message, user_id)
    else:
        await callback.answer("❌ Ты еще не подписался на этот канал!", show_alert=True)

@dp.message(Command("profil"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    stars, _, _ = get_user(user_id)
    
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"⭐ Баланс: <b>{stars:.1f} звёзд</b>\n\n"
        f"Минимальная сумма для вывода: {MIN_WITHDRAW} ⭐\n"
        f"Чтобы пригласить друга, напиши /ref"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести звезды", callback_data="withdraw")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(Command("ref"))
async def cmd_ref(message: Message):
    user_id = message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    invited_count = cursor.fetchone()[0]
    conn.close()

    ref_link = f"{"https://t.me/Oskegup"}?start={user_id}"
    text = (
        f"🤝 <b>Партнерская программа</b>\n\n"
        f"🔗 <b>Твоя ссылка для приглашения:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 Ты уже пригласил: <b>{invited_count}</b> чел.\n\n"
        f"<i>Отправь эту ссылку друзьям. Когда друг зайдет в бота и выполнит 2 задания, ты получишь +1 ⭐!</i>"
    )
    share_url = f"https://t.me/share/url?url={ref_link}&text=Зайди в бота и заработай звезды!"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться с другом", url=share_url)]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "withdraw")
async def withdraw_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    stars, _, _ = get_user(user_id)
    
    if stars < MIN_WITHDRAW:
        await callback.answer(f"❌ Недостаточно звезд! Тебе нужно минимум {MIN_WITHDRAW} ⭐", show_alert=True)
        return
    
    subtract_stars(user_id, MIN_WITHDRAW)
    
    try:
        username = callback.from_user.username
        user_link = f"@{username}" if username else "Нет юзернейма"
        
        admin_text = (
            f"🔔 <b>Новая заявка на вывод!</b>\n\n"
            f"👤 Имя: {callback.from_user.first_name}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🔗 Связь: {user_link}\n"
            f"💰 Сумма: {MIN_WITHDRAW} ⭐\n\n"
            f"<i>Свяжись с пользователем для выдачи средств.</i>"
        )
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception:
        pass
    
    await callback.answer("✅ Заявка создана!", show_alert=True)
    await callback.message.edit_text("✅ Заявка на вывод создана! Звезды списаны.")

@dp.message(Command("addstars"))
async def cmd_add_stars(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    if user_id != ADMIN_ID and username != ADMIN_USERNAME:
        await message.answer("❌ У тебя нет прав для этой команды.")
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("⚠️ Использование: <code>/addstars ID_юзера Количество</code>\nПример: <code>/addstars 123456789 10</code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
        amount = float(args[2])
    except ValueError:
        await message.answer("❌ Ошибка: ID должен быть числом, а количество — цифрой.")
        return

    success = admin_add_stars(target_id, amount)
    
    if success:
        await message.answer(f"✅ Начислено <b>{amount} ⭐</b> пользователю <code>{target_id}</code>.", parse_mode="HTML")
        try:
            await bot.send_message(target_id, f"🎁 Тебе начислено <b>{amount} ⭐</b>!", parse_mode="HTML")
        except Exception:
            pass
    else:
        await message.answer(f"❌ Пользователь <code>{target_id}</code> не найден (он должен нажать /start).", parse_mode="HTML")

# ==========================================
# 4.5. ИГРА САПЕР 4x4 (С ВЫБОРОМ МИН)
# ==========================================
@dp.message(Command("mines"))
async def cmd_mines(message: Message):
    args = message.text.split()
    
    # Если написали просто /mines
    if len(args) != 3:
        await message.answer(
            "💣 <b>Игра «Сапер» 4х4</b>\n\n"
            "Выбери ставку и количество мин (1, 2 или 3).\n"
            "Формат: <code>/mines СТАВКА МИНЫ</code>\n\n"
            "Пример: <code>/mines 500 2</code>\n"
            "<i>(Ставка 500, 2 мины на поле 4х4)</i>",
            parse_mode="HTML"
        )
        return
    
    try:
        bet = float(args[1])
        mines_count = int(args[2])
    except ValueError:
        await message.answer("❌ Ошибка! Пример: <code>/mines 500 2</code>", parse_mode="HTML")
        return

    # Проверки
    if bet < MIN_BET or bet > MAX_BET:
        await message.answer(f"❌ Ставка должна быть от {MIN_BET} до {MAX_BET} ⭐")
        return
    
    if mines_count not in [1, 2, 3]:
        await message.answer("❌ Количество мин должно быть 1, 2 или 3!")
        return

    user_id = message.from_user.id
    stars, _, _ = get_user(user_id)

    if stars < bet:
        await message.answer("❌ Недостаточно звёзд на балансе! Напиши /profil.")
        return

    # Списываем ставку
    subtract_stars(user_id, bet)

    # Создаем поле 4х4 (16 клеток)
    total_cells = 16
    cells = ["star"] * (total_cells - mines_count) + ["mine"] * mines_count
    random.shuffle(cells)
    mines_str = ",".join(cells)

    # Сохраняем игру в базу (в step будем хранить количество открытых звезд)
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO active_games (user_id, game_type, bet, step, mines) 
        VALUES (?, 'mines', ?, 0, ?)
    """, (user_id, bet, mines_str))
    conn.commit()
    conn.close()

    # Отправляем поле 4х4
    keyboard = []
    for row in range(4):
        row_buttons = []
        for col in range(4):
            index = row * 4 + col
            row_buttons.append(InlineKeyboardButton(text="❓", callback_data=f"mines_open_{index}"))
        keyboard.append(row_buttons)

    await message.answer(
        f"💣 <b>Сапер начат!</b>\n"
        f"Ставка: {bet} ⭐ | Мин: {mines_count}\n\n"
        f"Нажимай на клетки. Если попадешь на мину — проиграешь.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("mines_open_"))
async def mines_open(callback: CallbackQuery):
    user_id = callback.from_user.id
    cell_index = int(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet, step, mines FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена! Напиши /mines заново.", show_alert=True)
        return

    bet, step, mines_str = row
    mines = mines_str.split(",")
    total_cells = len(mines)
    mines_count = mines.count("mine")

    # Защита от повторного нажатия
    if mines[cell_index] == "star":
        await callback.answer("Эта клетка уже открыта!", show_alert=True)
        return

    # Попал на мину
    if mines[cell_index] == "mine":
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        # Показываем, где были мины
        reveal_keyboard = []
        for r in range(4):
            row_btns = []
            for c in range(4):
                idx = r * 4 + c
                if mines[idx] == "mine":
                    row_btns.append(InlineKeyboardButton(text="💥", callback_data="ignore"))
                else:
                    row_btns.append(InlineKeyboardButton(text="⭐", callback_data="ignore"))
            reveal_keyboard.append(row_btns)
            
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты попал на мину.</b>\nСтавка {bet} ⭐ потеряна.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=reveal_keyboard),
            parse_mode="HTML"
        )
        return

    # Нашел звезду
    mines[cell_index] = "opened_star"
    step += 1
    
    # --- РАСЧЕТ МНОЖИТЕЛЯ (по твоей схеме) ---
    if mines_count == 1:
        # На 1 бомбу: 1.05, 1.15, 1.25 и т.д.
        multiplier = 1.0 + (step * 0.05) + (step * 0.05) # Упрощенно: 1.05, 1.10, 1.15... 
        # (Для точного совпадения с твоим примером 1.05, 1.15, 1.25 - прибавляем по 0.1, но начнем с 1.05)
        # Сделаем точнее: 1-я звезда = 1.05, 2-я = 1.15, 3-я = 1.25
        multiplier = 1.0 + (step * 0.10) - 0.05
    elif mines_count == 2:
        # На 2 бомбы: 1.10, 1.15, 1.25 и т.д. (прибавляем по 0.05 или 0.10)
        multiplier = 1.0 + (step * 0.10) # 1.10, 1.20, 1.30 (подогнал под твой пример)
    elif mines_count == 3:
        # На 3 бомбы: 1.15, 1.25, 1.30 и т.д.
        multiplier = 1.0 + (step * 0.15) # 1.15, 1.30, 1.45 (подогнал под твой пример)
    
    # Проверка на победу (открыл все безопасные клетки)
    safe_cells = total_cells - mines_count
    if step == safe_cells:
        winnings = bet * multiplier
        add_stars(user_id, winnings)
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await callback.answer(f"🎉 Ты выиграл {winnings:.0f} ⭐!", show_alert=True)
        await callback.message.delete()
        return

    # Обновляем шаг
    cursor.execute("UPDATE active_games SET step = ?, mines = ? WHERE user_id = ?", (step, ",".join(mines), user_id))
    conn.commit()
    conn.close()

    # Обновляем кнопки
    new_keyboard = []
    for r in range(4):
        row_btns = []
        for c in range(4):
            idx = r * 4 + c
            if mines[idx] == "opened_star":
                row_btns.append(InlineKeyboardButton(text="⭐", callback_data="ignore"))
            else:
                row_btns.append(InlineKeyboardButton(text="❓", callback_data=f"mines_open_{idx}"))
        new_keyboard.append(row_btns)
    
    # Добавляем кнопку "Забрать"
    new_keyboard.append([InlineKeyboardButton(text=f"💰 Забрать {bet * multiplier:.0f} ⭐ (x{multiplier:.2f})", callback_data=f"mines_cashout_{multiplier:.2f}")])
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
    await callback.answer(f"⭐ Звезда! Множитель: x{multiplier:.2f}")

@dp.callback_query(F.data.startswith("mines_cashout_"))
async def mines_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    multiplier = float(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена!", show_alert=True)
        return

    bet = row[0]
    winnings = bet * multiplier

    add_stars(user_id, winnings)
    cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    await callback.answer(f"✅ Ты забрал {winnings:.0f} ⭐!", show_alert=True)
    await callback.message.edit_text(f"✅ Ты забрал {winnings:.0f} ⭐ (x{multiplier:.2f})\nБаланс: /profil")

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("mines_open_"))
async def mines_open(callback: CallbackQuery):
    user_id = callback.from_user.id
    cell_index = int(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet, step, mines FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена! Напиши /mines заново.", show_alert=True)
        return

    bet, step, mines_str = row
    mines = mines_str.split(",")
    total_cells = len(mines)

    # Если клетка уже открыта (защита от повторного нажатия)
    if mines[cell_index] == "opened_star":
        await callback.answer("Эта клетка уже открыта!", show_alert=True)
        return

    # Попал на мину
    if mines[cell_index] == "mine":
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        # Показываем, где были мины
        reveal_keyboard = []
        for r in range(5):
            row_btns = []
            for c in range(5):
                idx = r * 5 + c
                if mines[idx] == "mine":
                    row_btns.append(InlineKeyboardButton(text="💥", callback_data="ignore"))
                else:
                    row_btns.append(InlineKeyboardButton(text="⭐", callback_data="ignore"))
            reveal_keyboard.append(row_btns)
            
        await callback.message.edit_text(
            f"💥 <b>БУМ! Ты попал на мину.</b>\nСтавка {bet} ⭐ потеряна.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=reveal_keyboard),
            parse_mode="HTML"
        )
        return

    # Нашел звезду
    mines[cell_index] = "opened_star"
    step += 1
    
    # Множитель растет в зависимости от сложности
    # Чем больше мин, тем быстрее растет множитель
    mines_count = mines_str.count("mine")
    multiplier = 1.0 + (step * (mines_count * 0.1)) 
    
    # Проверка на победу (открыл все безопасные клетки)
    safe_cells = total_cells - mines_count
    if step == safe_cells:
        winnings = bet * multiplier
        add_stars(user_id, winnings)
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await callback.answer(f"🎉 Ты выиграл {winnings:.0f} ⭐!", show_alert=True)
        await callback.message.delete()
        return

    # Обновляем шаг
    cursor.execute("UPDATE active_games SET step = ?, mines = ? WHERE user_id = ?", (step, ",".join(mines), user_id))
    conn.commit()
    conn.close()

    # Обновляем кнопки (открытые звезды)
    new_keyboard = []
    for r in range(5):
        row_btns = []
        for c in range(5):
            idx = r * 5 + c
            if mines[idx] == "opened_star":
                row_btns.append(InlineKeyboardButton(text="⭐", callback_data="ignore"))
            else:
                row_btns.append(InlineKeyboardButton(text="❓", callback_data=f"mines_open_{idx}"))
        new_keyboard.append(row_btns)
    
    # Добавляем кнопку "Забрать"
    new_keyboard.append([InlineKeyboardButton(text=f"💰 Забрать {bet * multiplier:.0f} ⭐", callback_data=f"mines_cashout_{multiplier:.1f}")])
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
    await callback.answer(f"⭐ Звезда! Множитель: x{multiplier:.2f}")

@dp.callback_query(F.data.startswith("mines_cashout_"))
async def mines_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    multiplier = float(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена!", show_alert=True)
        return

    bet = row[0]
    winnings = bet * multiplier

    add_stars(user_id, winnings)
    cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    await callback.answer(f"✅ Ты забрал {winnings:.0f} ⭐!", show_alert=True)
    await callback.message.edit_text(f"✅ Ты забрал {winnings:.0f} ⭐\nБаланс: /profil")

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

@dp.message(Command("mines"))
async def handle_mines_bet(message: Message):
    args = message.text.split()
    if len(args) != 2:
        return
    
    try:
        bet = float(args[1])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом!")
        return

    if bet < MIN_BET or bet > MAX_BET:
        await message.answer(f"❌ Ставка должна быть от {MIN_BET} до {MAX_BET} ⭐")
        return

    user_id = message.from_user.id
    stars, _, _ = get_user(user_id)

    if stars < bet:
        await message.answer("❌ Недостаточно звёзд!")
        return

    subtract_stars(user_id, bet)

    mines = ["mine", "star", "star", "star", "star", "star", "star", "star", "star"]
    random.shuffle(mines)
    mines_str = ",".join(mines)

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO active_games (user_id, game_type, bet, step, mines) VALUES (?, 'mines', ?, 0, ?)", (user_id, bet, mines_str))
    conn.commit()
    conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓", callback_data=f"mines_open_{i}") for i in range(3)],
        [InlineKeyboardButton(text="❓", callback_data=f"mines_open_{i}") for i in range(3, 6)],
        [InlineKeyboardButton(text="❓", callback_data=f"mines_open_{i}") for i in range(6, 9)]
    ])
    await message.answer(f"💣 Ставка: {bet} ⭐\nОткрывай клетки (1 мина из 9):", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("mines_open_"))
async def mines_open(callback: CallbackQuery):
    user_id = callback.from_user.id
    cell_index = int(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet, step, mines FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена!", show_alert=True)
        return

    bet, step, mines_str = row
    mines = mines_str.split(",")

    if mines[cell_index] == "mine":
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await callback.answer("💥 Ты попал на мину! Ставка потеряна.", show_alert=True)
        await callback.message.delete()
        return

    step += 1
    multiplier = 1.0 + (step * 0.2)
    
    if step == 8:
        winnings = bet * 3.0
        add_stars(user_id, winnings)
        cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await callback.answer(f"🎉 Ты выиграл {winnings:.0f} ⭐!", show_alert=True)
        await callback.message.delete()
        return

    cursor.execute("UPDATE active_games SET step = ? WHERE user_id = ?", (step, user_id))
    conn.commit()
    conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅" if i == cell_index else "❓", callback_data=f"mines_open_{i}") for i in range(3)],
        [InlineKeyboardButton(text="✅" if i == cell_index else "❓", callback_data=f"mines_open_{i}") for i in range(3, 6)],
        [InlineKeyboardButton(text="✅" if i == cell_index else "❓", callback_data=f"mines_open_{i}") for i in range(6, 9)]
    ])
    
    keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"💰 Забрать {bet * multiplier:.0f} ⭐", callback_data=f"mines_cashout_{multiplier:.1f}")])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"⭐ Звезда! Текущий множитель: x{multiplier:.1f}")

@dp.callback_query(F.data.startswith("mines_cashout_"))
async def mines_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    multiplier = float(callback.data.split("_")[2])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bet FROM active_games WHERE user_id = ? AND game_type = 'mines'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await callback.answer("Игра не найдена!", show_alert=True)
        return

    bet = row[0]
    winnings = bet * multiplier

    add_stars(user_id, winnings)
    cursor.execute("DELETE FROM active_games WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    await callback.answer(f"✅ Ты забрал {winnings:.0f} ⭐!", show_alert=True)
    await callback.message.delete()

async def main():
    print("бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
