import asyncio
import json
import re
import sys
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ChatPermissions
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram import types

# FSM uchun holatlar
class AddWordState(StatesGroup):
    waiting_for_word = State()

# =============================================================================
# Konfiguratsiya va bot obyektlarini yaratish
# =============================================================================
API_TOKEN = "7640175151:AAEtMBHRDp1bB-x5YVB7b4kv778NqHUb0Ww"

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Bot adminligini tekshirish
async def is_bot_admin(chat_id: int) -> bool:
    try:
        bot_member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
        return bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

# Xabarlarni avtomatik o'chirish
async def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Xabarni o'chirishda xatolik: {e}")

# =============================================================================
# Konfiguratsiya parametrlari
# =============================================================================
MAX_STRIKES = 3
MUTE_DURATION = 5  # daqiqa
BAN_DURATION = 1440  # daqiqa (24 soat)
STRIKES_FILE = "strikes.json"
HATEFUL_WORDS_FILE = "haqoratli_sozlar.json"
GROUP_WORDS_DIR = "group_custom_words"

# Guruh papkasini yaratish
if not os.path.exists(GROUP_WORDS_DIR):
    os.makedirs(GROUP_WORDS_DIR)


# =============================================================================
# Strike tizimi funksiyalari
# =============================================================================
def load_strikes():
    if os.path.exists(STRIKES_FILE):
        with open(STRIKES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_strikes(strikes):
    with open(STRIKES_FILE, "w", encoding="utf-8") as f:
        json.dump(strikes, f, ensure_ascii=False, indent=2)


async def add_strike(user_id, chat_id):
    strikes = load_strikes()
    user_key = f"{chat_id}_{user_id}"

    if user_key not in strikes:
        strikes[user_key] = {"count": 0, "last_warn": None}

    strikes[user_key]["count"] += 1
    strikes[user_key]["last_warn"] = str(datetime.now())
    save_strikes(strikes)
    return strikes[user_key]["count"]


def get_remaining_strikes(user_id, chat_id):
    strikes = load_strikes()
    user_key = f"{chat_id}_{user_id}"
    return MAX_STRIKES - strikes.get(user_key, {}).get("count", 0)


# =============================================================================
# So'zlar bilan ishlash funksiyalari
# =============================================================================
def get_group_words_file(chat_id: int) -> str:
    return f"{GROUP_WORDS_DIR}/group_{chat_id}.json"


def load_group_words(chat_id: int) -> list:
    group_file = get_group_words_file(chat_id)
    try:
        with open(group_file, "r", encoding="utf-8") as f:
            return json.load(f).get("words", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_group_words(chat_id: int, words: list):
    group_file = get_group_words_file(chat_id)
    data = {"words": words}
    with open(group_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =============================================================================
# Unit testlar va regex funksiyasi
# =============================================================================
def is_hateful(text, hateful_word):
    pattern = r"(?:\b|[^a-zA-Z0-9_])" + re.escape(hateful_word) + r"(?:\b|[^a-zA-Z0-9_])"
    return re.search(pattern, text.lower()) is not None


def test_is_hateful():
    hateful_word = "yomon"
    assert is_hateful("Bu juda yomon gap!", hateful_word) == True
    assert is_hateful("Bu gap juda yaxshi", hateful_word) == False
    assert is_hateful("YAMON gap", hateful_word) == True
    assert is_hateful("bu yamon gap emas", hateful_word) == False


# =============================================================================
# Ma'lumotlarni yuklash
# =============================================================================
try:
    with open(HATEFUL_WORDS_FILE, "r", encoding="utf-8") as file:
        HATEFUL_WORDS = json.load(file)["hate_words"]
    print(f"Haqoratli so'zlar yuklandi: {HATEFUL_WORDS}")
except Exception as e:
    print(f"Xatolik yuz berdi: {e}")
    HATEFUL_WORDS = []

# =============================================================================
# Reklama patternlari
# =============================================================================
ad_patterns = [
    # Yangi qo'shilganlar
    r"(?i)(bizni\s*manzilga\s*o'?ting|havolaga\s*o'?ting|bizga\s*qo'shiling|shu\s*yerni\s*bosib\s*kirish)",
    r"\b(botni\s*bosish|havolani\s*bosish)\b",
    r"(manzil:\s*\S+)",

    # Avvalgi mavjud regexlar
    r"(https?://\S+)",
    r"(www\.\S+)",
    r"(telegram\.(me|org|dog)/\S+)",
    r"\b(pul\s+topish|tez\s+boyish|kredit|online\s+biznes|promo\s?code|bonus|sotiladi|sotaman|sotish|sotamiz|narx|arzon)\b",
    r"@\w+",
    r"\b[^\s]+\.(uz|com|net|org|info|ru|hyz|tk|ml|ga|cf|gq)(/[^\s]*)?\b",
    r"<a\s+href=['\"](https?://\S+)['\"][^>]*>.*?</a>",
    r"\[.*?\]\((https?://\S+)\)",
    r"\{.*?\}\(https?://\S+\)",
    r"[\u200B-\u200D\uFEFF]",
    r"\s{5,}",
    r"(.+?)(\1\s*){3,}",
    r"tg://resolve\?domain=\w+",
    r"t\.me/joinchat/\S+",
    r"t\.me/\w+(\?start=\w+)?",
    r"t\.me/addstickers/\S+",
    r"🔗\s*\S+",
    r"➡️\s*\S+",
    r"\((?:https?://|t\.me)\S+\)",
    r"→\s*\S+",
    r"(?i)boshlash|start|qo'shilish"
]



# =============================================================================
# Qo'shimcha funksiyalar
# =============================================================================
def extract_hidden_links(text: str) -> list:
    patterns = [
        r"<a\s+href=[\"'](https?://\S+)[\"']",
        r"\[.*?\]\((https?://\S+)\)",
        r"\{.*?\}\(https?://\S+\)",
        r"tg://resolve\?domain=(\w+)",
        r"t\.me/\w+\?start=(\w+)"
    ]

    found_links = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found_links.extend(matches)

    return list(set(found_links))


# =============================================================================
# Message handlerlari
# =============================================================================
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.reply(
        "Salom, botimizga xush kelibsiz! Bot guruhdagi haqoratli so'zlar va reklama yuborishlarni o'chirib beradi.")


@dp.message(Command("rules"))
async def send_rules(message: types.Message):
    await message.reply(
        "Guruh qoidalari:\n1. Haqoratli so'z ishlatmaslik.\n2. Reklama yubormaslik.\n3. Qoida buzganlar ban qilinadi.")


@dp.message(Command("help"))
async def send_help(message: types.Message):
    await message.reply(
        "Bot buyruqlari:\n/start - Botni ishga tushirish.\n/rules - Guruh qoidalarini ko'rish.\n/help - Yordam olish.\n/addword yomon - Haqoratli yoki Reklama ishlatilgan so'z qo'shish uchun.\n/removeword yomon - Haqoratli so'z o'chirish uchun.\nQo'shimcha qo'llanma @uzbtgbotlar")


@dp.message(Command("addword"), F.chat.type.in_({"group", "supergroup"}))
# `/addword` komandasi yuborilganda foydalanuvchidan so'zni so'rash
async def add_word_start(message: types.Message, state: FSMContext):
    chat_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    if chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        await message.reply("❌ Bu buyruq faqat adminlar uchun!")
        return

    await message.reply("⚠️ So'z kiritishingizni kutyapman. Masalan: <code>jinni</code>", parse_mode="HTML")
    await state.set_state(AddWordState.waiting_for_word)

# Kiritilgan so'zni qabul qilish va saqlash
async def add_word_finish(message: types.Message, state: FSMContext):
    word = message.text.lower().strip()
    chat_id = message.chat.id

    group_words = load_group_words(chat_id)
    if word in group_words:
        await message.reply(f"⚠️ '{word}' allaqachon mavjud!")
    else:
        group_words.append(word)
        save_group_words(chat_id, group_words)
        await message.reply(f"✅ '{word}' guruh ro'yxatiga qo'shildi!")

    # Holatni tugatish
    await state.clear()
    
@dp.message(Command("removeword"), F.chat.type.in_({"group", "supergroup"}))
async def remove_word_command(message: types.Message):
    try:
        chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status not in [types.ChatMemberStatus.ADMINISTRATOR, types.ChatMemberStatus.CREATOR]:
            await message.reply("❌ Bu buyruq faqat adminlar uchun!")
            return

        args = message.text.split()
        if len(args) < 2:
            await message.reply("⚠️ Iltimos, so'z kiriting!\nMasalan: <code>/removeword jinni</code>",
                                parse_mode="HTML")
            return

        word = args[1].lower().strip()
        chat_id = message.chat.id

        group_words = load_group_words(chat_id)
        if word in group_words:
            group_words.remove(word)
            save_group_words(chat_id, group_words)
            await message.reply(f"✅ '{word}' o'chirildi!")
        else:
            await message.reply(f"❌ '{word}' topilmadi!")

    except Exception as e:
        print(f"Xatolik: {e}")
        await message.reply("❌ Xatolik yuz berdi!")


@dp.message(F.chat.type.in_({"group", "supergroup"}) & (F.new_chat_members | F.left_chat_member))
async def handle_join_leave_messages(message: types.Message):
    try:
        if message.new_chat_members:
            for new_member in message.new_chat_members:
                welcome_msg = await message.reply(f"Salom, {new_member.full_name}! Guruhga xush kelibsiz!")
                asyncio.create_task(delete_message_after_delay(message.chat.id, welcome_msg.message_id, 30))
            await bot.delete_message(message.chat.id, message.message_id)
        elif message.left_chat_member:
            await bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        print(f"Xatolik: {e}")


async def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Xabarni o'chirishda xatolik: {e}")


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def filter_messages(message: types.Message):
    # 1. Kanal xabarlarini va anonim adminlarni o'tkazib yuborish
    if message.sender_chat:
        return

    # 2. Adminlarni tekshirish
    try:
        chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            return
    except Exception as e:
        print(f"Xatolik: {e}")
        return

    # 3. Filtrlash logikasi (faqat 1 marta)
    text = message.text or message.caption or ""
    text_lower = text.lower()
    chat_id = message.chat.id

    # Haqoratli so'zlar
    banned_words = HATEFUL_WORDS + load_group_words(chat_id)
    for word in banned_words:
        if is_hateful(text_lower, word):
            await handle_offense(message, "haqorat")
            return

    # Yashirin havolalar
    hidden_links = extract_hidden_links(text)
    if hidden_links:
        await handle_offense(message, "hidden_link", links=hidden_links)
        return

    # Reklama
    for pattern in ad_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            await handle_offense(message, "reklama")
            return

async def handle_offense(message: types.Message, offense_type: str, links: list = None):
    # Bot adminligini tekshirish
    is_admin = await is_bot_admin(message.chat.id)

    if is_admin:
        # Xabarni o'chirish
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Xabarni o'chirishda xatolik: {e}")
            return

        # Ogohlantirish xabarini yuborish
        user = message.from_user
        remaining = get_remaining_strikes(user.id, message.chat.id)
        warning_msg = f"⚠️ <b>{user.full_name}</b>, ogohlantirish:\n"

        if offense_type == "haqorat":
            warning_msg += "⛔ Haqoratli so'z ishlatildi!"
        elif offense_type == "hidden_link":
            warning_msg += "🔗 Yashirin havolalar topildi!"
            if links:
                warning_msg += "\nBloklangan havolalar: " + ", ".join(links[:3])
        elif offense_type == "reklama":
            warning_msg += "📢 Reklama aniqlindi!"

        warning_msg += f"\nQolgan imkoniyat: {remaining}"

        try:
            sent_msg = await message.answer(warning_msg, parse_mode="HTML")
            asyncio.create_task(delete_message_after_delay(message.chat.id, sent_msg.message_id, 30))
        except Exception as e:
            print(f"Ogohlantirish yuborishda xatolik: {e}")

        # Strike qo'shish va ban
        current_strikes = await add_strike(user.id, message.chat.id)
        if current_strikes >= MAX_STRIKES:
            try:
                await bot.ban_chat_member(
                    chat_id=message.chat.id,
                    user_id=user.id,
                    until_date=datetime.now() + timedelta(minutes=BAN_DURATION)
                )
                await message.answer(f"🚫 {user.full_name} {MAX_STRIKES} ogohlantirishdan keyin bloklandi!")
            except Exception as e:
                print(f"Ban qilishda xatolik: {e}")
    else:
        # Bot admin bo'lmasa, guruhga reply qilish
        user = message.from_user
        public_report = (
            f"⚠️ <b>{user.full_name}</b> ({user.mention}), diqqat!\n"
            f"🔍 Sabab: {offense_type.capitalize()} aniqlandi\n"
            f"📝 Guruhga reklama yoki haqoratli xabar tarqatmang!\n"
            f"ℹ️ Botni admin qiling, aks holda bunday xabarlarni o'chira olmayman!"
        )
        try:
            # Xabarni reply qilib guruhga yuborish
            await message.reply(public_report, parse_mode="HTML")
        except Exception as e:
            print(f"Guruhga xabar yuborishda xatolik: {e}")
            # Agar reply ishlamasa, oddiy xabar yuborishga urinamiz
            try:
                await bot.send_message(message.chat.id, public_report, parse_mode="HTML")
            except Exception as e2:
                print(f"Xabar yuborish umuman muvaffaqiyatsiz: {e2}")
# =============================================================================
# Asosiy ishga tushirish
# =============================================================================
async def main():
    print("Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        import pytest

        pytest.main([__file__])
    else:
        asyncio.run(main())