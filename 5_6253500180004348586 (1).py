import logging
import asyncio
from datetime import datetime
import pytz
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import Command, CommandObject
from aiogram.utils.formatting import Bold, CustomEmoji, Text, TextLink
from aiogram.exceptions import TelegramBadRequest
import re
from aiogram.types import Message, ChatJoinRequest

# Configure logging
logging.basicConfig(level=logging.INFO)

# Your valid Bot Token
BOT_TOKEN = "8882985083:AAE2Hpazlkn0w__F7t5ygtANchdjJEEGF3U"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

REQUIRED_CHANNELS = [-1003984401347, -1003597837461]

# Place this at the top level of your file along with other global variables
WELCOME_SETUP_STATE = {}
# GLOBAL_WELCOME_STATES = {}

# System initialization timestamp in IST
START_TIME_IST = datetime.now(pytz.timezone('Asia/Kolkata'))


# Database name reference
DB_NAME = "bot_factory.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Master Cloned Bots Registry Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cloned_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bot_id TEXT UNIQUE,
                bot_token TEXT UNIQUE,
                bot_username TEXT,
                theme TEXT,
                created_at TEXT
            )
        """)
        
        # 2. Private Channel Join Requests Analytics Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS child_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                channel_id TEXT,
                user_id INTEGER,
                requested_at TEXT
            )
        """)
        
        await db.commit()

        # Check and handle database migration column hot-patches seamlessly
        async with db.execute("PRAGMA table_info(cloned_bots)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            
        if "bot_id" not in columns:
            await db.execute("ALTER TABLE cloned_bots ADD COLUMN bot_id TEXT DEFAULT 'None'")
            await db.commit()
            print("Successfully patched 'bot_id' column inside cloned_bots!")



async def init_system_tables():
    """Run this immediately at the start of your main() function."""
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Balances Matrix
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER, 
                bot_id INTEGER,
                balance REAL DEFAULT 0.0,
                PRIMARY KEY(user_id, bot_id)
            )
        """)
        # Update your existing init_system_tables function:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS child_bot_settings (
                bot_id INTEGER PRIMARY KEY,
                status_state TEXT DEFAULT 'Active',
                device_verification TEXT DEFAULT 'On',
                payout_mode TEXT DEFAULT 'AUTO',
                min_withdraw REAL DEFAULT 100.0,
                max_withdraw REAL DEFAULT 10000.0,
                withdraw_tax INTEGER DEFAULT 0,
                req_referrals INTEGER DEFAULT 3,
                cooldown TEXT DEFAULT 'off',
                bonus_amount TEXT DEFAULT 'Tell Me',
                bonus_mode TEXT DEFAULT '',
                refer_amount TEXT DEFAULT 'Tell Me',
                refer_mode TEXT DEFAULT ''
            )
        """)

        # 3. Verification Matrix (FIXED: This was missing from your master initialization)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id INTEGER,
                bot_id INTEGER,
                seen INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, bot_id)
            )
        """)
        # 4. Referrals Matrix
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_referrals (
                referrer_id INTEGER,
                referred_id INTEGER,
                bot_id INTEGER,
                PRIMARY KEY(referred_id, bot_id)
            )
        """)
        # 5. Gateways
        await db.execute("""
            CREATE TABLE IF NOT EXISTS child_gateways (
                bot_id INTEGER PRIMARY KEY,
                techpay_status TEXT DEFAULT 'Disabled',
                payzy_status TEXT DEFAULT 'Disabled',
                techpay_token TEXT DEFAULT 'None',
                payzy_token TEXT DEFAULT 'None',
                ultrapay_token TEXT DEFAULT 'None',
                ultrapay_key TEXT DEFAULT 'None',
                ultrapay_base_url TEXT DEFAULT 'https://ultra-pay.store/APIs/api',
                payzy_base_url TEXT DEFAULT 'https://payzy-gateway.site/api/transfer'
            )
        """)
        await db.commit()
    print("✅ All system tables (including user_verification) verified and ready.")

async def init_gift_code_tables():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                code TEXT,
                amount REAL,
                req_referrals INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 1,
                current_uses INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Active',
                UNIQUE(bot_id, code)  -- Ensures code is unique per bot instance
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claimed_gift_codes (
                user_id INTEGER,
                bot_id INTEGER,
                code_id INTEGER,
                PRIMARY KEY(user_id, bot_id, code_id)
            )
        """)
        await db.commit()

async def migrate_database():
    async with aiosqlite.connect("bot_factory.db") as db:
        # Get list of existing columns for child_bot_settings
        async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            
        # Add the column if it's missing
        if "withdraw_tax" not in columns:
            await db.execute("ALTER TABLE child_bot_settings ADD COLUMN withdraw_tax INTEGER DEFAULT 0")
            await db.commit()
            print("Successfully added 'withdraw_tax' column!")


async def fix_gift_code_columns():
    """
    Safely injects the missing bot_id and status structural columns into active 
    database tables to resolve schema constraints on legacy configurations.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Update gift_codes table schema
        async with db.execute("PRAGMA table_info(gift_codes)") as cursor:
            gift_cols = [row[1] for row in await cursor.fetchall()]
        
        if gift_cols:
            if "bot_id" not in gift_cols:
                print("⚙️ Altering 'gift_codes' table to add missing 'bot_id' column...")
                await db.execute("ALTER TABLE gift_codes ADD COLUMN bot_id INTEGER DEFAULT 0")
                await db.commit()
            if "status" not in gift_cols:
                print("⚙️ Altering 'gift_codes' table to add missing 'status' column...")
                await db.execute("ALTER TABLE gift_codes ADD COLUMN status TEXT DEFAULT 'Active'")
                await db.commit()
            if "max_uses" not in gift_cols:
                print("⚙️ Altering 'gift_codes' table to add missing 'max_uses' column...")
                await db.execute("ALTER TABLE gift_codes ADD COLUMN max_uses INTEGER DEFAULT 1")
                await db.commit()
            if "current_uses" not in gift_cols:
                print("⚙️ Altering 'gift_codes' table to add missing 'current_uses' column...")
                await db.execute("ALTER TABLE gift_codes ADD COLUMN current_uses INTEGER DEFAULT 0")
                await db.commit()
            if "req_referrals" not in gift_cols:
                print("⚙️ Altering 'gift_codes' table to add missing 'req_referrals' column...")
                await db.execute("ALTER TABLE gift_codes ADD COLUMN req_referrals INTEGER DEFAULT 0")
                await db.commit()

        # 2. Update claimed_gift_codes table schema
        async with db.execute("PRAGMA table_info(claimed_gift_codes)") as cursor:
            claimed_cols = [row[1] for row in await cursor.fetchall()]
            
        if claimed_cols and "bot_id" not in claimed_cols:
            print("⚙️ Altering 'claimed_gift_codes' table to add missing 'bot_id' column...")
            await db.execute("ALTER TABLE claimed_gift_codes ADD COLUMN bot_id INTEGER DEFAULT 0")
            await db.commit()
    print("✅ Gift code database columns checked and verified successfully.")


async def migrate_gift_code_tables():
    """Wrapper routine ensuring functional backwards compatibility requirements."""
    await fix_gift_code_columns()


# Helper Logic snippet for the Broadcast
async def send_to_user(bot, user_id, content, buttons):
    try:
        await bot.send_message(user_id, content, reply_markup=buttons)
        return True
    except Exception:
        return False # Ignores blocked/deleted users

# -----------------------------------------------------------------
# Broadcast Confirmation Report
# -----------------------------------------------------------------

async def send_broadcast_report(message: types.Message, results: list, start_time: datetime, end_time: datetime):
    total_time = end_time - start_time
    
    # Header
    report = (
        f"<b><tg-emoji emoji-id='5442939099906325301'>📢</tg-emoji> Broadcast Completed Successfully</b>\n\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
    )
    
    # Repeat for every bot processed
    for res in results:
        report += (
            f"<b><tg-emoji emoji-id='5372981976804366741'>🤖</tg-emoji> Bot Name: {res['name']}</b>\n"
            f"<b><tg-emoji emoji-id='6309997365226903510'>🔗</tg-emoji> Username: @{res['username']}</b>\n\n"
            f"<b><tg-emoji emoji-id='5274055917766202507'>🕒</tg-emoji> Started: {start_time.strftime('%I:%M:%S %p')}</b>\n"
            f"<b><tg-emoji emoji-id='5472030678633684592'>🏁</tg-emoji> Finished: {end_time.strftime('%I:%M:%S %p')}</b>\n"
            f"<b><tg-emoji emoji-id='5447644880824181073'>⏱️</tg-emoji> Total Time: {total_time.seconds}s</b>\n\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> Delivered: {res['delivered']}</b>\n"
            f"<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> Failed: {res['failed']}</b>\n\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        )
    
    report += "<b><tg-emoji emoji-id='6300651726844204536'>🚀</tg-emoji> Broadcast has been processed successfully.</b>"
    
    await message.answer(text=report, parse_mode="HTML")

# Helper to retrieve users for a specific bot
async def get_all_users_for_bot(bot_db_id):
    """
    Retrieves all unique user_ids associated with a specific bot from user_balances.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT DISTINCT user_id FROM user_balances WHERE bot_id = ?", (bot_db_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

# High-speed parallel broadcast engine
async def perform_broadcast(data, bot_list):
    start_time = datetime.now()
    results = []
    
    async def send_to_single_bot(bot_record):
        token = bot_record['token']
        bot = Bot(token=token)
        users = await get_all_users_for_bot(bot_record['id']) 
        delivered, failed = 0, 0
        
        async def task(u_id):
            try:
                # Handle Photo, Video, or Text
                if data.get('media_type') == 'photo':
                    await bot.send_photo(u_id, photo=data['media_id'], caption=data['bc_text'])
                elif data.get('media_type') == 'video':
                    await bot.send_video(u_id, video=data['media_id'], caption=data['bc_text'])
                else:
                    await bot.send_message(u_id, data['bc_text'])
                return True
            except:
                return False
                
        sent_results = await asyncio.gather(*[task(u) for u in users])
        return {
            "name": "Rapid Auto Maker Bot ", 
            "username": bot_record['username'], 
            "delivered": sent_results.count(True), 
            "failed": sent_results.count(False),
            "start": start_time.strftime('%I:%M:%S %p'),
            "end": datetime.now().strftime('%I:%M:%S %p')
        }

    broadcast_data = await asyncio.gather(*[send_to_single_bot(b) for b in bot_list])
    return broadcast_data, start_time, datetime.now()

# 1. Define FSM States for this sequence
class CloneBotForm(StatesGroup):
    waiting_for_theme = State()
    waiting_for_token = State()

class ChildBonusSetup(StatesGroup):
    waiting_for_bonus_input = State()

class ChildReferSetup(StatesGroup):
    waiting_for_refer_input = State()

class ChildGatewaySetup(StatesGroup):
    waiting_for_ultrapay_token = State()
    waiting_for_ultrapay_key = State()
    waiting_for_payzy_token = State()
    waiting_for_digipay_token = State()
    waiting_for_bot_fund_amount = State()
    waiting_for_welcome_channel = State()

class ClonedUserWalletSetup(StatesGroup):
    waiting_for_wallet_number = State()

class ChildWithdrawalConfigSetup(StatesGroup):
    waiting_for_min_withdraw = State()
    waiting_for_max_withdraw = State()
    waiting_for_req_refers = State()

class ChildCooldownSetup(StatesGroup):
    waiting_for_cooldown_input = State()

class ClonedUserWithdrawalFlow(StatesGroup):
    waiting_for_withdraw_amount = State()

class ChildAdminBalanceSetup(StatesGroup):
    waiting_for_add_balance_input = State()
    waiting_for_rem_balance_input = State()
    waiting_for_withdraw_off_text = State()
    waiting_for_withdraw_on_text = State()

class TaskPaymentBotForm(StatesGroup):
    waiting_for_theme = State()
    waiting_for_token = State()

class TaxSetup(StatesGroup):
    waiting_for_tax = State()

class GiftCodeSetup(StatesGroup):
    waiting_for_gift_input = State()
    waiting_for_wager_input = State()  # <--- Add this line

class BroadcastForm(StatesGroup):
    waiting_for_media = State()
    waiting_for_message = State()
    waiting_for_buttons = State()
    waiting_for_confirm = State()

class GiftCodeForm(StatesGroup):
    waiting_for_code = State()

class ChildBanSetup(StatesGroup):
    waiting_for_ban_id = State()

class ClonedBotBroadcastFlow(StatesGroup):
    waiting_for_broadcast_content = State()
    waiting_for_broadcast_confirm = State()

class ChildTransferOwnershipSetup(StatesGroup):
    waiting_for_new_owner_id = State()

class ChildUserVerificationSearchSetup(StatesGroup):
    waiting_for_target_user_id = State()

class ChildChannelsDashboardSetup(StatesGroup):
    waiting_for_channel_input = State()

class ChildChannelLinkEditSetup(StatesGroup):
    waiting_for_private_invite_link = State()

async def is_user_member(user_id: int) -> bool:
    for channel_id in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except TelegramBadRequest:
            return False
    return True

def get_join_keyboard():
    builder = InlineKeyboardBuilder()
    
    # Row 1: Join 1 and Join 2 (Primary Style) with Premium Emojis
    builder.add(types.InlineKeyboardButton(
        text="Join ", 
        url="https://t.me/RapidAutoMakerOfficial", 
        style="primary",
        icon_custom_emoji_id="4999015678238262018"  # 1st
    ))
    builder.add(types.InlineKeyboardButton(
        text="Join ", 
        url="https://t.me/aman_officialp", 
        style="primary",
        icon_custom_emoji_id="4999015678238262018"  # 2nd
    ))
    
    # Row 2: ✅Joined Button (Success Style) with Premium Emoji
    builder.add(types.InlineKeyboardButton(
        text="Joined", 
        callback_data="check_membership", 
        style="success",
        icon_custom_emoji_id="6298317205960397843"  # 3rd
    ))
    
    # Keeps your 1 2 / 3 alignment layout intact
    builder.adjust(2, 1)
    return builder.as_markup()

    # Reply Keyboard designed specifically for the Task Payment Bot workspace matrix

def get_task_bot_main_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    
    # Row 1: Balance & Link UPI (Primary/Blue Style)
    builder.add(types.KeyboardButton(
        text="Balance", 
        style="primary", 
        icon_custom_emoji_id="5375296873982604963"
    ))
    builder.add(types.KeyboardButton(
        text="Link UPI", 
        style="primary", 
        icon_custom_emoji_id="5472030678633684592"
    ))
    
    # Row 2: Withdraw (Danger/Red Style)
    builder.add(types.KeyboardButton(
        text="Withdraw", 
        style="danger", 
        icon_custom_emoji_id="5264895611517300926"
    ))
    
    # Row 3: Bal. History & Withdraw History (Success/Green Style)
    builder.add(types.KeyboardButton(
        text="Bal. History", 
        style="success", 
        icon_custom_emoji_id="5274055917766202507"
    ))
    builder.add(types.KeyboardButton(
        text="Withdraw History", 
        style="success", 
        icon_custom_emoji_id="6068996425146965808"
    ))
    
    # Grid structure mapping layout constraints cleanly
    builder.adjust(2, 1, 2)
    return builder.as_markup(resize_keyboard=True)


def get_main_menu_reply_keyboard():
    builder = ReplyKeyboardBuilder()
    
    # Row 1: Primary Style (Blue)
    builder.add(types.KeyboardButton(
        text=" Cʀᴇᴀᴛᴇ Bᴏᴛ", 
        style="primary",
        icon_custom_emoji_id="6300651726844204536"  # 1st
    ))
    builder.add(types.KeyboardButton(
        text=" Mʏ Bᴏᴛs", 
        style="primary",
        icon_custom_emoji_id="5372981976804366741"  # 2nd
    ))
    
    # Row 2: Success Style (Green)
    builder.add(types.KeyboardButton(
        text="Bʀᴏᴀᴅᴄᴀsᴛ Hᴜʙ", 
        style="success",
        icon_custom_emoji_id="6068806600477383919"  # 3rd
    ))
    builder.add(types.KeyboardButton(
        text="Sᴛᴀᴛɪsᴛɪᴄs", 
        style="success",
        icon_custom_emoji_id="6300797828746711280"  # 4th
    ))
    
    # Row 3: Danger Style (Red)
    builder.add(types.KeyboardButton(
        text="Pᴜʀᴄʜᴀsᴇ Pᴏɪɴᴛs", 
        style="danger",
        icon_custom_emoji_id="5375296873982604963"  # 5th
    ))
    builder.add(types.KeyboardButton(
        text="Cᴏɴᴛᴀᴄᴛ Sᴜᴘᴘᴏʀᴛ", 
        style="danger",
        icon_custom_emoji_id="5465300082628763143"  # 6th
    ))
    
    # Maintains your exact 2x3 matrix layout
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_bot_type_keyboard():
    builder = ReplyKeyboardBuilder()
    
    # Row 1: Wallet Bot & UPI Bot (Primary Style)
    builder.add(types.KeyboardButton(
        text="Wallet Bot", style="primary",
        icon_custom_emoji_id="5472363448404809929"
    ))
    builder.add(types.KeyboardButton(
        text="UPI Bot", style="primary",
        icon_custom_emoji_id="6300651726844204536"
    ))
    
    # Row 2: Smart Advanced Bot (Success Style)
    builder.add(types.KeyboardButton(
        text="Smart Advanced Bot", style="success",
        icon_custom_emoji_id="6172745002314118594"
    ))
    
    # Row 3: Redeem Code Bot & Stars Bot (Primary Style)
    builder.add(types.KeyboardButton(
        text="Redeem Code Bot", style="primary",
        icon_custom_emoji_id="6068806600477383919"
    ))
    builder.add(types.KeyboardButton(
        text="Stars Bot", style="primary",
        icon_custom_emoji_id="5064709487953183440"
    ))
    
    # Row 4: Manual Bot (Success Style)
    builder.add(types.KeyboardButton(
        text="Manual Bot", style="success",
        icon_custom_emoji_id="6267008582294705964"
    ))
    
    # Row 5: Premium Bot & Task Payment Bot (Primary Style)
    builder.add(types.KeyboardButton(
        text="Premium Bot", style="primary",
        icon_custom_emoji_id="6118333272821865260"
    ))
    builder.add(types.KeyboardButton(
        text="Task Payment Bot", style="primary",
        icon_custom_emoji_id="4996755833950831347"
    ))
    
    # Row 6: Back Button (Danger Style - Red) with Premium Emoji Icon
    builder.add(types.KeyboardButton(
        text="Back To Main Panel", style="danger",
        icon_custom_emoji_id="6309851100115640076"
    ))
    
    # Pattern updated to include the single back button at the end: 2, 1, 2, 1, 2, 1
    builder.adjust(2, 1, 2, 1, 2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_wallet_bot_options_keyboard():
    builder = ReplyKeyboardBuilder()
    
    # Button 1: Normal Wallet Bot (No custom style applied)
    builder.add(types.KeyboardButton(
        text="Normal Wallet Bot", 
        icon_custom_emoji_id="6267008582294705964"
    ))
    
    # Button 2: Premium Wallet Bot (Primary Style)
    builder.add(types.KeyboardButton(
        text="Premium Wallet Bot", 
        style="primary",
        icon_custom_emoji_id="6118333272821865260"
    ))
    
    # Button 3: Back Button (Danger Style so it matches the other back button look)
    builder.add(types.KeyboardButton(
        text="Back To Main Panel", 
        style="danger",
        icon_custom_emoji_id="6309851100115640076"
    ))
    
    # Stacks the options and back button vertically: 1 button per row
    builder.adjust(1, 1, 1)
    return builder.as_markup(resize_keyboard=True)

# 2. Keyboard Generator for Theme Selection
def get_theme_selection_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Select Theme", 
        callback_data="select_premium_theme", 
        style="primary",
        icon_custom_emoji_id="6267008582294705964"
    ))
    return builder.as_markup()



# FIX: Added 'bot_username: str' argument parameter 
async def get_clone_verification_keyboard(bot_username: str):
    builder = InlineKeyboardBuilder()
    # Cleans the username to pass cleanly as a parameter string
    clean_username = bot_username.replace("@", "")
    
    builder.add(types.InlineKeyboardButton(
        text="Verify",
        web_app=types.WebAppInfo(url=f"https://newdevice.vercel.app/?bot={clean_username}"),
        style="primary",
        icon_custom_emoji_id="6267008582294705964"
    ))
    return builder.as_markup()


# Reply Keyboard for Cloned Bot Main Menu Workspace with Colored Button Styles
def get_clone_main_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    
    # Row 1: Balance & Refer Earn (Primary/Blue Style)
    builder.add(types.KeyboardButton(
        text="Balance", 
        style="primary", 
        icon_custom_emoji_id="5375296873982604963"
    ))
    builder.add(types.KeyboardButton(
        text="Refer Earn", 
        style="primary", 
        icon_custom_emoji_id="5375152498656961898"
    ))
    
    # Row 2: Rewards (Success/Green Style)
    builder.add(types.KeyboardButton(
        text="Rewards", 
        style="success", 
        icon_custom_emoji_id="6291702140280771095"
    ))
    
    # Row 3: Set Wallet & Withdraw (Primary/Blue & Danger/Red Styles)
    builder.add(types.KeyboardButton(
        text="Set Wallet", 
        style="primary", 
        icon_custom_emoji_id="5472030678633684592"
    ))
    builder.add(types.KeyboardButton(
        text="Withdraw", 
        style="danger", 
        icon_custom_emoji_id="5264895611517300926"
    ))
    
    # Layout adjustments matching: 2, 1, 2 grid format matrix
    builder.adjust(2, 1, 2)
    return builder.as_markup(resize_keyboard=True)



# Fixed function using aiogram utilities to safely structure the premium emojis
async def send_welcome_message(message: types.Message, reply_markup):
    content = Text(
        CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
        " ",
        Bold("Welcome To Rapid Auto Maker Bot, Launched Officially By 𝐀𝐌𝐀𝐍 𝐒𝐀𝐈𝐍𝐈 !!"),
        " ",
        CustomEmoji("🎉", custom_emoji_id="4996755833950831347")
    )
    # **content.as_kwargs() cleanly generates safe raw text and perfect entity maps
    return await message.answer(**content.as_kwargs(), reply_markup=reply_markup)

# Helper function to format and send the unverified join prompt with premium emojis
async def send_join_message(message: types.Message, reply_markup):
    content = Text(
        Bold(
            CustomEmoji("👋", custom_emoji_id="4999015678238262018"),
            f" Hey {message.from_user.first_name}, Welcome To Bot !!!\n\n",
            CustomEmoji("💈", custom_emoji_id="6172745002314118594"),
            " After Joining All Channels, Tap On the Joined Button !!!"
        )
    )
    return await message.answer(**content.as_kwargs(), reply_markup=reply_markup)

# =====================================================================
# 1. MAIN (MASTER) BOT CONTEXT
# =====================================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # 1. Register the user in the database immediately upon start
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_verification (user_id, bot_id, seen) 
            VALUES (?, 0, 0)
        """, (user_id,))
        await db.commit()
    
    # 2. Check membership status
    user_joined = await is_user_member(user_id)
    
    if not user_joined:
        await send_join_message(message, get_join_keyboard())
    else:
        await send_welcome_message(message, get_main_menu_reply_keyboard())




# =====================================================================
# 2. CLONED BOT WORKER CONTEXT (Prevents NameError: cloned_dp)
# =====================================================================
# Helper to render the Verified / Normal welcome menu profile panel text layout cleanly
async def send_clone_normal_welcome(message: types.Message):
    target_url = "https://t.me/RapidAutoMakerOfficial" # Default fallback pointer link
    raw_telegram_bot_id = message.bot.id

    # Dynamic lookup retrieval targeting the configured context channel configurations using db_bot_id mapped from active bot.id
    async with aiosqlite.connect("bot_factory.db") as db:
        # --- FIXED: Robust fallback matching checks bot_id first, then falls back to bot_token if bot_id is unset/None ---
        async with db.execute(
            "SELECT id FROM cloned_bots WHERE bot_id = ? OR bot_token = ?", 
            (str(raw_telegram_bot_id), getattr(message.bot, 'token', ''))
        ) as lookup_cursor:
            bot_row = await lookup_cursor.fetchone()
        
        # If the outer loop variable 'db_bot_id' is accessible in this scope, use it as the final fallback option
        active_db_bot_id = bot_row[0] if bot_row else (db_bot_id if 'db_bot_id' in globals() else None)
        
        if active_db_bot_id:
            async with db.execute(
                "SELECT welcome_channel_link FROM child_bot_settings WHERE bot_id = ?", 
                (active_db_bot_id,)
            ) as cursor:
                row = await cursor.fetchone()
        else:
            row = None
            
    # Strictly use the link already created and saved from the set welcome inline button configuration
    if row and row[0] and row[0] != "None" and "t.me" in str(row[0]):
        target_url = row[0]

    content = Text(
        CustomEmoji("💫", custom_emoji_id="5469741319330996757"), 
        Bold(" Welcome To Cash Giveaway Bot! "), 
        CustomEmoji("💫", custom_emoji_id="5469741319330996757"), 
        "\n\n",
        CustomEmoji("🎉", custom_emoji_id="4996755833950831347"), 
        Bold(" Earn Free Cash By Inviting Friends And Earning Rewards.\n\n"),
        CustomEmoji("✅", custom_emoji_id="6267008582294705964"), 
        Bold(" To Learn How To Earn ➠ "), 
        TextLink("Click Here", url=target_url), 
        "\n\n",
        CustomEmoji("🚀", custom_emoji_id="6300651726844204536"), 
        Bold(" Start Your Earning Journey Today!")
    )
    
    # Pack up the native payload dictionary and apply page preview suppression flags safely
    response_kwargs = content.as_kwargs()
    response_kwargs["reply_markup"] = get_clone_main_menu_keyboard()
    response_kwargs["link_preview_options"] = types.LinkPreviewOptions(is_disabled=True)
    
    return await message.answer(**response_kwargs)

async def start_cloned_bot_worker(token: str, db_bot_id: int):
    # --- PRE-FLIGHT: FORCE DATABASE CREATION ---
    # We ensure all required tables exist before any bot logic or queries execute
    async with aiosqlite.connect("bot_factory.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER, 
                bot_id INTEGER,
                balance REAL DEFAULT 0.0,
                PRIMARY KEY(user_id, bot_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_bonus_cooldowns (
                user_id INTEGER,
                bot_id INTEGER,
                last_claim_time TEXT,
                PRIMARY KEY(user_id, bot_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS child_bot_settings (
                bot_id INTEGER PRIMARY KEY,
                status_state TEXT DEFAULT 'Active',
                device_verification TEXT DEFAULT 'On',
                payout_mode TEXT DEFAULT 'AUTO',
                min_withdraw REAL DEFAULT 100.0,
                max_withdraw REAL DEFAULT 10000.0,
                req_referrals INTEGER DEFAULT 3,
                cooldown TEXT DEFAULT 'off',
                bonus_amount TEXT DEFAULT 'Tell Me',
                bonus_mode TEXT DEFAULT '',
                refer_amount TEXT DEFAULT 'Tell Me',
                refer_mode TEXT DEFAULT ''
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id INTEGER,
                bot_id INTEGER,
                seen INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, bot_id)
            )
        """)
        await db.commit()

    # -------------------------------------------

    try:
        from aiogram.client.default import DefaultBotProperties
        cloned_bot = Bot(token=token, properties=DefaultBotProperties(parse_mode="HTML"))
        cloned_dp = Dispatcher()
       
        
        # -----------------------------------------------------------------
        # Cloned Bot Rewards Button Handler (Stacked Vertical Layout)
        # -----------------------------------------------------------------
        @cloned_dp.message(F.text == "Rewards")
        async def handle_cloned_rewards(message: types.Message):
            # Fetch the dynamic operating status context from the configuration database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        payout_mode TEXT DEFAULT 'AUTO'
                    )
                """)
                await db.commit()

                async with db.execute("SELECT status_state FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    settings_row = await cursor.fetchone()
            
            current_state = settings_row[0] if settings_row and settings_row[0] else "Active"

            # --- STATUS CHECK INTERCEPTION MATRIX ---
            if current_state == "Maintenance":
                maintenance_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Under Maintenance!</b>'
                )
                await message.answer(text=maintenance_text, parse_mode="HTML")
                return

            if current_state in ["Disable", "disabled"]:
                disabled_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Off!</b>'
                )
                await message.answer(text=disabled_text, parse_mode="HTML")
                return

            # --- STANDARD FLOW EXECUTION ---
            inline_builder = InlineKeyboardBuilder()
            
            # 1st Button: Bonus (Primary)
            inline_builder.add(types.InlineKeyboardButton(
                text="Bonus",
                callback_data="claim_bonus",
                style="primary",
                icon_custom_emoji_id="4996755833950831347"
            ))
            
            # 2nd Button: Gift Code (Success)
            inline_builder.add(types.InlineKeyboardButton(
                text="Gift Code",
                callback_data="claim_gift_code",
                style="success",
                icon_custom_emoji_id="6291702140280771095"
            ))
            
            inline_builder.adjust(1)

            rewards_prompt = Text(
                CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
                Bold("Choose One:")
            )
            
            await message.answer(**rewards_prompt.as_kwargs(), reply_markup=inline_builder.as_markup())

        # -----------------------------------------------------------------
        # Cloned Bot Balance Button Handler (Isolated Workspace Ledger)
        # -----------------------------------------------------------------
        @cloned_dp.message(F.text == "Balance")
        async def handle_cloned_balance(message: types.Message):
            # Fetch the dynamic operating status context from the configuration database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        payout_mode TEXT DEFAULT 'AUTO'
                    )
                """)
                await db.commit()

                async with db.execute("SELECT status_state FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    settings_row = await cursor.fetchone()
            
            current_state = settings_row[0] if settings_row and settings_row[0] else "Active"

            # --- STATUS CHECK INTERCEPTION MATRIX ---
            if current_state == "Maintenance":
                maintenance_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Under Maintenance!</b>'
                )
                await message.answer(text=maintenance_text, parse_mode="HTML")
                return

            if current_state in ["Disable", "disabled"]:
                disabled_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Off!</b>'
                )
                await message.answer(text=disabled_text, parse_mode="HTML")
                return

            # --- STANDARD FLOW EXECUTION ---
            user_id = message.from_user.id
            # Extract raw Telegram API unique identifier matching the validation engine
            bot_id = message.bot.id
            
            async with aiosqlite.connect("bot_factory.db") as db:
                # Force dynamic structure isolation using independent execution scripts
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER, 
                        bot_id INTEGER,
                        balance REAL DEFAULT 0.0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()
                
                # Isolated balance search context cleanly tied to the active bot deployment
                async with db.execute(
                    "SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", 
                    (user_id, bot_id)
                ) as cursor:
                    row = await cursor.fetchone()
            
            current_balance = row[0] if row is not None else 0.00
            
            balance_panel_content = Text(
                CustomEmoji("💰", custom_emoji_id="5375296873982604963"), 
                Bold(f" Balance: ₹{current_balance:.2f}\n\n"),
                CustomEmoji("🎉", custom_emoji_id="4996755833950831347"), 
                Bold(" Use 'Withdraw' Button to Withdraw The Balance!")
            )
            
            await message.answer(**balance_panel_content.as_kwargs())


        # -----------------------------------------------------------------
        # Cloned Bot Refer & Earn Button Handler (With Dynamic Upto Mode)
        # -----------------------------------------------------------------
        @cloned_dp.message(F.text == "Refer Earn")
        async def handle_cloned_refer_earn(message: types.Message):
            # Fetch the dynamic operating status context from the configuration database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        payout_mode TEXT DEFAULT 'AUTO'
                    )
                """)
                await db.commit()

                async with db.execute("SELECT status_state FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    settings_row = await cursor.fetchone()
            
            current_state = settings_row[0] if settings_row and settings_row[0] else "Active"

            # --- STATUS CHECK INTERCEPTION MATRIX ---
            if current_state == "Maintenance":
                maintenance_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Under Maintenance!</b>'
                )
                await message.answer(text=maintenance_text, parse_mode="HTML")
                return

            if current_state in ["Disable", "disabled"]:
                disabled_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Off!</b>'
                )
                await message.answer(text=disabled_text, parse_mode="HTML")
                return

            # --- STANDARD FLOW EXECUTION ---
            user_id = message.from_user.id
            me = await message.bot.get_me()
            
            async with aiosqlite.connect("bot_factory.db") as db:
                # Ensure the referrals logging table handles independent scopes safely
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_referrals (
                        referrer_id INTEGER,
                        referred_id INTEGER,
                        bot_id INTEGER,
                        PRIMARY KEY(referred_id, bot_id)
                    )
                """)
                await db.commit()

                async with db.execute(
                    "SELECT refer_amount, refer_mode FROM child_bot_settings WHERE bot_id = ?", 
                    (db_bot_id,)
                ) as cursor:
                    row = await cursor.fetchone()
            
            refer_reward = row[0] if row and row[0] not in ["健全 Nᴏᴛ Sᴇᴛ", "Tell Me", "❎ Nᴏᴛ Sᴇᴛ"] else "1"
            refer_mode = row[1] if row else "Normal (Fixed Amount)"

            if "Random" in refer_mode and "-" in refer_reward:
                try:
                    max_amount = refer_reward.split("-")[1].strip()
                    reward_text = f"Earn Upto ₹{max_amount}"
                except Exception:
                    reward_text = f"Earn ₹{refer_reward}"
            else:
                reward_text = f"Earn ₹{refer_reward}"

            refer_panel_text = (
                f'<tg-emoji emoji-id="5472030678633684592">💸</tg-emoji> <b>{reward_text} Cash On Every Referral!</b>\n\n'
                f'<tg-emoji emoji-id="6309997365226903510">🔗</tg-emoji> <b>Your Referral Link:</b>\n'
                f'https://t.me/{me.username}?start={user_id}\n\n'
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji> <b>Invite Your Friends & Family Using Your Unique Link And {reward_text} For Every Successful Referral.</b>'
            )

            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text="My Invites",
                callback_data="cloned_my_invites",
                style="primary",
                icon_custom_emoji_id="4999015678238262018"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Leaderboard",
                callback_data="cloned_leaderboard",
                style="success",
                icon_custom_emoji_id="6118333272821865260"
            ))
            builder.adjust(2)

            await message.answer(text=refer_panel_text, parse_mode="HTML", reply_markup=builder.as_markup())

        # -----------------------------------------------------------------
        # Cloned Bot User Wallet Linking Engine (Dynamic Active Gateway)
        # -----------------------------------------------------------------
        
        # 1. Capture the "Set Wallet" text message sent by a user
        @cloned_dp.message(F.text == "Set Wallet", StateFilter(None))
        async def handle_set_wallet_request(message: types.Message, state: FSMContext):
            # Fetch the dynamic operating status context from the configuration database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        payout_mode TEXT DEFAULT 'AUTO'
                    )
                """)
                await db.commit()

                async with db.execute("SELECT status_state FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    settings_row = await cursor.fetchone()
            
            current_state = settings_row[0] if settings_row and settings_row[0] else "Active"

            # --- STATUS CHECK INTERCEPTION MATRIX ---
            if current_state == "Maintenance":
                maintenance_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Under Maintenance!</b>'
                )
                await message.answer(text=maintenance_text, parse_mode="HTML")
                return

            if current_state in ["Disable", "disabled"]:
                disabled_text = (
                    f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                    f'<b>The Bot Is Currently Off!</b>'
                )
                await message.answer(text=disabled_text, parse_mode="HTML")
                return

            # --- STANDARD FLOW EXECUTION ---
            async with aiosqlite.connect("bot_factory.db") as db:
                # Ensure the table layout matrix structures exist natively first including PayZy and Digi Pay columns
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_gateways (
                        bot_id INTEGER PRIMARY KEY,
                        techpay_status TEXT DEFAULT 'Disabled',
                        payzy_status TEXT DEFAULT 'Disabled',
                        digipay_status TEXT DEFAULT 'Disabled',
                        techpay_token TEXT DEFAULT 'None',
                        payzy_token TEXT DEFAULT 'None',
                        digipay_token TEXT DEFAULT 'None',
                        ultrapay_token TEXT DEFAULT 'None',
                        ultrapay_key TEXT DEFAULT 'None',
                        ultrapay_base_url TEXT DEFAULT 'https://ultra-pay.store/APIs/api',
                        payzy_base_url TEXT DEFAULT 'https://payzy-gateway.site/api/transfer',
                        digipay_base_url TEXT DEFAULT 'https://Digi-pay-wallet.vercel.app/api'
                    )
                """)
                await db.commit()

                # Hot patch dynamically adding missing Digi Pay structure elements inside active structures if missing
                async with db.execute("PRAGMA table_info(child_gateways)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                if "digipay_status" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_status TEXT DEFAULT 'Disabled'")
                if "digipay_token" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_token TEXT DEFAULT 'None'")
                if "digipay_base_url" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_base_url TEXT DEFAULT 'https://Digi-pay-wallet.vercel.app/api'")
                await db.commit()
                
                # Fetch row data matrix profile across all gateway platforms
                async with db.execute("""
                    SELECT techpay_status, payzy_status, digipay_status, ultrapay_base_url, payzy_base_url, digipay_base_url 
                    FROM child_gateways WHERE bot_id = ?
                """, (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            # If the admin hasn't opened the gateway dashboard panel yet, initialize the data row safely
            if not row:
                async with aiosqlite.connect("bot_factory.db") as db:
                    await db.execute("""
                        INSERT OR IGNORE INTO child_gateways (bot_id, techpay_status, ultrapay_base_url, payzy_base_url, digipay_base_url) 
                        VALUES (?, 'Enabled', 'https://ultra-pay.store/APIs/api', 'https://payzy-gateway.site/api/transfer', 'https://Digi-pay-wallet.vercel.app/api')
                    """, (db_bot_id,))
                    await db.commit()
                status_up, status_pz, status_dg, up_url, pz_url, dg_url = "Enabled", "Disabled", "Disabled", "https://ultra-pay.store/APIs/api", "https://payzy-gateway.site/api/transfer", "https://Digi-pay-wallet.vercel.app/api"
            else:
                status_up, status_pz, status_dg, up_url, pz_url, dg_url = row

            active_gateway = "None"
            base_url = "None"

            # Map statuses out into our current active profile variables cleanly using order priority
            if status_up == "Enabled":
                active_gateway = "UltraPay"
                base_url = up_url if up_url and up_url != "None" else "https://ultra-pay.store/APIs/api"
            elif status_pz == "Enabled":
                active_gateway = "PayZy"
                base_url = pz_url if pz_url and pz_url != "None" else "https://payzy-gateway.site/api/transfer"
            elif status_dg == "Enabled":
                active_gateway = "Digi Pay"
                base_url = dg_url if dg_url and dg_url != "None" else "https://Digi-pay-wallet.vercel.app/api"

            # Safety fallback closure check if admin explicitly turned off/disabled all systems
            if active_gateway == "None":
                await message.answer("❌ <b>Payout gateway systems are currently undergoing maintenance. Please try again later.</b>", parse_mode="HTML")
                return

            # DYNAMIC EXTRACTION ENGINE: Extract the pure root domain link out of the active base URL configuration
            if "://" in base_url:
                protocol, sep, remainder = base_url.partition("://")
                domain = remainder.split("/")[0]
                chosen_link = f"{protocol}{sep}{domain}/"
            else:
                if active_gateway == "UltraPay":
                    chosen_link = "https://ultra-pay.store/"
                elif active_gateway == "PayZy":
                    chosen_link = "https://payzy-gateway.site/"
                else:
                    chosen_link = "https://Digi-pay-wallet.vercel.app/"

            # Construct the setup text block matching your specific premium emoji tokens
            ask_wallet_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Send Your {active_gateway} Wallet Number!</b>\n\n'
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji><b>Wallet Link » {chosen_link}</b>\n\n'
                f'<tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji><b> Type </b><code>Cancel</code><b> To Abort</b>'
            )
            
            await state.update_data(gateway_type=active_gateway)
            await state.set_state(ClonedUserWalletSetup.waiting_for_wallet_number)
            await message.answer(text=ask_wallet_text, parse_mode="HTML")

        # 2. Process incoming wallet payload entries or handle direct cancel requests
        @cloned_dp.message(ClonedUserWalletSetup.waiting_for_wallet_number)
        async def process_user_wallet_number_input(message: types.Message, state: FSMContext):
            user_input = message.text.strip() if message.text else ""
            raw_bot_token_id = message.bot.id  # The raw unique 10-digit Telegram Token ID
            
            if user_input.lower() == 'cancel':
                await message.answer("<b>Configuration aborted successfully.</b>", parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
                await state.clear()
                return

            if not user_input.isdigit() or len(user_input) != 10:
                await message.answer(
                    "❌ <b>Invalid Wallet Number! Please provide a valid 10-digit number or type </b><code>Cancel</code><b> to abort.</b>", 
                    parse_mode="HTML"
                )
                return

            fsm_data = await state.get_data()
            gateway_used = fsm_data.get("gateway_type", "UltraPay")
            user_id = message.from_user.id

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_linked_wallets (
                        user_id INTEGER,
                        bot_id INTEGER,
                        wallet_number TEXT,
                        gateway_name TEXT,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()
                
                # --- FIXED: Use raw_bot_token_id string here to seamlessly match your withdrawal lookups ---
                await db.execute("""
                    INSERT OR REPLACE INTO user_linked_wallets (user_id, bot_id, wallet_number, gateway_name)
                    VALUES (?, ?, ?, ?)
                """, (user_id, raw_bot_token_id, user_input, gateway_used))
                await db.commit()

            confirmation_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>{gateway_used} Wallet Linked To: <code>{user_input}</code></b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji><b>Use <code>Withdraw</code> To Withdraw Your Balance!</b>'
            )
            
            await message.answer(text=confirmation_text, parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Bot Core Withdrawal Engine (Live Gateway Integration)
        # -----------------------------------------------------------------

        # 1. Capture the "Withdraw" action trigger text
        @cloned_dp.message(F.text == "Withdraw", StateFilter(None))
        async def handle_user_withdraw_request(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            raw_bot_token_id = message.bot.id  # The raw unique 10-digit Telegram Token ID

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        payout_mode TEXT DEFAULT 'AUTO',
                        min_withdraw REAL DEFAULT 100.0,
                        max_withdraw REAL DEFAULT 10000.0,
                        req_referrals INTEGER DEFAULT 3,
                        cooldown TEXT DEFAULT 'off'
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_linked_wallets (
                        user_id INTEGER,
                        bot_id INTEGER,
                        wallet_number TEXT,
                        gateway_name TEXT,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # Fetch settings using your original direct db_bot_id variable mapping
                async with db.execute("SELECT status_state, payout_mode, min_withdraw FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    settings_row = await cursor.fetchone()
                
                if settings_row:
                    current_state = settings_row[0] if settings_row[0] else "Active"
                    payout_mode = settings_row[1] if settings_row[1] else "AUTO"
                    min_required = settings_row[2] if settings_row[2] is not None else 100.0
                else:
                    current_state = "Active"
                    payout_mode = "AUTO"
                    min_required = 100.0

                # --- STATUS CHECK INTERCEPTION MATRIX ---
                if current_state == "Maintenance":
                    maintenance_text = (
                        f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                        f'<b>The Bot Is Currently Under Maintenance!</b>'
                    )
                    await message.answer(text=maintenance_text, parse_mode="HTML")
                    return

                if current_state in ["Disable", "disabled"]:
                    disabled_text = (
                        f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                        f'<b>The Bot Is Currently Off!</b>'
                    )
                    await message.answer(text=disabled_text, parse_mode="HTML")
                    return

                # Ensure custom texts table exists natively
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_texts (
                        bot_id INTEGER PRIMARY KEY,
                        withdraw_off_text TEXT,
                        withdraw_text TEXT
                    )
                """)
                await db.commit()

                async with db.execute("SELECT withdraw_off_text FROM child_bot_texts WHERE bot_id = ?", (db_bot_id,)) as text_cursor:
                    custom_text_row = await text_cursor.fetchone()
                custom_off_text = custom_text_row[0] if custom_text_row else None

                # --- GUARD: Enforce Payouts Off Interception Matrix ---
                if payout_mode == "OFF":
                    if custom_off_text and custom_off_text != "None":
                        await message.answer(text=custom_off_text, parse_mode="HTML")
                    else:
                        fallback_off = (
                            f'<tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji> '
                            f'<b>Withdrawal Is Currently Unavailable!</b>'
                        )
                        await message.answer(text=fallback_off, parse_mode="HTML")
                    return

                # B. Fetch active gateway profiles using your original db_bot_id mapping
                async with db.execute("""
                    SELECT techpay_status, payzy_status, ultrapay_base_url, payzy_base_url 
                    FROM child_gateways WHERE bot_id = ?
                """, (db_bot_id,)) as cursor:
                    g_row = await cursor.fetchone()

                # C. Check linked wallets mapping using raw 10-digit ID format consistently
                async with db.execute("""
                    SELECT wallet_number, gateway_name FROM user_linked_wallets 
                    WHERE user_id = ? AND bot_id = ?
                """, (user_id, raw_bot_token_id)) as cursor:
                    wallet_row = await cursor.fetchone()

                # D. --- FIXED: Check balance using raw_bot_token_id to match the balance handler precisely ---
                async with db.execute("""
                    SELECT balance FROM user_balances 
                    WHERE user_id = ? AND bot_id = ?
                """, (user_id, raw_bot_token_id)) as cursor:
                    bal_row = await cursor.fetchone()
                user_balance = bal_row[0] if bal_row else 0.0

            if not wallet_row:
                no_wallet_text = (
                    f'<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
                    f'<b>You Must Have To <code>Set Wallet</code> To Make Withdraw</b>'
                )
                await message.answer(text=no_wallet_text, parse_mode="HTML")
                return

            if user_balance < min_required:
                refusal_text = (
                    f'<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
                    f'<b>You Must Own Atleast ₹{min_required:.2f} Balance To Make Withdraw!</b>'
                )
                await message.answer(text=refusal_text, parse_mode="HTML")
                return

            status_up, status_pz, up_url, pz_url = g_row if g_row else ("Enabled", "Disabled", "https://ultra-pay.store/APIs/api", "https://payzy-gateway.site/api/transfer")
            base_url = pz_url if status_pz == "Enabled" else up_url
            
            if "://" in base_url:
                protocol, sep, remainder = base_url.partition("://")
                domain = remainder.split("/")[0]
                chosen_link = f"{protocol}{sep}{domain}/"
            else:
                chosen_link = "https://ultra-pay.store/" if status_up == "Enabled" else "https://payzy-gateway.site/"

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Provide Amount To Make Withdraw!</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji><b>Wallet: {chosen_link}</b>\n\n'
                f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <i>Type <code>Cancel</code> to exit</i>'
            )
            
            await state.update_data(
                current_bal=user_balance, 
                min_lim=min_required, 
                gw_name=wallet_row[1],
                wallet_num=wallet_row[0]
            )
            await state.set_state(ClonedUserWithdrawalFlow.waiting_for_withdraw_amount)
            await message.answer(text=ask_text, parse_mode="HTML")

        # 2. Process cash volume amount input values and run live payouts
        @cloned_dp.message(ClonedUserWithdrawalFlow.waiting_for_withdraw_amount)
        async def process_user_withdraw_amount(message: types.Message, state: FSMContext):
            import aiohttp
            user_input = message.text.strip() if message.text else ""
            user_id = message.from_user.id
            raw_bot_token_id = message.bot.id
            
            if user_input.lower() == 'cancel':
                await message.answer("<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> Withdrawal sequence canceled.</b>", parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
                await state.clear()
                return

            try:
                requested_amount = float(user_input)
                if requested_amount <= 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Please send a valid numeric positive amount.</b>", parse_mode="HTML")
                return

            fsm_data = await state.get_data()
            user_balance = fsm_data.get("current_bal", 0.0)
            min_required = fsm_data.get("min_lim", 100.0)
            gateway_used = fsm_data.get("gw_name", "UltraPay")
            destination_wallet = fsm_data.get("wallet_num")

            if requested_amount > user_balance:
                await message.answer(f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>Insufficient Balance! You can only withdraw up to ₹{user_balance:.2f}.</b>", parse_mode="HTML")
                return
            if requested_amount < min_required:
                await message.answer(f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>Amount is lower than the required minimum threshold of ₹{min_required:.2f}.</b>", parse_mode="HTML")
                return

            progress_msg = await message.answer("<b>Processing Your Request....</b>", parse_mode="HTML")

            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT ultrapay_token, ultrapay_key, payzy_token, digipay_token FROM child_gateways WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    tokens_row = await cursor.fetchone()

            up_token, up_key, pz_token, dp_token = tokens_row if tokens_row else ("None", "None", "None", "None")

            if gateway_used == "DigiPay":
                api_url = f"https://digi-pay-wallet.vercel.app/api?key={dp_token}&paytm={destination_wallet}&amount={requested_amount}"
            elif gateway_used == "PayZy":
                api_url = f"https://payzy-gateway.site/api/transfer/token={pz_token}&number={destination_wallet}&amount={requested_amount}"
            else:
                api_url = f"https://ultra-pay.store/APIs/api?token={up_token}&key={up_key}&paytoNumber={destination_wallet}&amount={requested_amount}&comment=%E2%9C%A8Payment"

            payment_successful = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(api_url, timeout=30) as response:
                        resp_text = await response.text()
                        if response.status == 200 and ("success" in resp_text.lower() or "processed" in resp_text.lower()):
                            payment_successful = True
            except Exception:
                payment_successful = False

            if payment_successful:
                async with aiosqlite.connect("bot_factory.db") as db:
                    await db.execute("UPDATE user_balances SET balance = balance - ? WHERE user_id = ? AND bot_id = ?", (requested_amount, user_id, raw_bot_token_id))
                    await db.execute("UPDATE child_bot_settings SET bot_funds = bot_funds - ? WHERE bot_id = ?", (requested_amount, db_bot_id))
                    await db.commit()

                    async with db.execute("SELECT withdraw_text FROM child_bot_texts WHERE bot_id = ?", (db_bot_id,)) as text_cursor:
                        success_row = await text_cursor.fetchone()
                    custom_on_text = success_row[0] if success_row else None

                try: await progress_msg.delete()
                except: pass

                success_text = custom_on_text if custom_on_text and custom_on_text != "None" else (
                    f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Your Withdraw Have Been Processed Successfully!</b>\n\n'
                    f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji><b>Kindly Check Your {gateway_used} Wallet Account!</b>'
                )
                await message.answer(text=success_text, parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
                await state.clear()
            else:
                try: await progress_msg.delete()
                except: pass
                await message.answer(text='<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> <b>Withdrawal Failed!!</b>\n\n<tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> <b>We Are Unable To Process Your Payment Due To Some Errors.</b>', parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
                await state.clear()

    except Exception as e:
        print(f"Error executing handler worker subsystem context loops: {e}")


    # =================================================================
    # Cloned Child Bot Dynamic /adminpanel Context Setup
    # =================================================================
    # Helper function inside the worker to fetch this specific bot's current admin settings layout
    async def get_child_admin_panel_content(db_bot_id: int, user_id: int, first_name: str):
        async with aiosqlite.connect("bot_factory.db") as db:
            # 1. Ensure core tracking columns exist, including withdraw_tax
            await db.execute("""
                CREATE TABLE IF NOT EXISTS child_bot_settings (
                    bot_id INTEGER PRIMARY KEY,
                    status_state TEXT DEFAULT 'Active',
                    device_verification TEXT DEFAULT 'On',
                    payout_mode TEXT DEFAULT 'AUTO',
                    min_withdraw REAL DEFAULT 100.0,
                    max_withdraw REAL DEFAULT 10000.0,
                    withdraw_tax INTEGER DEFAULT 0,
                    req_referrals INTEGER DEFAULT 3,
                    cooldown TEXT DEFAULT 'off',
                    bonus_amount TEXT DEFAULT 'Tell Me',
                    bonus_mode TEXT DEFAULT '',
                    refer_amount TEXT DEFAULT 'Tell Me',
                    refer_mode TEXT DEFAULT ''
                )
            """)
            await db.commit()

            # 2. Schema Patching
            async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
            
            if "withdraw_tax" not in columns:
                await db.execute("ALTER TABLE child_bot_settings ADD COLUMN withdraw_tax INTEGER DEFAULT 0")
                await db.commit()

            # 3. Dynamic selection matrix (Include withdraw_tax)
            async with db.execute("""
                SELECT status_state, payout_mode, min_withdraw, max_withdraw, req_referrals, 
                       cooldown, bonus_amount, bonus_mode, refer_amount, refer_mode, withdraw_tax 
                FROM child_bot_settings WHERE bot_id = ?
            """, (db_bot_id,)) as cursor:
                row = await cursor.fetchone()
                
            if not row:
                await db.execute("INSERT OR IGNORE INTO child_bot_settings (bot_id) VALUES (?)", (db_bot_id,))
                await db.commit()
                status, mode, min_w, max_w, req_ref, cool, b_amt, b_mode, r_amt, r_mode, tax = 'Active', 'AUTO', 100.0, 10000.0, 3, 'off', 'Tell Me', '', 'Tell Me', '', 0
            else:
                status, mode, min_w, max_w, req_ref, cool, b_amt, b_mode, r_amt, r_mode, tax = row

        status_map = {'Active': "🟢 ON", 'Maintenance': "🟡 MAINTENANCE", 'Disable': "🔴 OFF"}
        owner_mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
        
        # Display logic
        bonus_display = f"<b>❎ Nᴏᴛ Sᴇᴛ</b>" if b_amt in ["Tell Me", "❎ Nᴏᴛ Sᴇᴛ"] else f"<b>₹{b_amt} {f'({b_mode})' if b_mode else ''}</b>"
        refer_display = f"<b>❎ Nᴏᴛ Sᴇᴛ</b>" if r_amt in ["Tell Me", "❎ Nᴏᴛ Sᴇᴛ"] else f"<b>₹{r_amt} {f'({r_mode})' if r_mode else ''}</b>"
        tax_display = f"<b>{tax}%</b>" if tax > 0 else "<b>#️⃣ Nᴏᴛ Sᴇᴛ</b>"
        
        panel_text = (
            f"🔍 <b>Wᴇʟᴄᴏᴍᴇ Tᴏ Aᴅᴍɪɴ Pᴀɴᴇʟ</b>\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 <b>Rᴇᴠɪᴇw Bᴏᴛ Dᴇᴛᴀɪʟs</b>\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"    👩‍💻 <b>Mᴀɪɴ Oᴡɴᴇʀ ~</b> <b>{owner_mention}</b> <code>{user_id}</code>\n"
            f"    🤖 <b>Bᴏᴛ Oɴ/Oғғ ~</b> <b>{status_map.get(status, '🟢 ON')}</b>\n"
            f"    📤 <b>Wɪᴛʜᴅʀᴀw Mᴏᴅᴇ ~</b> <b>🟢 {mode}</b>\n"
            f"    ❇️ <b>PᴀyOᴜᴛ Cʜᴀɴɴᴇʟ~</b> <b>#️⃣ Nᴏᴛ Sᴇᴛ</b>\n"
            f"    🎫 <b>Mɪɴɪᴍᴜᴍ Wɪᴛʜᴅʀᴀw ~</b> <b>₹{min_w:.2f}</b>\n"
            f"    🎟 <b>Mᴀxɪᴍᴜᴍ Wɪᴛʜʀᴀw ~</b> <b>₹{max_w:.2f}</b>\n"
            f"    📮 <b>Rᴇǫᴜɪʀᴇᴅ Rᴇғᴇʀʀᴀʟs Fᴏʀ Wɪᴛʜᴅʀᴀw ~</b> <b>{req_ref}</b>\n"
            f"    ⏱️ <b>Wɪᴛʜᴅʀᴀw Cᴏᴏʟᴅᴏwɴ ~</b> <b>{cool}</b>\n"
            f"    📛 <b>Wɪᴛʜᴅʀᴀw Tᴀx Aᴍᴏᴜɴᴛ ~</b> {tax_display}\n"
            f"    🥳 <b>Pᴇʀ Rᴇғᴇʀ AᴍᴏᴜNT ~</b> {refer_display}\n"
            f"    🎁 <b>Dᴀɪʟy BᴏɴUs AᴍᴏᴜNᴛ ~</b> {bonus_display}"
        )
        return panel_text, status

    # =================================================================
    # Dynamic Consolidated Adaptive Matrix Control Admin Keyboard
    # =================================================================
    async def build_child_admin_keyboard(db_bot_id: int) -> types.InlineKeyboardMarkup:
        async with aiosqlite.connect("bot_factory.db") as db:
            # Ensure the table layout and columns exist before selecting
            await db.execute("""
                CREATE TABLE IF NOT EXISTS child_bot_settings (
                    bot_id INTEGER PRIMARY KEY,
                    status_state TEXT DEFAULT 'Active',
                    device_verification TEXT DEFAULT 'On',
                    payout_mode TEXT DEFAULT 'AUTO'
                )
            """)
            await db.commit()

            async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
            
            if "device_verification" not in columns:
                await db.execute("ALTER TABLE child_bot_settings ADD COLUMN device_verification TEXT DEFAULT 'On'")
                await db.commit()

            if "payout_mode" not in columns:
                await db.execute("ALTER TABLE child_bot_settings ADD COLUMN payout_mode TEXT DEFAULT 'AUTO'")
                await db.commit()

            async with db.execute("""
                SELECT status_state, device_verification, payout_mode 
                FROM child_bot_settings WHERE bot_id = ?
            """, (db_bot_id,)) as cursor:
                row = await cursor.fetchone()
        
        if row:
            status_state, device_verify_state, payout_mode_state = row[0], row[1], row[2]
        else:
            status_state, device_verify_state, payout_mode_state = "Active", "On", "AUTO"
    
        builder = InlineKeyboardBuilder()



        # --- ROW 1: Cyclic Dynamic Status Engine ---
        # REMOVED 'style' to stop the TelegramBadRequest
        if status_state == "Active":
            builder.add(types.InlineKeyboardButton(
                text=" Bot: Active", 
                callback_data="child_toggle_status", 
                icon_custom_emoji_id="6300633168290517241"
            ))
        elif status_state == "Maintenance":
            builder.add(types.InlineKeyboardButton(
                text=" Bot: Maintenance", 
                callback_data="child_toggle_status", 
                icon_custom_emoji_id="6309997365226903510"
            ))
        else:
            builder.add(types.InlineKeyboardButton(
                text=" Bot: Disable", 
                callback_data="child_toggle_status", 
                icon_custom_emoji_id="4926956800005112527"
            ))


        # --- ROW 2: Ownership Management ---
        builder.add(types.InlineKeyboardButton(text=" Transfer Ownership", callback_data="child_adm_transfer", style="primary", icon_custom_emoji_id="5251203410396458957"))
        builder.add(types.InlineKeyboardButton(text=" Set Withdraw Tax", callback_data="child_adm_settax", style="primary", icon_custom_emoji_id="4926956800005112527"))
        
        # --- ROW 3: Device Security ---
        if device_verify_state == "On":
            builder.add(types.InlineKeyboardButton(text=" Device Verification: On", callback_data="child_toggle_device_verify", style="success", icon_custom_emoji_id="5296369303661067030"))
        else:
            builder.add(types.InlineKeyboardButton(text=" Device Verification: Off", callback_data="child_toggle_device_verify", style="danger", icon_custom_emoji_id="5296369303661067030"))

        # --- ROW 4: Moderation ---
        builder.add(types.InlineKeyboardButton(text=" Ban User", callback_data="child_adm_ban", style="danger", icon_custom_emoji_id="6309648704076782071"))
        builder.add(types.InlineKeyboardButton(text=" Verify User", callback_data="child_adm_verify", style="success", icon_custom_emoji_id="5350722806281676158"))
        
        # --- ROW 5: Financial Operations ---
        if payout_mode_state == "AUTO":
            builder.add(types.InlineKeyboardButton(text=" Payouts: Active", callback_data="child_adm_payout_toggle", style="primary", icon_custom_emoji_id="6300633168290517241"))
        else:
            builder.add(types.InlineKeyboardButton(text=" Payouts: OFF", callback_data="child_adm_payout_toggle", style="danger", icon_custom_emoji_id="4926956800005112527"))

        
        # --- ROW 6: Accounting ---
        builder.add(types.InlineKeyboardButton(text=" Remove Balance", callback_data="child_adm_rembal", style="danger", icon_custom_emoji_id="6309980103753341998"))
        builder.add(types.InlineKeyboardButton(text=" Add Balance", callback_data="child_adm_addbal", style="success", icon_custom_emoji_id="6055646953826424170"))
        
        # --- ROW 7: Marketing ---
        builder.add(types.InlineKeyboardButton(text=" Manage Channels", callback_data="child_adm_channels", style="primary", icon_custom_emoji_id="6068806600477383919"))
        
        # --- ROW 8: Yield Parameters ---
        builder.add(types.InlineKeyboardButton(text=" Set Per Refer", callback_data="child_adm_refer", style="primary", icon_custom_emoji_id="5375296873982604963"))
        builder.add(types.InlineKeyboardButton(text=" Broadcast", callback_data="child_adm_broadcast", style="primary", icon_custom_emoji_id="5382013970905309819"))
        
        # --- ROW 9: Treasury ---
        builder.add(types.InlineKeyboardButton(text=" Manage Withdraws", callback_data="child_adm_withdraws", style="primary", icon_custom_emoji_id="6267008582294705964"))
        
        # --- ROW 10: Analytics & Rewards ---
        builder.add(types.InlineKeyboardButton(text=" Bot Analytics", callback_data="child_adm_analytics", style="primary", icon_custom_emoji_id="6300797828746711280"))
        builder.add(types.InlineKeyboardButton(text=" Gift Codes", callback_data="child_adm_giftcodes", style="primary", icon_custom_emoji_id="4996755833950831347"))
        
        # --- ROW 11: Content ---
        builder.add(types.InlineKeyboardButton(text=" Manage Texts", callback_data="child_adm_texts", style="primary", icon_custom_emoji_id="6300651726844204536"))
        
        # --- ROW 12: Gateway Pipelines ---
        builder.add(types.InlineKeyboardButton(text=" Daily Claim Bonus", callback_data="child_adm_daily", style="primary", icon_custom_emoji_id="6291702140280771095"))
        builder.add(types.InlineKeyboardButton(text=" Gateway Setup", callback_data="child_adm_gateway", style="primary", icon_custom_emoji_id="5447644880824181073"))
        
        # --- ROW 13: Operations & Features Custom Pipelines ---
        builder.add(types.InlineKeyboardButton(text=" Set Fund", callback_data="child_adm_setfund", style="success", icon_custom_emoji_id="6170401663862444833"))
        builder.add(types.InlineKeyboardButton(text=" Set Welcome Channel", callback_data="child_adm_setwelcome", style="primary", icon_custom_emoji_id="5064709487953183440"))

        builder.adjust(1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 2)
        return builder.as_markup()

    # =================================================================
    # Active Interaction Message and Callback Handlers
    # =================================================================

    # Command Entry Point Trigger inside dynamic child dispatcher
    @cloned_dp.message(Command("adminpanel"))
    async def child_command_admin_panel(message: types.Message):
        async with aiosqlite.connect("bot_factory.db") as db:
            async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                row = await cursor.fetchone()
        
        if not row or message.from_user.id != row[0]:
            await message.answer("❌ <b>Unauthorized Operation Access Blocked. You do not own this bot instance.</b>", parse_mode="HTML")
            return
            
        text_layout, _ = await get_child_admin_panel_content(db_bot_id, row[0], message.from_user.first_name)
        current_keyboard = await build_child_admin_keyboard(db_bot_id)
        await message.answer(text=text_layout, parse_mode="HTML", reply_markup=current_keyboard)

    @cloned_dp.callback_query(F.data == "child_back_to_admin")
    async def route_back_to_child_admin_panel(callback_query: types.CallbackQuery, state: FSMContext):
        await state.clear()  # Clear transient setup values securely
        async with aiosqlite.connect("bot_factory.db") as db:
            async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                row = await cursor.fetchone()
        
        if not row or callback_query.from_user.id != row[0]:
            await callback_query.answer("❌ Access Refused.", show_alert=True)
            return

        text_layout, _ = await get_child_admin_panel_content(db_bot_id, row[0], callback_query.from_user.first_name)
        updated_keyboard = await build_child_admin_keyboard(db_bot_id)
        
        try:
            await callback_query.message.edit_text(
                text=text_layout, 
                parse_mode="HTML", 
                reply_markup=updated_keyboard
            )
        except Exception:
            pass
        await callback_query.answer()

    @cloned_dp.callback_query(F.data == "child_toggle_status")
    async def process_child_status_toggle(callback_query: types.CallbackQuery):
        # 1. Ownership Check
        async with aiosqlite.connect("bot_factory.db") as db:
            async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                row = await cursor.fetchone()
                
        if not row or callback_query.from_user.id != row[0]:
            await callback_query.answer("❌ Access Refused.", show_alert=True)
            return
            
        # 2. Get CURRENT state from DB
        async with aiosqlite.connect("bot_factory.db") as db:
            async with db.execute("SELECT status_state FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                current_db_row = await cursor.fetchone()
                current_state = current_db_row[0] if current_db_row else "Active"
            
            # 3. Calculate NEXT state
            if current_state == "Active":
                next_state = "Maintenance"
            elif current_state == "Maintenance":
                next_state = "Disable"
            else:
                next_state = "Active"
            
            # 4. Save to DB
            await db.execute("UPDATE child_bot_settings SET status_state = ? WHERE bot_id = ?", (next_state, db_bot_id))
            await db.commit()
            
        # 5. Refresh UI
        updated_text, _ = await get_child_admin_panel_content(db_bot_id, row[0], callback_query.from_user.first_name)
        updated_keyboard = await build_child_admin_keyboard(db_bot_id)
        
        await callback_query.message.edit_text(
            text=updated_text,
            parse_mode="HTML",
            reply_markup=updated_keyboard
        )
        await callback_query.answer(f"Status Updated ➡️ {next_state}")


        # -----------------------------------------------------------------
        # Withdrawal Tax Configuration Engine
        # -----------------------------------------------------------------

        # 1. Catch button selection to trigger Tax setup
        @cloned_dp.callback_query(F.data == "child_adm_settax")
        async def start_set_tax(callback_query: types.CallbackQuery, state: FSMContext):
            await state.update_data(db_bot_id=db_bot_id)
            await state.set_state(TaxSetup.waiting_for_tax)
            
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text=" Back To Main Panel", 
                callback_data="child_back_to_admin", 
                style="primary", 
                icon_custom_emoji_id="6309851100115640076"
            ))

            
            await callback_query.message.edit_text(
                text='<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> <b>Provide The Withdrawn Amount Tax (Will Store In %).</b>',
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
            await callback_query.answer()

        # 2. Process incoming tax value safely
        @cloned_dp.message(TaxSetup.waiting_for_tax)
        async def process_tax_input(message: types.Message, state: FSMContext):
            if not message.text.isdigit():
                await message.answer("❌ <b>Please enter a valid numeric percentage.</b>", parse_mode="HTML")
                return

            tax_value = int(message.text)
            data = await state.get_data()
            target_bot_id = data.get("db_bot_id")

            # Save to DB
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET withdraw_tax = ? WHERE bot_id = ?", (tax_value, target_bot_id))
                await db.commit()

            await state.clear()
            
            # Success Message
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text=" Back To Main Panel", 
                callback_data="child_adm_withdraws",
                style="primary", 
                icon_custom_emoji_id="6309851100115640076"
            ))

            
            await message.answer(
                text=f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Withdrawal Amount Tax Have Been Set: {tax_value}%</b>',
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )

        # -----------------------------------------------------------------
        # Cloned Bot Admin: Ownership Migration Suite
        # -----------------------------------------------------------------

        # 1. Capture the "Transfer Ownership" button click from the Admin Console
        @cloned_dp.callback_query(F.data == "child_adm_transfer")
        async def prompt_admin_transfer_ownership(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard: Confirm original ownership matrix first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the active owner can transfer ownership.", show_alert=True)
                return

            ask_transfer_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Provide User Chat ID To Transfer Ownership!</b>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildTransferOwnershipSetup.waiting_for_new_owner_id)
            await callback_query.message.edit_text(text=ask_transfer_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Input payload processor and validation scanner
        @cloned_dp.message(ChildTransferOwnershipSetup.waiting_for_new_owner_id)
        async def process_admin_ownership_transfer_input(message: types.Message, state: FSMContext):
            # Re-verify administrative constraints before execution
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            target_input = message.text.strip() if message.text else ""
            if not target_input.isdigit():
                await message.answer("❌ <b>Invalid Input! Please provide a numeric Telegram Chat ID string.</b>", parse_mode="HTML")
                return

            target_new_owner_id = int(target_input)
            raw_bot_token_id = message.bot.id

            async with aiosqlite.connect("bot_factory.db") as db:
                # CRITICAL SCANNER: Verify if target user has initialized an active record workspace footprint inside the bot
                async with db.execute(
                    "SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", 
                    (target_new_owner_id, raw_bot_token_id)
                ) as cursor:
                    user_record_exists = await cursor.fetchone()

            if not user_record_exists:
                decline_text = (
                    f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> '
                    f'<b>Ownership Transfer Decline! User Haven\'t Started The Bot Yet!</b>'
                )
                back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Return To Panel", callback_data="child_back_to_admin"))
                await message.answer(text=decline_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
                await state.clear()
                return

            # Resolve user chat data details from the active runtime context to build structural mention tokens
            try:
                target_chat_profile = await message.bot.get_chat(chat_id=target_new_owner_id)
                new_owner_title = target_chat_profile.first_name if target_chat_profile.first_name else "New Administrator"
                new_owner_mention = f'<a href="tg://user?id={target_new_owner_id}">{new_owner_title}</a>'
            except Exception:
                new_owner_mention = f'<b>User Profile</b>'

            # 3. Commit ownership database field updates permanently
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute(
                    "UPDATE cloned_bots SET user_id = ? WHERE id = ?", 
                    (target_new_owner_id, db_bot_id)
                )
                await db.commit()

            success_transfer_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Ownership Have Been Transferred To: <code>{target_new_owner_id}</code> {new_owner_mention}</b>'
            )

            # Build static standalone layout button (The old owner can now only exit back to main clone user space)
            exit_panel_builder = ReplyKeyboardBuilder()
            exit_panel_builder.row(types.KeyboardButton(text="Balance"))
            exit_panel_builder.adjust(1)

            await message.answer(text=success_transfer_text, parse_mode="HTML", reply_markup=get_clone_main_menu_keyboard())
            await state.clear()

            # Push instant priority transaction alert straight to the new owner's dashboard view
            notify_new_owner_text = (
                f'<tg-emoji emoji-id="6118333272821865260">👑</tg-emoji> '
                f'<b>Congratulations! You are now the Main Owner of this bot instance.\n\n'
                f'Use command /adminpanel to access your dashboard settings configuration console framework instantly!</b>'
            )
            try:
                await message.bot.send_message(chat_id=target_new_owner_id, text=notify_new_owner_text, parse_mode="HTML")
            except Exception:
                pass


        # =================================================================
        # CLONED BOT ROUTER: User Invites Live Analytics Panel
        # =================================================================
        @cloned_dp.callback_query(F.data == "cloned_my_invites")
        async def process_cloned_user_my_invites_panel(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            raw_bot_token_id = str(callback_query.bot.id)

            async with aiosqlite.connect("bot_factory.db") as db:
                # Resolve active bot ID
                cursor = await db.execute("SELECT id FROM cloned_bots WHERE bot_id LIKE ?", (f"{raw_bot_token_id}%",))
                row = await cursor.fetchone()
                active_db_id = str(row[0]) if row else None

                # 1. Total Joined
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM user_referrals 
                    WHERE referrer_id = ? AND (CAST(bot_id AS TEXT) = ? OR CAST(bot_id AS TEXT) = ?)
                """, (user_id, active_db_id, raw_bot_token_id))
                users_joined = (await cursor.fetchone())[0]

                # 2. Pending Joins
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT r.referred_id) FROM user_referrals r
                    JOIN child_join_requests j ON r.referred_id = j.user_id
                    LEFT JOIN user_verification v ON r.referred_id = v.user_id
                    WHERE r.referrer_id = ? AND (CAST(r.bot_id AS TEXT) = ? OR CAST(r.bot_id AS TEXT) = ?) 
                    AND (v.seen IS NULL OR v.seen = 0)
                """, (user_id, active_db_id, raw_bot_token_id))
                pending_joins = (await cursor.fetchone())[0]

                # 3. Verified
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM user_referrals r
                    JOIN user_verification v ON r.referred_id = v.user_id
                    WHERE r.referrer_id = ? AND (CAST(r.bot_id AS TEXT) = ? OR CAST(r.bot_id AS TEXT) = ?) AND v.seen = 1
                """, (user_id, active_db_id, raw_bot_token_id))
                verified_referrals = (await cursor.fetchone())[0]

            text = (
                f'<b>👥 Users Joined Via Your Link: {users_joined}</b>\n\n'
                f'<b>⏳ Pending Channel Joins: {pending_joins}</b>\n\n'
                f'<b>✅ Verified & Credited Referrals: {verified_referrals}</b>'
            )
            
            kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 Return To Menu", callback_data="child_user_main_menu")]])
            
            try: await callback_query.message.edit_text(text=text, parse_mode="HTML", reply_markup=kb)
            except: await callback_query.message.answer(text=text, parse_mode="HTML", reply_markup=kb)
            await callback_query.answer()


        # =================================================================
        # CLONED BOT ROUTER: Live Top Referrals Leaderboard Engine
        # =================================================================
        @cloned_dp.callback_query(F.data == "cloned_leaderboard")
        async def process_cloned_leaderboard_panel(callback_query: types.CallbackQuery):
            raw_bot_token_id = str(callback_query.bot.id)

            async with aiosqlite.connect("bot_factory.db") as db:
                cursor = await db.execute("SELECT id FROM cloned_bots WHERE bot_id LIKE ?", (f"{raw_bot_token_id}%",))
                row = await cursor.fetchone()
                active_db_id = str(row[0]) if row else None

                query = """
                    SELECT referrer_id, COUNT(*) FROM user_referrals 
                    JOIN user_verification ON user_referrals.referred_id = user_verification.user_id 
                    WHERE (CAST(user_referrals.bot_id AS TEXT) = ? OR CAST(user_referrals.bot_id AS TEXT) = ?) 
                    AND user_verification.seen = 1 
                    GROUP BY referrer_id ORDER BY COUNT(*) DESC LIMIT 5
                """
                cursor = await db.execute(query, (active_db_id, raw_bot_token_id))
                top_leaders = await cursor.fetchall()

            lines = []
            for i, (uid, count) in enumerate(top_leaders, 1):
                badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                lines.append(f"<b>{badges[i-1]} 👤 <a href='tg://user?id={uid}'>User {uid}</a>\n✅ Verified: {count}</b>")

            text = f"<b>✨ Top Referral Leaders 🚀</b>\n\n" + "\n\n".join(lines) if lines else "<b>No leaders yet.</b>"

            try: await callback_query.message.edit_text(text=text, parse_mode="HTML")
            except: await callback_query.message.answer(text=text, parse_mode="HTML")
            await callback_query.answer()



        # =================================================================
        # CLONED BOT ADMIN: Manage Texts Sub-Menu Screen System
        # =================================================================

        @cloned_dp.callback_query(F.data == "child_adm_texts")
        async def handle_cloned_admin_manage_texts(callback_query: types.CallbackQuery):
            # Security verification guard: Confirm ownership matrix via DB tracking rows
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can adjust text layouts.", show_alert=True)
                return

            text_menu_prompt = (
                f'<tg-emoji emoji-id="5442939099906325301">🎁</tg-emoji> <b>Select An Option Below To Manage Texts!</b>'
            )

            # Build the custom 2-row inline matrix grid layout
            text_builder = InlineKeyboardBuilder()
            
            # --- Row 1: Left & Right Options ---
            text_builder.add(types.InlineKeyboardButton(
                text=" Edit Withdraw Off Text",
                callback_data="child_text_edit_off",
                style="danger",
                icon_custom_emoji_id="4926956800005112527"
            ))
            text_builder.add(types.InlineKeyboardButton(
                text=" Edit Withdraw Text",
                callback_data="child_text_edit_on",
                style="primary",
                icon_custom_emoji_id="6170147440453227548"
            ))
            
            # Pack the first row tightly with 2 options
            text_builder.adjust(2)

            # --- Row 2: Bottom Navigation Escape Target ---
            bottom_row_builder = InlineKeyboardBuilder()
            bottom_row_builder.add(types.InlineKeyboardButton(
                text="🔙 Back To Console",
                callback_data="child_back_to_admin"
            ))
            
            # Combine structural layout frames sequentially as individual sibling nodes
            text_builder.attach(bottom_row_builder)

            try:
                await callback_query.message.edit_text(
                    text=text_menu_prompt,
                    parse_mode="HTML",
                    reply_markup=text_builder.as_markup()
                )
                await callback_query.answer()
            except Exception:
                await callback_query.answer()


        # =================================================================
        # CLONED BOT ADMIN: Custom Withdrawal Text Management Engine
        # =================================================================

        # --- 1. PROMPT FOR WITHDRAW OFF TEXT ---
        @cloned_dp.callback_query(F.data == "child_text_edit_off")
        async def prompt_edit_withdraw_off_text(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Send Your Withdraw Off Text As Message!</b>\n\n'
                f'<tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> <b>Only Texts &amp; Numeric Value Support!</b>'
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_texts"))
            await state.set_state(ChildAdminBalanceSetup.waiting_for_withdraw_off_text)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # --- 2. PROMPT FOR WITHDRAW TEXT ---
        @cloned_dp.callback_query(F.data == "child_text_edit_on")
        async def prompt_edit_withdraw_on_text(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Send Your Withdraw Text As Message!</b>\n\n'
                f'<tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> <b>Only Texts &amp; Numeric Value Support!</b>'
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_texts"))
            await state.set_state(ChildAdminBalanceSetup.waiting_for_withdraw_on_text)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # --- 3. PROCESS WITHDRAW OFF TEXT INPUT ---
        @cloned_dp.message(ChildAdminBalanceSetup.waiting_for_withdraw_off_text)
        async def process_withdraw_off_text_input(message: types.Message, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Access.</b>", parse_mode="HTML")
                await state.clear()
                return

            # Reject photos, videos, stickers, documents, etc.
            if not message.text:
                await message.answer('<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <b>Only Texts &amp; Numeric Value Allowed!</b>', parse_mode="HTML")
                return

            # Capture raw HTML text directly containing styling entities
            provided_html_text = message.html_text

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_texts (
                        bot_id INTEGER PRIMARY KEY,
                        withdraw_off_text TEXT,
                        withdraw_text TEXT
                    )
                """)
                await db.commit()

                await db.execute("""
                    INSERT INTO child_bot_texts (bot_id, withdraw_off_text)
                    VALUES (?, ?) ON CONFLICT(bot_id) DO UPDATE SET withdraw_off_text = ?
                """, (db_bot_id, provided_html_text, provided_html_text))
                await db.commit()

            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Successfully Edited Withdrawal Off Text!</b>\n'
                f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
                f'{provided_html_text}'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back To Console", callback_data="child_adm_texts"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # --- 4. PROCESS WITHDRAW TEXT INPUT ---
        @cloned_dp.message(ChildAdminBalanceSetup.waiting_for_withdraw_on_text)
        async def process_withdraw_on_text_input(message: types.Message, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Access.</b>", parse_mode="HTML")
                await state.clear()
                return

            # Reject photos, videos, stickers, documents, etc.
            if not message.text:
                await message.answer('<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <b>Only Texts &amp; Numeric Value Allowed!</b>', parse_mode="HTML")
                return

            # Capture raw HTML text directly containing styling entities
            provided_html_text = message.html_text

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_texts (
                        bot_id INTEGER PRIMARY KEY,
                        withdraw_off_text TEXT,
                        withdraw_text TEXT
                    )
                """)
                await db.commit()

                await db.execute("""
                    INSERT INTO child_bot_texts (bot_id, withdraw_text)
                    VALUES (?, ?) ON CONFLICT(bot_id) DO UPDATE SET withdraw_text = ?
                """, (db_bot_id, provided_html_text, provided_html_text))
                await db.commit()

            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Successfully Edited Withdrawal Text!</b>\n'
                f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
                f'{provided_html_text}'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back To Console", callback_data="child_adm_texts"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Bot Admin: Channels Infrastructure Configuration Dashboard
        # -----------------------------------------------------------------

        # Helper function to dynamically pull and flip Channel Display Mode settings from DB
        async def query_current_show_mode():
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_channels_config (
                        bot_id INTEGER PRIMARY KEY,
                        show_mode TEXT DEFAULT 'Not Joined Only'
                    )
                """)
                await db.commit()
                async with db.execute("SELECT show_mode FROM child_channels_config WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
                if not row:
                    await db.execute("INSERT INTO child_channels_config (bot_id, show_mode) VALUES (?, 'Not Joined Only')", (db_bot_id,))
                    await db.commit()
                    return "Not Joined Only"
                return row[0]

        # 2. Toggle Mode Callback Execution Node
        @cloned_dp.callback_query(F.data == "chn_panel_toggle_mode")
        async def process_child_channels_display_toggle(callback_query: types.CallbackQuery):
            current_mode = await query_current_show_mode()
            next_mode = "All Channels" if current_mode == "Not Joined Only" else "Not Joined Only"

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_channels_config SET show_mode = ? WHERE bot_id = ?", (next_mode, db_bot_id))
                await db.commit()

            # Refresh view with newly mutated state context variables cleanly
            await process_child_channels_management_dashboard(callback_query)
            await callback_query.answer(f"Display Style set to: {next_mode}")

        # -----------------------------------------------------------------
        # Cloned Bot Admin: Dynamic Multi-Channel Integration Pipeline
        # -----------------------------------------------------------------

        # A. Core Dashboard Renderer Overhaul to render dynamic channel rows
        @cloned_dp.callback_query(F.data == "child_adm_channels")
        async def process_child_channels_management_dashboard(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused.", show_alert=True)
                return

            current_mode = await query_current_show_mode()

            channels_panel_text = (
                f'<b><tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> Manage Channels Panel</b>\n\n'
                f'<b><tg-emoji emoji-id="6298317205960397843">✅</tg-emoji> Add Channels</b>\n'
                f'<b><tg-emoji emoji-id="6300633168290517241">🟢</tg-emoji> Set Show Style</b>\n\n'
                f'<b>Click <tg-emoji emoji-id="6305134186642544683">👀</tg-emoji> to view info  <tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> to delete</b>\n\n'
                f'<b>Click On Channel To Set Invite Link For Private Channels.</b>'
            )

            builder = InlineKeyboardBuilder()
            
            # Enforce dynamic table creation right here BEFORE running the select query
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot_id INTEGER,
                        channel_id TEXT,
                        channel_name TEXT,
                        invite_link TEXT
                    )
                """)
                await db.commit()

                # Safely query channel registries
                async with db.execute("SELECT id, channel_id, channel_name, invite_link FROM child_bot_channels WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    saved_channels = await cursor.fetchall()

            # Dynamic Row Matrix Generation Loop
            for ch_row in saved_channels:
                row_pk, ch_id, ch_name, inv_link = ch_row
                
                # Button 1: Channel Name/Title Button (Primary)
                builder.button(
                    text=f"{ch_name}", 
                    callback_data=f"chn_edit_link_{row_pk}",
                    style="primary"
                )
                # Button 2: View Info Button (Success)
                builder.button(
                    text="View", 
                    callback_data=f"chn_view_info_{row_pk}",
                    style="success",
                    icon_custom_emoji_id="6305134186642544683"
                )
                # Button 3: Purge Deletion Button (Danger)
                builder.button(
                    text=" ", 
                    callback_data=f"chn_delete_purg_{row_pk}",
                    style="danger",
                    icon_custom_emoji_id="6309980103753341998"
                )
            
            # Restructure matrix to exactly 3 items per channel row
            total_channel_buttons = len(list(saved_channels)) * 3
            if total_channel_buttons > 0:
                builder.adjust(*([3] * (total_channel_buttons // 3)))

            # Append bottom dashboard operational utility controllers
            control_builder = InlineKeyboardBuilder()
            control_builder.button(text="Add Channels", callback_data="chn_panel_add_trigger", style="primary", icon_custom_emoji_id="6298317205960397843")
            control_builder.button(text="View Channels", callback_data="chn_panel_view_trigger", style="primary", icon_custom_emoji_id="6305134186642544683")
            
            active_btn_style = "danger" if current_mode == "Not Joined Only" else "success"
            control_builder.button(text=f"Show Mode: {current_mode}", callback_data="chn_panel_toggle_mode", style=active_btn_style, icon_custom_emoji_id="6300633168290517241")
            control_builder.button(text="🔙 Back To Console", callback_data="child_back_to_admin")
            control_builder.adjust(1, 1, 1, 1)
            
            builder.attach(control_builder)
            await callback_query.message.edit_text(text=channels_panel_text, parse_mode="HTML", reply_markup=builder.as_markup())
            await callback_query.answer()

        # B. Prompt user for channel entry credentials
        @cloned_dp.callback_query(F.data == "chn_panel_add_trigger")
        async def trigger_prompt_add_channel(callback_query: types.CallbackQuery, state: FSMContext):
            prompt_text = (
                f'<b><tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> Provide Your Channel Username (@YourChannel) Or Forward Any Message From The Channel!</b>\n\n'
                f'<b><tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> Bot Must Be Admin With Invite User Via Link Permission!</b>'
            )
            cancel_builder = InlineKeyboardBuilder()
            cancel_builder.button(text="⬅️ Cancel", callback_data="child_adm_channels")
            await state.set_state(ChildChannelsDashboardSetup.waiting_for_channel_input)
            await callback_query.message.edit_text(text=prompt_text, parse_mode="HTML", reply_markup=cancel_builder.as_markup())
            await callback_query.answer()

        # C. Input Payload Processor & Deep Administrative Permission Check
        @cloned_dp.message(ChildChannelsDashboardSetup.waiting_for_channel_input)
        async def process_channel_input_and_verify(message: types.Message, state: FSMContext):
            target_chat_identifier = None
            
            if message.forward_origin and message.forward_origin.type == "channel":
                target_chat_identifier = message.forward_origin.chat.id
            elif message.text and message.text.strip().startswith("@"):
                target_chat_identifier = message.text.strip()
            else:
                await message.answer("<b>❌ Invalid Entry! Please forward a message from your channel or send a username starting with @.</b>", parse_mode="HTML")
                return

            try:
                channel_info = await message.bot.get_chat(chat_id=target_chat_identifier)
                bot_permissions = await message.bot.get_chat_member(chat_id=channel_info.id, user_id=message.bot.id)
                
                if bot_permissions.status not in ["administrator", "creator"]:
                    await message.answer('<b><tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> Bot Is Not Admin!</b>', parse_mode="HTML")
                    return
                
                if not bot_permissions.can_invite_users:
                    await message.answer('<b><tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji> Your Channel Lack Invite User Via Link Permission To The Bot!</b>', parse_mode="HTML")
                    return

                # Create standard invite link layout footprint natively
                invite_link_obj = await message.bot.create_chat_invite_link(chat_id=channel_info.id, name="Dynamic Welcome Link")
                generated_link = invite_link_obj.invite_link
                channel_title = channel_info.title if channel_info.title else "Our Channel Network"

            except Exception as api_err:
                await message.answer(f"<b>❌ API Communication Error: Ensure the Bot has been added inside the channel as Admin first. Log: {api_err}</b>", parse_mode="HTML")
                return

            # Persist variables inside the database rows cleanly
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    INSERT INTO child_bot_channels (bot_id, channel_id, channel_name, invite_link)
                    VALUES (?, ?, ?, ?)
                """, (db_bot_id, str(channel_info.id), channel_title, generated_link))
                await db.commit()

            success_response = (
                f'<b><tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> Successfully Added {channel_title} (<code>{channel_info.id}</code>)</b>\n\n'
                f'<b><tg-emoji emoji-id="6305134186642544683">👀</tg-emoji> Invite Link: {generated_link}</b>'
            )
            
            back_panel = InlineKeyboardBuilder()
            back_panel.button(text="🔙 Return To Panel", callback_data="child_adm_channels")
            await message.answer(text=success_response, parse_mode="HTML", reply_markup=back_panel.as_markup())
            await state.clear()

        # D. Deletion Handler to drop registered matrix channels instantly
        @cloned_dp.callback_query(F.data.startswith("chn_delete_purg_"))
        async def process_purge_channel_record(callback_query: types.CallbackQuery):
            record_id = int(callback_query.data.split("_")[3])
            
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("DELETE FROM child_bot_channels WHERE id = ? AND bot_id = ?", (record_id, db_bot_id))
                await db.commit()
                
            await callback_query.answer("🗑️ Channel removed successfully from system registries.", show_alert=True)
            await process_child_channels_management_dashboard(callback_query)


        # E. View Action Handler node to print invite mappings
        @cloned_dp.callback_query(F.data.startswith("chn_view_info_"))
        async def process_view_channel_record_info(callback_query: types.CallbackQuery):
            record_id = int(callback_query.data.split("_")[3])
            
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT channel_name, channel_id, invite_link FROM child_bot_channels WHERE id = ?", (record_id,)) as cursor:
                    row = await cursor.fetchone()
            
            if not row:
                await callback_query.answer("❌ Entry missing.", show_alert=True)
                return

            name, c_id, link = row
            raw_bot_token_id = callback_query.bot.id

            # Gather analytical context statistics metrics from platform tables
            async with aiosqlite.connect("bot_factory.db") as db:
                # 1. Total Joined: Calculate users who verified and have completed actions
                async with db.execute(
                    "SELECT COUNT(*) FROM user_verification WHERE bot_id = ? AND seen = 1", 
                    (raw_bot_token_id,)
                ) as count_cursor:
                    total_joined = (await count_cursor.fetchone())[0]

                # 2. Total Left: Users whose current status is unverified or marked failed
                async with db.execute(
                    "SELECT COUNT(*) FROM user_verification WHERE bot_id = ? AND seen = 0", 
                    (raw_bot_token_id,)
                ) as failure_cursor:
                    total_left = (await failure_cursor.fetchone())[0]

                # 3. Total Requests: ✅ FIXED: Queries the actual logged admin approval join requests for this specific channel
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_join_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER, channel_id TEXT, user_id INTEGER, requested_at TEXT
                    )
                """)
                await db.commit()

                async with db.execute(
                    "SELECT COUNT(*) FROM child_join_requests WHERE bot_id = ? AND channel_id = ?", 
                    (raw_bot_token_id, str(c_id))
                ) as request_cursor:
                    total_requests = (await request_cursor.fetchone())[0]

            # Compile structural summary text block with all lines explicitly bolded
            detailed_info_view = (
                f'<b><tg-emoji emoji-id="4999015678238262018">✨</tg-emoji>Channel Info:</b>\n\n'
                f'<b><tg-emoji emoji-id="6305134186642544683">👀</tg-emoji>Name: {name}</b>\n\n'
                f'<b><tg-emoji emoji-id="6309997365226903510">🔗</tg-emoji>Invite Link: {link}</b>\n\n'
                f'<b><tg-emoji emoji-id="6267008582294705964">✅</tg-emoji>Total Joined: {total_joined}</b>\n\n'
                f'<b><tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji>Total User Left: {total_left}</b>\n\n'
                f'<b><tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji>Total Requests: {total_requests}</b>'
            )

            # Build inline return navigation button to get back to the channels console layout smoothly
            back_navigation_builder = InlineKeyboardBuilder()
            back_navigation_builder.button(text="🔙 Return To Panel", callback_data="child_adm_channels")

            # Update the panel text window interface cleanly with HTML layouts
            await callback_query.message.edit_text(
                text=detailed_info_view, 
                parse_mode="HTML", 
                reply_markup=back_navigation_builder.as_markup(),
                disable_web_page_preview=True
            )
            await callback_query.answer()

        # -----------------------------------------------------------------
        # Cloned Bot Admin: Private Channel Link Overwrite Matrix
        # -----------------------------------------------------------------

        # 1. Capture clicking on the added Channel Name button from row list
        @cloned_dp.callback_query(F.data.startswith("chn_edit_link_"))
        async def trigger_edit_channel_private_link(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification checkpoint: Confirm administrative status entries
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can modify target links.", show_alert=True)
                return

            row_pk = int(callback_query.data.split("_")[3])
            
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT channel_name FROM child_bot_channels WHERE id = ?", (row_pk,)) as cursor:
                    channel_row = await cursor.fetchone()
            
            if not channel_row:
                await callback_query.answer("❌ Channel entry not found inside registries.", show_alert=True)
                return

            channel_name = channel_row[0]
            ask_link_text = f'<b><tg-emoji emoji-id="6267008582294705964">✅</tg-emoji>Send New Private Link For Channel: {channel_name}</b>'

            cancel_btn = InlineKeyboardBuilder()
            cancel_btn.button(text="⬅️ Cancel", callback_data="child_adm_channels")
            
            # Save row references within memory buffers securely
            await state.update_data(target_channel_pk=row_pk, target_channel_name=channel_name)
            await state.set_state(ChildChannelLinkEditSetup.waiting_for_private_invite_link)
            
            await callback_query.message.edit_text(text=ask_link_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Capture and save the new private invite link string
        @cloned_dp.message(ChildChannelLinkEditSetup.waiting_for_private_invite_link)
        async def process_custom_private_link_input(message: types.Message, state: FSMContext):
            user_input = message.text.strip() if message.text else ""
            
            # Basic link syntax structure check
            if "t.me/" not in user_input:
                await message.answer("❌ <b>Invalid Link! Please provide a valid Telegram link containing 't.me/'.</b>", parse_mode="HTML")
                return

            fsm_data = await state.get_data()
            row_pk = fsm_data.get("target_channel_pk")
            channel_name = fsm_data.get("target_channel_name")

            # Commit the update directly to the multi-channel database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_channels SET invite_link = ? WHERE id = ?", (user_input, row_pk))
                await db.commit()

            success_update_text = f'<b><tg-emoji emoji-id="6309997365226903510">🔗</tg-emoji>Private Link Updated: {user_input}</b>'
            
            back_panel = InlineKeyboardBuilder()
            back_panel.button(text="🔙 Return To Panel", callback_data="child_adm_channels")
            
            await message.answer(text=success_update_text, parse_mode="HTML", reply_markup=back_panel.as_markup())
            await state.clear()


        # -----------------------------------------------------------------
        # Gift Code Management Engine
        # -----------------------------------------------------------------

        @cloned_dp.callback_query(F.data == "child_adm_giftcodes")
        async def display_giftcode_dashboard(callback_query: types.CallbackQuery, state: FSMContext):
            dashboard_text = (
                f"<b>╭───〔 <tg-emoji emoji-id='5442939099906325301'>🎁</tg-emoji> Gift Code Management 〕───╮</b>\n\n"
                f"<b><tg-emoji emoji-id='5375296873982604963'>💰</tg-emoji> Amount Per User    » ❎Not Set</b>\n"
                f"<b><tg-emoji emoji-id='4942888689131848546'>👥</tg-emoji> Total Users        » ❎Not Set</b>\n"
                f"<b><tg-emoji emoji-id='5442939099906325301'>🎁</tg-emoji> Required Refers    » ❎Not Set</b>\n"
                f"<b>├─ Reply With ────────────────</b>\n"
                f"<b><tg-emoji emoji-id='5472030678633684592'>💸</tg-emoji> Amount Per User</b>\n"
                f"<b><tg-emoji emoji-id='4942888689131848546'>👥</tg-emoji> Total Users</b>\n"
                f"<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> Required Refers (0 = Off)</b>\n\n"
                f"<b><tg-emoji emoji-id='6068806600477383919'>⚡</tg-emoji> Or Use The Button To Set Wager!</b>\n\n"
                f"<b>|•| Format: 2-3-4</b>\n"
                f"<b>╰─────────────────────────────╯</b>"
            )

            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(text=" Set Wager", callback_data="child_set_wager", style="primary", icon_custom_emoji_id="4996755833950831347"))
            builder.add(types.InlineKeyboardButton(text=" View Active Gift Codes", callback_data="child_view_giftcodes", style="success", icon_custom_emoji_id="4999015678238262018"))
            builder.add(types.InlineKeyboardButton(text=" Back To Main Panel", callback_data="child_back_to_admin", style="danger", icon_custom_emoji_id="6309851100115640076"))
            
            builder.adjust(1)
            
            await state.set_state(GiftCodeSetup.waiting_for_gift_input)
            await callback_query.message.edit_text(text=dashboard_text, parse_mode="HTML", reply_markup=builder.as_markup())
            await callback_query.answer()

        @cloned_dp.message(GiftCodeSetup.waiting_for_gift_input)
        async def process_gift_input(message: types.Message, state: FSMContext):
            import random, string
            parts = message.text.split("-")
            if len(parts) != 3:
                await message.answer("❌ <b>Invalid Format! Please send: Amount-Users-Refers (e.g. 10-3-4)</b>", parse_mode="HTML")
                return

            # Destructure raw values cleanly
            try:
                amt = float(parts[0])
                users = int(parts[1])
                refs = int(parts[2])
            except ValueError:
                await message.answer("❌ <b>Numerical Error! Check that values are valid numbers.</b>", parse_mode="HTML")
                return

            # Extract raw Telegram API identifier context for this sub-instance clone
            bot_id = message.bot.id
            
            # Generate unique 12-character alphanumeric code
            characters = string.ascii_uppercase + string.digits
            gift_code = ''.join(random.choices(characters, k=12))
            
            async with aiosqlite.connect("bot_factory.db") as db:
                # Count current active codes specifically generated within this isolated clone instance
                async with db.execute(
                    "SELECT COUNT(*) FROM gift_codes WHERE bot_id = ? AND status = 'Active'", 
                    (bot_id,)
                ) as cursor:
                    count = await cursor.fetchone()
                    if count and count[0] >= 3:
                        await message.answer("❌ <b>Limit Reached! You can only have 3 active gift codes.</b>", parse_mode="HTML")
                        return

                # Map configuration values into your proper schema properties
                await db.execute(
                    """INSERT INTO gift_codes (bot_id, code, amount, req_referrals, max_uses, current_uses, status) 
                       VALUES (?, ?, ?, ?, ?, 0, 'Active')""", 
                    (bot_id, gift_code, amt, refs, users)
                )
                await db.commit()
            
            success_text = (
                f"<b><tg-emoji emoji-id='5442939099906325301'>🎁</tg-emoji> Gift Code Created!</b>\n\n"
                f"<b><tg-emoji emoji-id='4942888689131848546'>👥</tg-emoji> Total User: {users}</b>\n"
                f"<b><tg-emoji emoji-id='5375296873982604963'>💰</tg-emoji> Amount Per User : ₹{amt:.2f}</b>\n"
                f"<b><tg-emoji emoji-id='4996755833950831347'>🎉</tg-emoji> Gift Code: <code>{gift_code}</code></b>\n"
                f"<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> Required Refer: {refs}</b>\n\n"
                f"<b><tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji> Don't Miss Your Golden Chance To Claim This Code!</b>"
            )
            
            await message.answer(text=success_text, parse_mode="HTML")
            await state.clear()


        @cloned_dp.callback_query(F.data == "child_view_giftcodes")
        async def view_active_giftcodes(callback_query: types.CallbackQuery):
            bot_id = callback_query.bot.id
            
            async with aiosqlite.connect("bot_factory.db") as db:
                # Fetching code properties filtered by current clone token instance context
                async with db.execute(
                    """SELECT code, amount, max_uses, current_uses 
                       FROM gift_codes 
                       WHERE (bot_id = ? OR bot_id = 0) AND status = 'Active'""", 
                    (bot_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
            
            if not rows:
                return await callback_query.answer("❌ No active codes found for this bot instance.", show_alert=True)
            
            # Formatting line structures to explicitly reveal user capacities (e.g., [For 50 Users])
            lines = []
            for i, (code, amt, max_u, curr_u) in enumerate(rows, 1):
                lines.append(f"{i}) <code>{code}</code> [<b> {max_u} </b>] [<b>₹{amt}</b>]")
            
            text = (
                f"<b><tg-emoji emoji-id='5442939099906325301'>🎁</tg-emoji> Active Gift Codes!</b>\n\n"
                f"{chr(10).join(lines)}\n\n"
                f"<b><tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji> Enjoy Your Gift Codes!...</b>"
            )
            
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text=" Back To Panel", 
                callback_data="child_adm_giftcodes",
                style="primary", 
                icon_custom_emoji_id="6309851100115640076"
            ))
            
            await callback_query.message.edit_text(text=text, parse_mode="HTML", reply_markup=builder.as_markup())


        # -----------------------------------------------------------------
        # Select Gift Code for Wager
        # -----------------------------------------------------------------

        @cloned_dp.callback_query(F.data == "child_set_wager")
        async def select_gift_code_for_wager(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT code FROM gift_codes") as cursor:
                    rows = await cursor.fetchall()
            
            if not rows:
                return await callback_query.answer("❌ No active gift codes found to set a wager.", show_alert=True)
            
            builder = InlineKeyboardBuilder()
            
            # Create a button for each active gift code
            for row in rows:
                code = row[0]
                builder.add(types.InlineKeyboardButton(
                    text=f"{code}", 
                    callback_data=f"wager_code_{code}", 
                    style="primary", 
                    icon_custom_emoji_id="4996755833950831347"
                ))
            
            # Back Button
            builder.add(types.InlineKeyboardButton(
                text=" Back", 
                callback_data="child_adm_giftcodes", 
                style="danger", 
                icon_custom_emoji_id="6309851100115640076"
            ))
            
            builder.adjust(1)
            
            text = "<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> Select A Gift Code To Set Wager!</b>"
            await callback_query.message.edit_text(text=text, parse_mode="HTML", reply_markup=builder.as_markup())


        # -----------------------------------------------------------------
        # Handler for when a code is selected
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data.startswith("wager_code_"))
        async def handle_wager_selection(callback_query: types.CallbackQuery, state: FSMContext):
            code = callback_query.data.split("_")[2]
            # Store the selected code in state to use later
            await state.update_data(selected_code=code)
            await state.set_state(GiftCodeSetup.waiting_for_wager_input)
            
            text = (
                f"<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> You Selected: <code>{code}</code></b>\n\n"
                f"<b><tg-emoji emoji-id='5442939099906325301'>🎁</tg-emoji> Provide The Wager (Required Refers)!</b>"
            )
            await callback_query.message.edit_text(text=text, parse_mode="HTML")

        @cloned_dp.message(GiftCodeSetup.waiting_for_wager_input)
        async def process_wager_input(message: types.Message, state: FSMContext):
            wager_refers = message.text
            data = await state.get_data()
            code = data.get("selected_code")
            
            # Save the new wager requirement to your gift_codes database
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE gift_codes SET refers = ? WHERE code = ?", (wager_refers, code))
                await db.commit()
            
            success_text = (
                f"<b><tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji> Wager Refer Set To: <code>{wager_refers}</code> Refers!</b>"
            )
            
            await message.answer(text=success_text, parse_mode="HTML")
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Bot Admin: Dynamic Broadcast Hub Engine
        # -----------------------------------------------------------------

        # 1. Capture the "Broadcast" button click from the Clone Admin Panel
        @cloned_dp.callback_query(F.data == "child_adm_broadcast")
        async def process_child_broadcast_trigger(callback_query: types.CallbackQuery, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can execute a broadcast.", show_alert=True)
                return

            ask_broadcast_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Write Your Broadcast Message</b>\n\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> Send the message you want to broadcast.\n\n'
                f'<tg-emoji emoji-id="5375152498656961898">🎀</tg-emoji> <b>Supported Formatting</b>\n'
                f'• Bold\n• Italic\n• <u>Underline</u>\n• <s>Strikethrough</s>\n'
                f'• <tg-emoji emoji-id="6309997365226903510">🔗</tg-emoji> Text Links\n• <tg-spoiler>Spoilers</tg-spoiler>\n'
                f'• <code>Monospace</code>\n• <blockquote>Block Quotes</blockquote>\n\n'
                f'<tg-emoji emoji-id="5251203410396458957">🛡️</tg-emoji> <b>Supported Media</b>\n'
                f'• Photos\n• Videos\n• Animations (GIFs)\n• Audio\n• Voice Messages\n• Documents\n• Text\n\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n'
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji> Your message will be delivered to all users of the selected bot.'
            )

            cancel_builder = InlineKeyboardBuilder()
            cancel_builder.add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))

            await state.set_state(ClonedBotBroadcastFlow.waiting_for_broadcast_content)
            await callback_query.message.edit_text(text=ask_broadcast_text, parse_mode="HTML", reply_markup=cancel_builder.as_markup(), disable_web_page_preview=True)
            await callback_query.answer()

        # 2. Capture and store the content payload (Supports all media types natively)
        @cloned_dp.message(ClonedBotBroadcastFlow.waiting_for_broadcast_content)
        async def process_broadcast_content_input(message: types.Message, state: FSMContext):
            # Save message properties copy into FSM state
            await state.update_data(
                content_type=message.content_type,
                text=message.html_text if message.text else (message.caption_html if message.caption else None),
                file_id=message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else (message.animation.file_id if message.animation else (message.audio.file_id if message.audio else (message.voice.file_id if message.voice else (message.document.file_id if message.document else None))))),
                reply_markup=message.reply_markup.model_dump() if message.reply_markup else None
            )

            confirm_builder = InlineKeyboardBuilder()
            confirm_builder.add(types.InlineKeyboardButton(
                text="Confirm", 
                callback_data="child_bc_confirm_execute",
                icon_custom_emoji_id="6267008582294705964"
            ))
            confirm_builder.add(types.InlineKeyboardButton(text="❌ Cancel", callback_data="child_back_to_admin"))
            confirm_builder.adjust(1)

            await state.set_state(ClonedBotBroadcastFlow.waiting_for_broadcast_confirm)
            await message.answer("<b>⚠️ Do you want to confirm and send this broadcast to all users?</b>", parse_mode="HTML", reply_markup=confirm_builder.as_markup())

        # 3. High-speed parallel dispatch execution sequence
        @cloned_dp.callback_query(F.data == "child_bc_confirm_execute", StateFilter(ClonedBotBroadcastFlow.waiting_for_broadcast_confirm))
        async def execute_cloned_parallel_broadcast(callback_query: types.CallbackQuery, state: FSMContext):
            import time
            raw_bot_token_id = callback_query.bot.id
            
            # Fetch target users linked exclusively to this specific clone instance
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT DISTINCT user_id FROM user_balances WHERE bot_id = ?", (raw_bot_token_id,)) as cursor:
                    user_rows = await cursor.fetchall()
            
            target_user_ids = [row[0] for row in user_rows]
            
            if not target_user_ids:
                await callback_query.answer("❌ There are no active users in this bot to broadcast to.", show_alert=True)
                await state.clear()
                return

            bc_data = await state.get_data()
            await state.clear()

            # UI Update placeholder status
            await callback_query.message.edit_text("⚡ <b>Sending Broadcast at Maximum Speed...</b>", parse_mode="HTML")
            
            start_time = time.time()
            delivered_count, failed_count = 0, 0

            # Atomic task wrapper isolating errors completely (Blocks "faltu" exception trace logs)
            async def send_atomic_payload(target_chat_id: int):
                nonlocal delivered_count, failed_count
                try:
                    c_type = bc_data.get("content_type")
                    text_val = bc_data.get("text")
                    f_id = bc_data.get("file_id")
                    inline_markup = types.InlineKeyboardMarkup.model_validate(bc_data.get("reply_markup")) if bc_data.get("reply_markup") else None

                    if c_type == "text":
                        await callback_query.bot.send_message(chat_id=target_chat_id, text=text_val, parse_mode="HTML", reply_markup=inline_markup, disable_web_page_preview=True)
                    elif c_type == "photo":
                        await callback_query.bot.send_photo(chat_id=target_chat_id, photo=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    elif c_type == "video":
                        await callback_query.bot.send_video(chat_id=target_chat_id, video=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    elif c_type == "animation":
                        await callback_query.bot.send_animation(chat_id=target_chat_id, animation=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    elif c_type == "audio":
                        await callback_query.bot.send_audio(chat_id=target_chat_id, audio=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    elif c_type == "voice":
                        await callback_query.bot.send_voice(chat_id=target_chat_id, voice=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    elif c_type == "document":
                        await callback_query.bot.send_document(chat_id=target_chat_id, document=f_id, caption=text_val, parse_mode="HTML", reply_markup=inline_markup)
                    delivered_count += 1
                except Exception:
                    # Clean intercept: Catches stops, blocks, and dead chats silently without logging or crashing
                    failed_count += 1

            # Execute all tasks simultaneously across parallel corridors
            await asyncio.gather(*[send_atomic_payload(uid) for uid in target_user_ids])
            
            end_time = time.time()
            elapsed_seconds = end_time - start_time
            
            # Formulate human-readable runtime string
            if elapsed_seconds < 1.0:
                elapsed_string = f"{int(elapsed_seconds * 1000)} ms"
            else:
                elapsed_string = f"{elapsed_seconds:.2f} s"

            report_summary_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Broadcast Sent Successfully!</b>\n\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n\n'
                f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> Your message has been broadcast successfully.\n\n'
                f'<tg-emoji emoji-id="5375152498656961898">🎀</tg-emoji>Delivered: <b>{delivered_count}</b> users\n'
                f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> Failed: <b>{failed_count}</b> users\n'
                f'<tg-emoji emoji-id="5017179932451668652">🕖</tg-emoji> Completed In: <b>{elapsed_string}</b>\n\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n'
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji> Broadcast process finished successfully.'
            )

            back_to_menu_builder = InlineKeyboardBuilder()
            back_to_menu_builder.add(types.InlineKeyboardButton(text="🔙 Back To Console", callback_data="child_back_to_admin"))

            await callback_query.message.delete()
            await callback_query.message.answer(text=report_summary_text, parse_mode="HTML", reply_markup=back_to_menu_builder.as_markup())
            await callback_query.answer()


        # -----------------------------------------------------------------
        # 1. Withdrawal Cooldown System Configuration
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "wd_set_cooldown")
        async def prompt_withdrawal_cooldown(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT cooldown FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            current_cooldown = row[0] if row and row[0] else "off"
            ask_text = (
                f'<tg-emoji emoji-id="5472030678633684592">💸</tg-emoji> <b>Provide The Withdraw Cooldown Using The Format Below.</b>\n\n'
                f"<b>📖 Examples:</b>\n"
                f'• <tg-emoji emoji-id="5017179932451668652">🕒</tg-emoji> <b>30 sec</b>\n'
                f'• <tg-emoji emoji-id="5017179932451668652">🕒</tg-emoji> <b>30 minutes</b>\n'
                f'• <tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji> <b>1 hour</b>\n'
                f'• <tg-emoji emoji-id="5274055917766202507">📅</tg-emoji> <b>1 day</b>\n'
                f'• <tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <b>off</b>\n\n'
                f"<b>⚙️ Current: {current_cooldown}</b>"
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_withdraws"))
            await state.set_state(ChildCooldownSetup.waiting_for_cooldown_input)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        @cloned_dp.message(ChildCooldownSetup.waiting_for_cooldown_input)
        async def process_cooldown_input(message: types.Message, state: FSMContext):
            raw_input = message.text.strip().lower() if message.text else ""
            input_text = raw_input.split("=")[0].strip()
            is_valid, normalized_value = False, ""

            if input_text == "off":
                is_valid, normalized_value = True, "off"
            else:
                if (m := re.match(r"^(\d+)\s*(sec|seconds?)$", input_text)) and 1 <= int(m.group(1)) <= 59:
                    is_valid, normalized_value = True, f"{m.group(1)} sec"
                elif (m := re.match(r"^(\d+)\s*(min|minutes?)$", input_text)) and 1 <= int(m.group(1)) <= 59:
                    is_valid, normalized_value = True, f"{m.group(1)} minutes"
                elif (m := re.match(r"^(\d+)\s*(hour|hr|hours?)$", input_text)) and 1 <= int(m.group(1)) <= 23:
                    val = m.group(1)
                    is_valid, normalized_value = True, f"{val} hour" if val == "1" else f"{val} Hours"
                elif (m := re.match(r"^(\d+)\s*(day|days?)$", input_text)) and 1 <= int(m.group(1)) <= 7:
                    val = m.group(1)
                    is_valid, normalized_value = True, f"{val} day" if val == "1" else f"{val} days"

            if not is_valid:
                await message.answer("❌ <b>Invalid Format!</b>", parse_mode="HTML")
                return

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET cooldown = ? WHERE bot_id = ?", (normalized_value, db_bot_id))
                await db.commit()
            
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="child_adm_withdraws"))
            await message.answer(text=f"✅ <b>Set To: {normalized_value}</b>", parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # 2. Dynamic Bonus Dashboard
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "child_adm_daily")
        async def display_bonus_dashboard(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT bonus_amount, bonus_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            b_amt, b_mode = (row[0], row[1]) if row else ("1", "Normal")
            dashboard_text = f"🎁 <b>BONUS DASHBOARD</b>\n├ Amount: ₹{b_amt}\n└ Mode: {b_mode}\n\n➡️ Send: <b>Integer</b>, <b>Range (1-6)</b>, or <b>🎲</b>"
            
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="child_back_to_admin"))
            await state.set_state(ChildBonusSetup.waiting_for_bonus_input)
            await callback_query.message.edit_text(text=dashboard_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await callback_query.answer()

        @cloned_dp.message(ChildBonusSetup.waiting_for_bonus_input)
        async def process_bonus_input_selection(message: types.Message, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            if not row or message.from_user.id != row[0]:
                return await message.answer("❌ <b>Unauthorized.</b>", parse_mode="HTML")

            input_text = message.text.strip() if message.text else ""
            if (message.dice and message.dice.emoji == "🎲") or input_text == "🎲":
                final_amt, final_mode = "1-6", "Dice Bonus"
            elif "-" in input_text:
                final_amt, final_mode = input_text, "Random Amount"
            else:
                try:
                    final_amt, final_mode = str(int(input_text.replace("₹", ""))), "Normal (Fixed Amount)"
                except:
                    return await message.answer("❌ <b>Invalid Format.</b>", parse_mode="HTML")

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET bonus_amount = ?, bonus_mode = ? WHERE bot_id = ?", (final_amt, final_mode, db_bot_id))
                await db.commit()
            await message.answer(f"✅ <b>Set to: {final_amt} ({final_mode})</b>", parse_mode="HTML")
            await state.clear()

        # -----------------------------------------------------------------
        # 3. Withdraws & Device Verification
        # -----------------------------------------------------------------


        @cloned_dp.callback_query(F.data == "child_toggle_device_verify")
        async def exec_child_device_verify_toggle(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT device_verification FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            new_v = "Off" if (row[0] if row else "On") == "On" else "On"
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET device_verification = ? WHERE bot_id = ?", (new_v, db_bot_id))
                await db.commit()
            
            await callback_query.message.edit_reply_markup(reply_markup=await build_child_admin_keyboard(db_bot_id))
            await callback_query.answer(f"⚙️ Verification: {new_v}")

        # -----------------------------------------------------------------
        # Cloned Bot Bonus Claim Execution Engine
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "claim_bonus")
        async def process_cloned_bonus_claim(callback_query: types.CallbackQuery):
            import random
            import asyncio
            from datetime import datetime, timedelta

            user_id = callback_query.from_user.id
            # Extract raw Telegram API unique identifier matching the validation engine
            bot_id = callback_query.bot.id
            current_time = datetime.now()
            
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_bonus_cooldowns (
                        user_id INTEGER, bot_id INTEGER, last_claim_time TEXT, PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER, bot_id INTEGER, balance REAL DEFAULT 0.0, PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()
                
                async with db.execute(
                    "SELECT last_claim_time FROM user_bonus_cooldowns WHERE user_id = ? AND bot_id = ?", 
                    (user_id, bot_id)
                ) as cursor:
                    cooldown_row = await cursor.fetchone()
            
            # 24-hour cooldown logic calculation matching your layout style parameters
            if cooldown_row and cooldown_row[0]:
                last_claim = datetime.fromisoformat(cooldown_row[0])
                time_passed = current_time - last_claim
                cooldown_duration = timedelta(days=1)
                
                if time_passed < cooldown_duration:
                    time_remaining = cooldown_duration - time_passed
                    total_seconds = int(time_remaining.total_seconds())
                    
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    seconds = total_seconds % 60
                    
                    await callback_query.message.answer(
                        f'<tg-emoji emoji-id="5251203410396458957">🛡️</tg-emoji> <b>You Have Already Claimed Your Bonus For Today!!\n\n'
                        f'Try Again After {hours}H {minutes}m & {seconds}s</b>', 
                        parse_mode="HTML"
                    )
                    await callback_query.answer()
                    return

            # Fetch Bonus Settings using inner operational primary keys
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT bonus_amount, bonus_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    setting_row = await cursor.fetchone()
            
            b_amt = setting_row[0] if setting_row else "1"
            b_mode = setting_row[1] if setting_row else "Normal (Fixed Amount)"
            
            bonus_reward = 1.0

            # Logic Engine
            if "Dice" in b_mode:
                dice_msg = await callback_query.message.answer_dice(emoji="🎲")
                await asyncio.sleep(3.5)
                bonus_reward = float(dice_msg.dice.value)
            elif "Random" in b_mode:
                try:
                    min_val, max_val = map(int, b_amt.split("-"))
                    bonus_reward = float(random.randint(min_val, max_val))
                except:
                    bonus_reward = 1.0
            else:
                try:
                    bonus_reward = float(b_amt.replace("₹", ""))
                except:
                    bonus_reward = 1.0

            # Save to Balance and Cooldown using API identifiers
            async with aiosqlite.connect("bot_factory.db") as db:
                # Get current balance for the instance matching raw API parameters
                async with db.execute("SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", (user_id, bot_id)) as cursor:
                    curr_bal = await cursor.fetchone()
                    new_bal = (curr_bal[0] if curr_bal else 0.0) + bonus_reward
                
                await db.execute(
                    "INSERT OR REPLACE INTO user_balances (user_id, bot_id, balance) VALUES (?, ?, ?)", 
                    (user_id, bot_id, new_bal)
                )
                await db.execute(
                    "INSERT OR REPLACE INTO user_bonus_cooldowns (user_id, bot_id, last_claim_time) VALUES (?, ?, ?)", 
                    (user_id, bot_id, current_time.isoformat())
                )
                await db.commit()

            await callback_query.message.answer(
                f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> <b>Bonus Of ₹{bonus_reward:.2f} Claimed Successfully!</b>', 
                parse_mode="HTML"
            )
            await callback_query.answer()



        # -----------------------------------------------------------------
        # Cloned Bot Manage Withdraws Dashboard Handler
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "child_adm_withdraws")
        async def process_child_withdraws_dashboard(callback_query: types.CallbackQuery):
            builder = InlineKeyboardBuilder()
            
            # Row 1: Min & Max Withdraw
            builder.add(types.InlineKeyboardButton(
                text="  Set Minimum Withdraw", 
                callback_data="child_wd_set_min",
                style="primary",
                icon_custom_emoji_id="6068806600477383919"
            ))
            builder.add(types.InlineKeyboardButton(
                text="  Set Maximum Withdraw", 
                callback_data="child_wd_set_max",
                style="primary",
                icon_custom_emoji_id="6267008582294705964"
            ))
            
            # Row 2: Refer & Cooldown
            builder.add(types.InlineKeyboardButton(
                text="  Set Required Refer", 
                callback_data="child_wd_set_refers",
                style="primary",
                icon_custom_emoji_id="5375152498656961898"
            ))
            builder.add(types.InlineKeyboardButton(
                text="  Set Cooldown", 
                callback_data="wd_set_cooldown",
                style="primary",
                icon_custom_emoji_id="5350722806281676158"
            ))
            
            # Row 3: Back Button
            builder.add(types.InlineKeyboardButton(
                text=" Back To Main Panel", 
                callback_data="child_back_to_admin",
                style="danger", 
                icon_custom_emoji_id="6309851100115640076"
            ))
            
            builder.adjust(2, 2, 1)
            
            await callback_query.message.edit_text(
                text='<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> <b>Select An Option To Manage Withdrawals</b>', 
                parse_mode="HTML", 
                reply_markup=builder.as_markup()
            )
            await callback_query.answer()

        # -----------------------------------------------------------------
        # 1. Callback Query Handler (Using Cloned Dispatcher Pipeline)
        # -----------------------------------------------------------------

        @cloned_dp.callback_query(F.data == "claim_gift_code")
        async def process_claim_gift_code(callback_query: types.CallbackQuery, state: FSMContext):
            # Safe dynamic retrieval of the current running clone's unique ID
            bot_id = callback_query.bot.id

            # Check if at least one active gift code exists for THIS clone bot OR has a default ID of 0
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    """SELECT COUNT(*) FROM gift_codes 
                       WHERE (bot_id = ? OR bot_id = 0) 
                       AND status = 'Active' 
                       AND max_uses > current_uses""",
                    (bot_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    available_codes = row[0] if row else 0

            if available_codes == 0:
                await callback_query.answer()
                await callback_query.message.answer(
                    "<b><tg-emoji emoji-id='6309648704076782071'>🚫</tg-emoji> No Gift Code Available At This Moment!</b>", 
                    parse_mode="HTML"
                )
                return

            # Store the clone's verified context ID inside FSM tracking storage
            await state.update_data(current_clone_db_id=bot_id)

            # Construct custom standard panel keyboard
            builder = ReplyKeyboardBuilder()
            builder.button(text="Back To Panel", style="danger", icon_custom_emoji_id="6309851100115640076")
            
            await state.set_state(GiftCodeForm.waiting_for_code)
            await callback_query.answer()
            await callback_query.message.answer(
                "<b><tg-emoji emoji-id='6300651726844204536'>✨</tg-emoji> Send Gift Code To Claim Reward!</b>", 
                parse_mode="HTML",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )

        # -----------------------------------------------------------------
        # 2. Input Validation Handler (Using Cloned Dispatcher Pipeline)
        # -----------------------------------------------------------------

        @cloned_dp.message(GiftCodeForm.waiting_for_code)
        async def validate_and_claim_code(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            provided_code = message.text.strip()
            
            # Pull tracking identifier from storage or resolve via runtime message context
            state_data = await state.get_data()
            bot_id = state_data.get("current_clone_db_id") or message.bot.id

            if provided_code == "Back To Panel":
                await state.clear()
                await message.answer("<b>Returned to panel.</b>", reply_markup=get_clone_main_menu_keyboard())
                return

            async with aiosqlite.connect(DB_NAME) as db:
                # 1. Fetch exact explicit positions to fully bypass row_factory dictionary naming issues
                async with db.execute(
                    """SELECT id, bot_id, code, amount, req_referrals, max_uses, current_uses, status 
                       FROM gift_codes 
                       WHERE (bot_id = ? OR bot_id = 0) AND code = ? AND status = 'Active'""", 
                    (bot_id, provided_code)
                ) as cursor:
                    code_data = await cursor.fetchone()

                if not code_data:
                    await message.answer("<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> Invalid Gift Code...!</b>", parse_mode="HTML")
                    return

                # Map database values securely by structural index positions
                gift_db_id      = code_data[0]
                reward_amount   = code_data[3]
                required_refers = code_data[4]
                max_uses        = code_data[5]
                current_uses    = code_data[6]

                # 2. Check if already claimed by this specific user on this specific clone
                async with db.execute(
                    "SELECT COUNT(*) FROM claimed_gift_codes WHERE user_id = ? AND bot_id = ? AND code_id = ?", 
                    (user_id, bot_id, gift_db_id)
                ) as check_cursor:
                    already_claimed = (await check_cursor.fetchone())[0]

                if already_claimed > 0:
                    await message.answer("<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> You have already claimed this gift code!</b>", parse_mode="HTML")
                    return

                # 3. Check usage limit
                if current_uses >= max_uses:
                    await message.answer("<b><tg-emoji emoji-id='6309648704076782071'>🚫</tg-emoji> This gift code has expired or reached its maximum limit!</b>", parse_mode="HTML")
                    return

                # 4. Verify verified refers using your user_verification matrix for this bot
                async with db.execute(
                    """SELECT COUNT(*) FROM user_verification 
                       WHERE bot_id = ? AND seen = 1 
                       AND user_id IN (SELECT referred_id FROM user_referrals WHERE referrer_id = ? AND bot_id = ?)""",
                    (bot_id, user_id, bot_id)
                ) as ref_cursor:
                    verified_refers = (await ref_cursor.fetchone())[0]

                if verified_refers < required_refers:
                    await message.answer(
                        f"<b><tg-emoji emoji-id='5251203410396458957'>🛡️</tg-emoji> You Need {required_refers} Verified Refers To Claim This Code!</b>", 
                        parse_mode="HTML"
                    )
                    return

                # 5. Execute Payout Transaction
                # Update user balance within this specific clone bot's balance domain
                await db.execute(
                    "INSERT INTO user_balances (user_id, bot_id, balance) VALUES (?, ?, ?) ON CONFLICT(user_id, bot_id) DO UPDATE SET balance = balance + ?",
                    (user_id, bot_id, reward_amount, reward_amount)
                )
                
                # Log transaction footprint mapping
                await db.execute("INSERT INTO claimed_gift_codes (user_id, bot_id, code_id) VALUES (?, ?, ?)", (user_id, bot_id, gift_db_id))
                # Increment usage tracker
                await db.execute("UPDATE gift_codes SET current_uses = current_uses + 1 WHERE id = ?", (gift_db_id,))
                await db.commit()

            # 6. Success Response
            success_img = "https://ganga--link--ghhzdp9sv8hk.code.run/i/czaehzl5.jpg"
            success_caption = f"<b><tg-emoji emoji-id='5442939099906325301'>🎉</tg-emoji> Congratulations! You Have Successfully Claimed The Gift Code Of ₹{reward_amount}</b>"
            
            await message.answer_photo(
                photo=success_img, 
                caption=success_caption, 
                parse_mode="HTML", 
                reply_markup=get_clone_main_menu_keyboard()
            )
            await state.clear()

        # F. Real-time Private Link Join Request Tracker
        @cloned_dp.chat_join_request()
        async def handle_cloned_chat_join_request(update: ChatJoinRequest):
            raw_bot_token_id = update.bot.id
            clean_channel_id = str(update.chat.id).strip()
            
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    INSERT OR IGNORE INTO child_join_requests (bot_id, channel_id, user_id, requested_at)
                    VALUES (?, ?, ?, DATETIME('now'))
                """, (raw_bot_token_id, clean_channel_id, update.from_user.id))
                await db.commit()

        # -----------------------------------------------------------------
        # Cloned Bot Admin: User Search & Verification Status Suite
        # -----------------------------------------------------------------

        # 1. Capture the "Verify User" button click from the Admin Console
        @cloned_dp.callback_query(F.data == "child_adm_verify")
        async def prompt_admin_user_verification_search(callback_query: types.CallbackQuery, state: FSMContext):
            # Security guard: Confirm administrative authorization profile context rows first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can view user profiles.", show_alert=True)
                return

            ask_search_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Provide User Chat ID To Verify User!</b>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildUserVerificationSearchSetup.waiting_for_target_user_id)
            await callback_query.message.edit_text(text=ask_search_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Search payload analytical processing engine
        @cloned_dp.message(ChildUserVerificationSearchSetup.waiting_for_target_user_id)
        async def process_admin_user_verification_search_input(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            target_input = message.text.strip() if message.text else ""
            if not target_input.isdigit():
                await message.answer("❌ <b>Invalid Input! Please provide a numeric Telegram Chat ID.</b>", parse_mode="HTML")
                return

            target_search_user_id = int(target_input)
            raw_bot_token_id = message.bot.id

            async with aiosqlite.connect("bot_factory.db") as db:
                # Core Guard: Check if user exists inside our ledger balances for this bot
                async with db.execute(
                    "SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", 
                    (target_search_user_id, raw_bot_token_id)
                ) as cursor:
                    user_started_bot = await cursor.fetchone()

            if not user_started_bot:
                missing_user_text = (
                    f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> '
                    f'<b>No Information Available About This User! The User Haven\'t Started The Bot Yet!</b>'
                )
                back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Return To Panel", callback_data="child_back_to_admin"))
                await message.answer(text=missing_user_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
                await state.clear()
                return

            # Resolve user details dynamically to safely capture formatting targets
            try:
                target_chat_profile = await message.bot.get_chat(chat_id=target_search_user_id)
                user_display_name = target_chat_profile.first_name if target_chat_profile.first_name else "User Profile"
                user_mention_str = f'<a href="tg://user?id={target_search_user_id}">{user_display_name}</a>'
            except Exception:
                user_mention_str = f'<b>User Profile</b>'

            async with aiosqlite.connect("bot_factory.db") as db:
                # A. Verify Device Fingerprint Verification Status via seen bits
                async with db.execute(
                    "SELECT seen FROM user_verification WHERE user_id = ? AND bot_id = ?", 
                    (target_search_user_id, raw_bot_token_id)
                ) as cursor:
                    v_row = await cursor.fetchone()
                device_passed = v_row and v_row[0] == 1
                verify_badge = "🟢 Verification Status: Passed" if device_passed else "🔴 Verification Status: Failed"

                # B. Verify Channel Membership Conditions
                channels_joined = await is_user_member(target_search_user_id)
                channel_badge = "🟢 Joined All Channels: Yes" if channels_joined else "🔴 Joined All Channels: No"

                # C. Compute Referral Traffic Matrices
                async with db.execute("""
                    SELECT COUNT(*) FROM user_referrals r
                    JOIN user_verification v ON r.referred_id = v.user_id AND r.bot_id = v.bot_id
                    WHERE r.referrer_id = ? AND r.bot_id = ? AND v.seen = 1
                """, (target_search_user_id, raw_bot_token_id)) as cursor:
                    verified_ref_count = (await cursor.fetchone())[0]

                async with db.execute("""
                    SELECT COUNT(*) FROM user_referrals r
                    JOIN user_verification v ON r.referred_id = v.user_id AND r.bot_id = v.bot_id
                    WHERE r.referrer_id = ? AND r.bot_id = ? AND v.seen = 0
                """, (target_search_user_id, raw_bot_token_id)) as cursor:
                    unverified_ref_count = (await cursor.fetchone())[0]

                # D. --- FIXED: Hot-patch child_payout_logs structure dynamically to guarantee user_id mapping existence ---
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_payout_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot_id INTEGER,
                        user_id INTEGER,
                        amount REAL,
                        status TEXT
                    )
                """)
                await db.commit()

                async with db.execute("PRAGMA table_info(child_payout_logs)") as col_cursor:
                    log_columns = [r[1] for r in await col_cursor.fetchall()]
                if "user_id" not in log_columns:
                    await db.execute("ALTER TABLE child_payout_logs ADD COLUMN user_id INTEGER")
                    await db.commit()

                async with db.execute("""
                    SELECT SUM(amount) FROM child_payout_logs 
                    WHERE user_id = ? AND bot_id = ? AND status = 'Success'
                """, (target_search_user_id, db_bot_id)) as cursor:
                    payout_row = await cursor.fetchone()
                total_withdrawn = payout_row[0] if payout_row and payout_row[0] is not None else 0.00

            # Synthesize data report purely in HTML bold wrapping with explicit Premium Emojis
            profile_summary_report = (
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji>{user_mention_str} <b>Informations:-</b>\n\n'
                f'{verify_badge}\n'
                f'{channel_badge}\n\n'
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji><b>Total Verified Refers: {verified_ref_count}</b>\n'
                f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji><b>Total Unverified Refers: {unverified_ref_count}</b>\n'
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Total Amount Withdrawn: ₹{total_withdrawn:.2f}</b>'
            )

            back_to_menu_builder = InlineKeyboardBuilder()
            back_to_menu_builder.add(types.InlineKeyboardButton(text="🔙 Back To Console", callback_data="child_back_to_admin"))

            await message.answer(text=profile_summary_report, parse_mode="HTML", reply_markup=back_to_menu_builder.as_markup())
            await state.clear()


        # -----------------------------------------------------------------
        # Dynamic Refer Dashboard & FSM Setup
        # -----------------------------------------------------------------
        
        # 1. Catch button selection from /adminpanel to trigger the Dashboard menu
        @cloned_dp.callback_query(F.data == "child_adm_refer")
        async def display_refer_dashboard(callback_query: types.CallbackQuery, state: FSMContext):
            # Inspect existing database column indexes natively to verify migration structure
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]

                if "refer_amount" not in columns:
                    await db.execute("ALTER TABLE child_bot_settings ADD COLUMN refer_amount TEXT DEFAULT '❎ Nᴏᴛ Sᴇᴛ'")
                    await db.commit()
                if "refer_mode" not in columns:
                    await db.execute("ALTER TABLE child_bot_settings ADD COLUMN refer_mode TEXT DEFAULT ''")
                    await db.commit()

                async with db.execute("SELECT refer_amount, refer_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            r_amt = row[0] if row else "❎ Nᴏᴛ Sᴇᴛ"
            r_mode = row[1] if row and row[1] else "Normal (Fixed Amount)"

            # Constructing Dashboard Text purely in HTML bold wrapping with explicit Custom Premium Emojis
            dashboard_text = (
                f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>REFER MANAGEMENT DASHBOARD</b>\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="5370935802844946281">⚙️</tg-emoji> <b>CURRENT SETTINGS</b>\n'
                f"<b>├ Refer Amount: ₹{r_amt}</b>\n"
                f"<b>└ Active Mode: {r_mode}</b>\n\n"
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>REFER TYPES GUIDE</b>\n'
                f"<b>•Normal: Every user gets the exact fixed amount.</b>\n"
                f"<b>•Random: Users get a random amount.</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"<b>Select an option below to configure your refer system:</b>\n\n"
                f'<tg-emoji emoji-id="6267119710278522544">➡️</tg-emoji> <b>To configure, please reply directly or send the value:</b>\n'
                f"• <b>For Fix Amount Normal: Send any integer (e.g. 5)</b>\n"
                f"• <b>For Random Amount: Send range configuration (e.g. 1-6)</b>"
            )

            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="child_back_to_admin"))
            
            await state.set_state(ChildReferSetup.waiting_for_refer_input)
            await callback_query.message.edit_text(text=dashboard_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await callback_query.answer()

        # 2. Process incoming referral settings input values safely
        @cloned_dp.message(ChildReferSetup.waiting_for_refer_input)
        async def process_refer_input_selection(message: types.Message, state: FSMContext):
            # Verify owner constraint profile paths first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            if not row or message.from_user.id != row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            input_text = message.text.strip() if message.text else ""
            
            # Detect Dynamic Random range setting configurations (e.g., 1-6)
            if "-" in input_text:
                final_amt = input_text
                final_mode = "Random Amount"
                success_text = (
                    f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Random Amount Refer Bonus Activated Successfully!</b> <tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji>\n'
                    f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji> <b>Bonus Amount Set To: ₹{final_amt}</b>'
                )
                
            # Default fallback: Treat any raw standard numerical character input as standard Fixed normal values
            else:
                try:
                    clean_amt = input_text.replace("₹", "")
                    final_amt = str(int(clean_amt))
                    final_mode = "Normal (Fixed Amount)"
                    success_text = (
                        f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Fixed Amount Refer Bonus Activated Successfully!</b> <tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji>\n'
                        f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji> <b>Bonus Amount Set To: ₹{final_amt}</b>'
                    )
                except ValueError:
                    await message.answer("❌ <b>Invalid configuration payload. Send an integer (5) or a range string (1-6).</b>", parse_mode="HTML")
                    return

            # Save properties persistently into the settings database table
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    UPDATE child_bot_settings 
                    SET refer_amount = ?, refer_mode = ? 
                    WHERE bot_id = ?
                """, (final_amt, final_mode, db_bot_id))
                await db.commit()

            await message.answer(text=success_text, parse_mode="HTML")
            await state.clear()
            
            # ✅ FIXED: Passed all 3 missing parameter mappings and unified key function properties explicitly
            text_layout, _ = await get_child_admin_panel_content(db_bot_id, row[0], message.from_user.first_name)
            await message.answer(text=text_layout, parse_mode="HTML", reply_markup=await build_child_admin_keyboard(db_bot_id))

        # -----------------------------------------------------------------
        # Withdrawal Parameter Configuration Suite (FSM System Engines)
        # -----------------------------------------------------------------

        # ==========================================
        # ENGINE A: MINIMUM WITHDRAWAL LIMIT CONFIG
        # ==========================================
        # ✅ FIXED: Target matches callback 'child_wd_set_min' configured on the withdrawal panel layout natively
        @cloned_dp.callback_query(F.data == "child_wd_set_min")
        async def prompt_set_min_withdraw(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT min_withdraw FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            current_min = row[0] if row else 100.0

            ask_text = (
                f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>Current Minimum Withdraw: ₹{current_min:.2f}</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji><b>Provide Minimum Withdraw Amount!</b>'
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_withdraws"))
            await state.set_state(ChildWithdrawalConfigSetup.waiting_for_min_withdraw)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        @cloned_dp.message(ChildWithdrawalConfigSetup.waiting_for_min_withdraw)
        async def process_min_withdraw_input(message: types.Message, state: FSMContext):
            input_text = message.text.strip() if message.text else ""
            try:
                final_val = float(input_text.replace("₹", ""))
                if final_val < 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Only Numeric Values Allowed! Please send a valid amount.</b>", parse_mode="HTML")
                return

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET min_withdraw = ? WHERE bot_id = ?", (final_val, db_bot_id))
                await db.commit()

            success_text = f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Minimum Withdrawal Set To ₹{final_val:.2f}</b>'
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="child_adm_withdraws"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # ==========================================
        # ENGINE B: MAXIMUM WITHDRAWAL LIMIT CONFIG
        # ==========================================
        # ✅ FIXED: Target matches callback 'child_wd_set_max' configured on the withdrawal panel layout natively
        @cloned_dp.callback_query(F.data == "child_wd_set_max")
        async def prompt_set_max_withdraw(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT max_withdraw FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            current_max = row[0] if row else 10000.0

            ask_text = (
                f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>Current Maximum Withdraw: ₹{current_max:.2f}</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji><b>Provide Maximum Withdraw Amount!</b>'
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_withdraws"))
            await state.set_state(ChildWithdrawalConfigSetup.waiting_for_max_withdraw)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        @cloned_dp.message(ChildWithdrawalConfigSetup.waiting_for_max_withdraw)
        async def process_max_withdraw_input(message: types.Message, state: FSMContext):
            input_text = message.text.strip() if message.text else ""
            try:
                final_val = float(input_text.replace("₹", ""))
                if final_val < 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Only Numeric Values Allowed! Please send a valid amount.</b>", parse_mode="HTML")
                return

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET max_withdraw = ? WHERE bot_id = ?", (final_val, db_bot_id))
                await db.commit()

            success_text = f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Maximum Withdrawal Set To ₹{final_val:.2f}</b>'
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="child_adm_withdraws"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # ==========================================
        # ENGINE C: REQUIRED REFERRALS CONFIG
        # ==========================================
        # ✅ FIXED: Target matches callback 'child_wd_set_refers' configured on the withdrawal panel layout natively
        @cloned_dp.callback_query(F.data == "child_wd_set_refers")
        async def prompt_set_req_refers(callback_query: types.CallbackQuery, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT req_referrals FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            current_refers = row[0] if row else 3

            ask_text = (
                f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>Current Required Refers For Withdraw: {current_refers}</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji><b>Provide Required Refers For Withdraw!</b>'
            )
            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_withdraws"))
            await state.set_state(ChildWithdrawalConfigSetup.waiting_for_req_refers)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        @cloned_dp.message(ChildWithdrawalConfigSetup.waiting_for_req_refers)
        async def process_req_refers_input(message: types.Message, state: FSMContext):
            input_text = message.text.strip() if message.text else ""
            try:
                final_val = int(input_text)
                if final_val < 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Only Numeric Values Allowed! Please send a valid number.</b>", parse_mode="HTML")
                return

            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET req_referrals = ? WHERE bot_id = ?", (final_val, db_bot_id))
                await db.commit()

            success_text = f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Required Refers For Withdrawal Set To: {final_val}</b>'
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="child_adm_withdraws"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()



        # -----------------------------------------------------------------
        # Dynamic Gateway Dashboard Matrix Config & FSM Setup
        # -----------------------------------------------------------------

        # Helper function to dynamically construct the 3x2 grid format keyboard mapping states
        async def build_gateway_keyboard():
            async with aiosqlite.connect("bot_factory.db") as db:
                # 1. --- Core Schema Blueprint Mapping (Including digipay_status Directly) ---
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_gateways (
                        bot_id INTEGER PRIMARY KEY,
                        techpay_status TEXT DEFAULT 'Disabled',
                        payzy_status TEXT DEFAULT 'Disabled',
                        digipay_status TEXT DEFAULT 'Disabled'
                    )
                """)
                await db.commit()

                # 2. --- Dynamic Safety Check (Ensures existing tables get the column too) ---
                async with db.execute("PRAGMA table_info(child_gateways)") as cursor:
                    columns = [col_row[1] for col_row in await cursor.fetchall()]
                if "digipay_status" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_status TEXT DEFAULT 'Disabled'")
                    await db.commit()

                # 3. --- Query Extraction Layer ---
                async with db.execute("SELECT techpay_status, payzy_status, digipay_status FROM child_gateways WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
                
                if not row:
                    await db.execute("INSERT INTO child_gateways (bot_id) VALUES (?)", (db_bot_id,))
                    await db.commit()
                    tp_status, pz_status, dg_status = "Disabled", "Disabled", "Disabled"
                else:
                    tp_status, pz_status, dg_status = row

            builder = InlineKeyboardBuilder()

            # --- ROW 1: TechPay Config Bundle (Buttons 1, 2, 3) ---
            builder.add(types.InlineKeyboardButton(text="UltraPay", callback_data="gt_tp_main", style="primary", icon_custom_emoji_id="4999015678238262018"))
            if tp_status == "Disabled":
                builder.add(types.InlineKeyboardButton(text="Disabled", callback_data="gt_toggle_techpay", style="danger", icon_custom_emoji_id="6309648704076782071"))
            else:
                builder.add(types.InlineKeyboardButton(text="Enabled", callback_data="gt_toggle_techpay", style="success", icon_custom_emoji_id="6298317205960397843"))
            builder.add(types.InlineKeyboardButton(text="API Token", callback_data="gt_tp_token", style="success", icon_custom_emoji_id="6267008582294705964"))

            # --- ROW 2: PayZy Config Bundle (Buttons 4, 5, 6) ---
            builder.add(types.InlineKeyboardButton(text="PayZy", callback_data="gt_pz_main", style="primary", icon_custom_emoji_id="4999015678238262018"))
            if pz_status == "Disabled":
                builder.add(types.InlineKeyboardButton(text="Disabled", callback_data="gt_toggle_payzy", style="danger", icon_custom_emoji_id="6309648704076782071"))
            else:
                builder.add(types.InlineKeyboardButton(text="Enabled", callback_data="gt_toggle_payzy", style="success", icon_custom_emoji_id="6298317205960397843"))
            builder.add(types.InlineKeyboardButton(text="API Token", callback_data="gt_pz_token", style="success", icon_custom_emoji_id="6267008582294705964"))

            # --- ROW 3: Digi Pay Config Bundle (Buttons 7, 8, 9) ---
            builder.add(types.InlineKeyboardButton(text="Digi Pay", callback_data="gt_dp_main", style="primary", icon_custom_emoji_id="4999015678238262018"))
            if dg_status == "Disabled":
                builder.add(types.InlineKeyboardButton(text="Disabled", callback_data="gt_toggle_digipay", style="danger", icon_custom_emoji_id="6309648704076782071"))
            else:
                builder.add(types.InlineKeyboardButton(text="Enabled", callback_data="gt_toggle_digipay", style="success", icon_custom_emoji_id="6298317205960397843"))
            builder.add(types.InlineKeyboardButton(text="API Token", callback_data="gt_dp_token", style="success", icon_custom_emoji_id="6267008582294705964"))

            # Bottom Controls: Navigation return row element
            builder.add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="child_back_to_admin"))

            # Adjust into 3 buttons per row, and 1 for the back button at bottom
            builder.adjust(3, 3, 3, 1)
            return builder.as_markup()

        # 1. Main Gateway Setup Handler Trigger Context
        @cloned_dp.callback_query(F.data == "child_adm_gateway")
        async def display_gateway_setup_dashboard(callback_query: types.CallbackQuery):
            gateway_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Integrate Your Bot With Wallet Gateway Setup!</b>\n\n'
                f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji><b>Choose Your Gateway To Continue.</b>'
            )
            
            await callback_query.message.edit_text(
                text=gateway_text, 
                parse_mode="HTML", 
                reply_markup=await build_gateway_keyboard()
            )
            await callback_query.answer()

        # 2. Toggle Engine Route for Gateway 1: TechPay
        @cloned_dp.callback_query(F.data == "gt_toggle_techpay")
        async def process_toggle_techpay(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT techpay_status FROM child_gateways WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
                
                current_state = row[0] if row else "Disabled"
                next_state = "Enabled" if current_state == "Disabled" else "Disabled"
                
                await db.execute("UPDATE child_gateways SET techpay_status = ? WHERE bot_id = ?", (next_state, db_bot_id))
                await db.commit()

            await callback_query.message.edit_reply_markup(reply_markup=await build_gateway_keyboard())
            await callback_query.answer(f"TechPay state turned to {next_state}!")

        # 3. Toggle Engine Route for Gateway 2: PayZy
        @cloned_dp.callback_query(F.data == "gt_toggle_payzy")
        async def process_toggle_payzy(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT payzy_status FROM child_gateways WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
                
                current_state = row[0] if row else "Disabled"
                next_state = "Enabled" if current_state == "Disabled" else "Disabled"
                
                await db.execute("UPDATE child_gateways SET payzy_status = ? WHERE bot_id = ?", (next_state, db_bot_id))
                await db.commit()

            await callback_query.message.edit_reply_markup(reply_markup=await build_gateway_keyboard())
            await callback_query.answer(f"PayZy state turned to {next_state}!")
        
        # -----------------------------------------------------------------
        # 3. Withdraws & Device Verification / Payouts Mode Toggle Engine
        # -----------------------------------------------------------------

        @cloned_dp.callback_query(F.data == "child_toggle_device_verify")
        async def exec_child_device_verify_toggle(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT device_verification FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            new_v = "Off" if (row[0] if row else "On") == "On" else "On"
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET device_verification = ? WHERE bot_id = ?", (new_v, db_bot_id))
                await db.commit()
            
            await callback_query.message.edit_reply_markup(reply_markup=await build_child_admin_keyboard(db_bot_id))
            await callback_query.answer(f"⚙️ Verification: {new_v}")


        @cloned_dp.callback_query(F.data == "child_adm_payout_toggle")
        async def exec_child_payout_mode_toggle(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT payout_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            new_p = "OFF" if (row[0] if row else "AUTO") == "AUTO" else "AUTO"
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("UPDATE child_bot_settings SET payout_mode = ? WHERE bot_id = ?", (new_p, db_bot_id))
                await db.commit()
            
            await callback_query.message.edit_reply_markup(reply_markup=await build_child_admin_keyboard(db_bot_id))
            await callback_query.answer(f"⚙️ Payouts: {'Active' if new_p == 'AUTO' else 'OFF'}")
        # -----------------------------------------------------------------
        # Toggle Engine Route for Gateway 3: Digi Pay
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "gt_toggle_digipay")
        async def process_toggle_digipay(callback_query: types.CallbackQuery):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT digipay_status FROM child_gateways WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
                
                current_state = row[0] if row else "Disabled"
                next_state = "Enabled" if current_state == "Disabled" else "Disabled"
                
                await db.execute("UPDATE child_gateways SET digipay_status = ? WHERE bot_id = ?", (next_state, db_bot_id))
                await db.commit()

            await callback_query.message.edit_reply_markup(reply_markup=await build_gateway_keyboard())
            await callback_query.answer(f"DigiPay state turned to {next_state}!")

        # -----------------------------------------------------------------
        # UltraPay API Credential Panel Configuration Engine (With API URL Auto-Log)
        # -----------------------------------------------------------------
        
        # Helper function to auto-verify active database table layout integrity
        async def verify_ultrapay_schema():
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("PRAGMA table_info(child_gateways)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                
                if "ultrapay_token" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN ultrapay_token TEXT DEFAULT 'None'")
                if "ultrapay_key" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN ultrapay_key TEXT DEFAULT 'None'")
                if "ultrapay_base_url" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN ultrapay_base_url TEXT DEFAULT 'None'")
                await db.commit()

        # 1. Triggered when clicking "API Token" under UltraPay -> Displays Options Menu
        @cloned_dp.callback_query(F.data == "gt_tp_token")
        async def display_ultrapay_cred_options(callback_query: types.CallbackQuery):
            await verify_ultrapay_schema()

            selection_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Configure UltraPay Gateway Credentials!</b>\n\n'
                f'<b>Select which credential component you wish to set up below.</b>'
            )
            
            builder = InlineKeyboardBuilder()
            # ✅ FIXED: Stripped banned style and custom icon arguments from all inline elements
            builder.add(types.InlineKeyboardButton(text="🔑 Set API Token", callback_data="gt_up_set_token"))
            builder.add(types.InlineKeyboardButton(text="🔐 Set API Key", callback_data="gt_up_set_key"))
            builder.add(types.InlineKeyboardButton(text="⬅️ Back", callback_data="child_adm_gateway"))
            
            builder.adjust(2, 1)
            await callback_query.message.edit_text(text=selection_text, parse_mode="HTML", reply_markup=builder.as_markup())
            await callback_query.answer()

        # 2. Handler to prompt for API Token
        @cloned_dp.callback_query(F.data == "gt_up_set_token")
        async def ask_ultrapay_token(callback_query: types.CallbackQuery, state: FSMContext):
            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Provide UltraPay Wallet API Token!</b>'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="gt_tp_token"))
            await state.set_state(ChildGatewaySetup.waiting_for_ultrapay_token)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await callback_query.answer()

        # 3. Handler to save API Token and set Base URL path
        @cloned_dp.message(ChildGatewaySetup.waiting_for_ultrapay_token)
        async def save_ultrapay_token(message: types.Message, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            if not row or message.from_user.id != row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            token_input = message.text.strip()
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    UPDATE child_gateways 
                    SET ultrapay_token = ?, ultrapay_base_url = 'https://ultra-pay.store/APIs/api' 
                    WHERE bot_id = ?
                """, (token_input, db_bot_id))
                await db.commit()
                
            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>UltraPay Wallet API Token Set To :- {token_input}</b>'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="gt_tp_token"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # 4. Handler to prompt for API Key
        @cloned_dp.callback_query(F.data == "gt_up_set_key")
        async def ask_ultrapay_key(callback_query: types.CallbackQuery, state: FSMContext):
            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Provide UltraPay Wallet API Key!</b>'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="gt_tp_token"))
            await state.set_state(ChildGatewaySetup.waiting_for_ultrapay_key)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await callback_query.answer()

        # 5. Handler to save API Key and set Base URL path
        @cloned_dp.message(ChildGatewaySetup.waiting_for_ultrapay_key)
        async def save_ultrapay_key(message: types.Message, state: FSMContext):
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            if not row or message.from_user.id != row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            key_input = message.text.strip()
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    UPDATE child_gateways 
                    SET ultrapay_key = ?, ultrapay_base_url = 'https://ultra-pay.store/APIs/api' 
                    WHERE bot_id = ?
                """, (key_input, db_bot_id))
                await db.commit()
                
            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>UltraPay Wallet API Key Set To :- {key_input}</b>'
            )
            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="gt_tp_token"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()


        # -----------------------------------------------------------------
        # PayZy API Token Configuration Engine (With API URL Auto-Log)
        # -----------------------------------------------------------------

        # 1. Triggered when the Admin clicks "API Token" under PayZy (gt_pz_token)
        @cloned_dp.callback_query(F.data == "gt_pz_token")
        async def ask_payzy_token(callback_query: types.CallbackQuery, state: FSMContext):
            # Ensure proper table structure layout updates are consistently present
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("PRAGMA table_info(child_gateways)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                
                if "payzy_token" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN payzy_token TEXT DEFAULT 'None'")
                if "payzy_base_url" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN payzy_base_url TEXT DEFAULT 'None'")
                await db.commit()

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Provide PayZy Wallet API Token!</b>'
            )
            
            # Add a cancel button to return to the gateway panel safely
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_gateway"))
            
            await state.set_state(ChildGatewaySetup.waiting_for_payzy_token)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await callback_query.answer()

        # 2. Triggered when the Admin sends the PayZy token text entry into chat
        @cloned_dp.message(ChildGatewaySetup.waiting_for_payzy_token)
        async def save_payzy_token(message: types.Message, state: FSMContext):
            # Verify owner constraint profile paths first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            if not row or message.from_user.id != row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            token_input = message.text.strip()
            
            # Securely save the token text and log the full target base URL for dynamic link extraction
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    UPDATE child_gateways 
                    SET payzy_token = ?, payzy_base_url = 'https://payzy-gateway.site/api/transfer' 
                    WHERE bot_id = ?
                """, (token_input, db_bot_id))
                await db.commit()
                
            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>PayZy Wallet API Token Set To :- {token_input}</b>'
            )
            
            # Button to go back to the Gateway Setup console menu
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Back to Gateways", callback_data="child_adm_gateway"))

            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # Digi Pay API Token Configuration Engine (With API URL Auto-Log)
        # -----------------------------------------------------------------

        # 1. Triggered when the Admin clicks "API Token" under Digi Pay (gt_dp_token)
        @cloned_dp.callback_query(F.data == "gt_dp_token")
        async def ask_digipay_token(callback_query: types.CallbackQuery, state: FSMContext):
            # Ensure proper table structure layout updates are consistently present
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("PRAGMA table_info(child_gateways)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                
                if "digipay_token" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_token TEXT DEFAULT 'None'")
                if "digipay_base_url" not in columns:
                    await db.execute("ALTER TABLE child_gateways ADD COLUMN digipay_base_url TEXT DEFAULT 'None'")
                await db.commit()

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Provide Digi Pay Wallet API Token!</b>'
            )
            
            # Add a cancel button to return to the gateway panel safely
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_adm_gateway"))
            
            await state.set_state(ChildGatewaySetup.waiting_for_digipay_token)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await callback_query.answer()

        # 2. Triggered when the Admin sends the Digi Pay token text entry into chat
        @cloned_dp.message(ChildGatewaySetup.waiting_for_digipay_token)
        async def save_digipay_token(message: types.Message, state: FSMContext):
            # Verify owner constraint profile paths first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    row = await cursor.fetchone()
            
            if not row or message.from_user.id != row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            token_input = message.text.strip()
            
            # Securely save the token text and log the clean target base URL
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    UPDATE child_gateways 
                    SET digipay_token = ?, digipay_base_url = 'https://Digi-pay-wallet.vercel.app/api' 
                    WHERE bot_id = ?
                """, (token_input, db_bot_id))
                await db.commit()
                
            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> '
                f'<b>Digi Pay Wallet API Token Set To :- {token_input}</b>'
            )
            
            # Button to go back to the Gateway Setup console menu
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Back to Gateways", callback_data="child_adm_gateway"))

            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_builder.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Bot Admin Console - Add Balance Management Engine
        # -----------------------------------------------------------------

        # 1. Triggered when clicking "Add Balance" button (child_adm_addbal)
        @cloned_dp.callback_query(F.data == "child_adm_addbal")
        async def prompt_admin_add_balance(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can use admin utilities.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Provide Chat ID &amp; Amount To Add Balance</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> <b>Example:</b>\n'
                f'<code>{callback_query.from_user.id} 10</code>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildAdminBalanceSetup.waiting_for_add_balance_input)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Input processor execution sequence
        @cloned_dp.message(ChildAdminBalanceSetup.waiting_for_add_balance_input)
        async def process_admin_add_balance_input(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            raw_input = message.text.strip() if message.text else ""
            parts = raw_input.split()

            # Ensure proper two-part argument split array spacing configurations
            if len(parts) != 2:
                await message.answer(
                    "❌ <b>Invalid Input Format!</b>\n"
                    "Please send exactly the <code>Target_Chat_ID Space Amount</code>.", 
                    parse_mode="HTML"
                )
                return

            target_chat_str, amount_str = parts[0], parts[1]

            # Validate numeric compliance
            if not target_chat_str.isdigit():
                await message.answer("❌ <b>Invalid Chat ID! Must be a numeric string value.</b>", parse_mode="HTML")
                return

            try:
                added_amount = float(amount_str)
                if added_amount <= 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Invalid Amount! Must be a positive numeric value format.</b>", parse_mode="HTML")
                return

            target_user_id = int(target_chat_str)
            bot_id = message.bot.id

            # Update structural accounting balances safely inside persistent matrix files
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER,
                        bot_id INTEGER,
                        balance REAL DEFAULT 0.0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # Execute Payout Transaction mirroring the precise gift code payload structure
                await db.execute(
                    "INSERT INTO user_balances (user_id, bot_id, balance) VALUES (?, ?, ?) ON CONFLICT(user_id, bot_id) DO UPDATE SET balance = balance + ?",
                    (target_user_id, bot_id, added_amount, added_amount)
                )
                await db.commit()

                # Extract post-transaction computed ledger figures safely for response formatting
                async with db.execute("SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", (target_user_id, bot_id)) as cursor:
                    bal_row = await cursor.fetchone()
                new_bal = bal_row[0] if bal_row else added_amount

            # Format successful dashboard transaction review parameters
            success_admin_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Successfully Updated Balance Of <code>{target_user_id}</code></b>\n\n'
                f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> <b>New Balance : ₹{new_bal:.2f}</b>'
            )

            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Main Console", callback_data="child_back_to_admin"))
            await message.answer(text=success_admin_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

            # Push instant balance credit notification directly to target user account
            notify_user_text = (
                f'<tg-emoji emoji-id="5375152498656961898">🎀</tg-emoji> '
                f'<b>You Received ₹{added_amount:.2f} As Bonus Gift From Admin!</b>'
            )
            try:
                await message.bot.send_message(chat_id=target_user_id, text=notify_user_text, parse_mode="HTML")
            except Exception:
                # Silently catch errors if the target user has stopped or blocked the bot clone
                pass

        # -----------------------------------------------------------------
        # Cloned Bot Admin Console - Remove Balance Management Engine
        # -----------------------------------------------------------------

        # 1. Triggered when clicking "Remove Balance" button (child_adm_rembal)
        @cloned_dp.callback_query(F.data == "child_adm_rembal")
        async def prompt_admin_remove_balance(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can use admin utilities.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <b>Provide Chat ID &amp; Amount To Remove Balance</b>\n\n'
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> <b>Example:</b>\n'
                f'<code>{callback_query.from_user.id} 10</code>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildAdminBalanceSetup.waiting_for_rem_balance_input)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Input processor execution sequence for deducting balance volume settings
        @cloned_dp.message(ChildAdminBalanceSetup.waiting_for_rem_balance_input)
        async def process_admin_remove_balance_input(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            raw_input = message.text.strip() if message.text else ""
            parts = raw_input.split()

            # Ensure proper two-part argument split array spacing configurations
            if len(parts) != 2:
                await message.answer(
                    "❌ <b>Invalid Input Format!</b>\n"
                    "Please send exactly the <code>Target_Chat_ID Space Amount</code>.", 
                    parse_mode="HTML"
                )
                return

            target_chat_str, amount_str = parts[0], parts[1]

            # Validate numeric compliance
            if not target_chat_str.isdigit():
                await message.answer("❌ <b>Invalid Chat ID! Must be a numeric string value.</b>", parse_mode="HTML")
                return

            try:
                removed_amount = float(amount_str)
                if removed_amount <= 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Invalid Amount! Must be a positive numeric value format.</b>", parse_mode="HTML")
                return

            target_user_id = int(target_chat_str)
            
            # --- MATCHED WITH ADD BALANCE LOGIC: Match row targeting logic with your working Add Balance routine ---
            bot_id = message.bot.id

            # Update structural accounting balances safely inside persistent matrix files
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER,
                        bot_id INTEGER,
                        balance REAL DEFAULT 0.0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # Deduct balance via UPDATE matching execution criteria patterns smoothly using bot_id matching your working command
                await db.execute(
                    "INSERT INTO user_balances (user_id, bot_id, balance) VALUES (?, ?, 0.0) ON CONFLICT(user_id, bot_id) DO UPDATE SET balance = balance - ?",
                    (target_user_id, bot_id, removed_amount)
                )
                await db.commit()

                # Extract post-transaction computed ledger figures safely for response formatting
                async with db.execute("SELECT balance FROM user_balances WHERE user_id = ? AND bot_id = ?", (target_user_id, bot_id)) as cursor:
                    bal_row = await cursor.fetchone()
                new_bal = bal_row[0] if bal_row else 0.0

            # Format successful dashboard transaction review parameters
            success_admin_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Successfully Removed Balance Of <code>{target_user_id}</code></b>\n\n'
                f'<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> <b>New Balance : ₹{new_bal:.2f}</b>'
            )

            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Main Console", callback_data="child_back_to_admin"))
            await message.answer(text=success_admin_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

            # Push instant balance debit warning notification directly to target user account
            notify_user_text = (
                f'<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> '
                f'<b>₹{removed_amount:.2f} Have Been Deducted From Your Balance By Admin!</b>'
            )
            try:
                await message.bot.send_message(chat_id=target_user_id, text=notify_user_text, parse_mode="HTML")
            except Exception:
                # Silently catch errors if the target user has stopped or blocked the bot clone
                pass


        # -----------------------------------------------------------------
        # Cloned Bot Admin Console - Bot Fund Pool Management Engine
        # -----------------------------------------------------------------

        # 1. Triggered when clicking "Set Fund" button (child_adm_setfund)
        @cloned_dp.callback_query(F.data == "child_adm_setfund")
        async def prompt_admin_set_fund(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can use admin utilities.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="5375203677487248777">🎀</tg-emoji><b>Send Your Bot Fund Amount!</b>\n\n'
                f'<i>⚠️ Only Numeric Values Allowed (e.g. 5000)</i>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildGatewaySetup.waiting_for_bot_fund_amount)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Process fund amount input values and update configuration settings
        @cloned_dp.message(ChildGatewaySetup.waiting_for_bot_fund_amount)
        async def process_admin_set_fund_input(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            user_input = message.text.strip() if message.text else ""

            # Validate numeric compliance safely
            try:
                fund_value = float(user_input)
                if fund_value < 0: raise ValueError
            except ValueError:
                await message.answer("❌ <b>Invalid Amount! Please enter a valid positive numeric value framework.</b>", parse_mode="HTML")
                return

            # Update structural data matrices inside table domains safely
            async with aiosqlite.connect("bot_factory.db") as db:
                # Hot patch to guarantee bot_funds column existence dynamically if missing
                async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                if "bot_funds" not in columns:
                    await db.execute("ALTER TABLE child_bot_settings ADD COLUMN bot_funds REAL DEFAULT 0.0")
                    await db.commit()

                await db.execute("""
                    INSERT INTO child_bot_settings (bot_id, bot_funds) 
                    VALUES (?, ?) 
                    ON CONFLICT(bot_id) 
                    DO UPDATE SET bot_funds = excluded.bot_funds
                """, (db_bot_id, fund_value))
                await db.commit()

            # Format successful transaction update parameter block using exact verified emoji
            success_text = f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji><b>Bot Fund Updated To: ₹{fund_value:.2f}</b>'

            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Console", callback_data="child_back_to_admin"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Bot Admin Console - Welcome Channel Configuration Engine
        # -----------------------------------------------------------------

        # 1. Triggered when clicking "Set Welcome Channel" button (child_adm_setwelcome)
        @cloned_dp.callback_query(F.data == "child_adm_setwelcome")
        async def prompt_admin_set_welcome_channel(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can use admin utilities.", show_alert=True)
                return

            ask_text = (
                f'<tg-emoji emoji-id="4999015678238262018">✨</tg-emoji> <b>Provide Your Channel Username (@YourChannel) Or Forward Any Message From The Channel!</b>\n\n'
                f'<tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> <b>Bot Must Be Admin With Invite User Via Link &amp; Post Messages Permission!</b>'
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            await state.set_state(ChildGatewaySetup.waiting_for_welcome_channel)
            await callback_query.message.edit_text(text=ask_text, parse_mode="HTML", reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Input payload processor and deep permission analytical validation scanner
        @cloned_dp.message(ChildGatewaySetup.waiting_for_welcome_channel)
        async def process_admin_welcome_channel_input(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            target_chat_id = None

            # A. Check if the message is a direct channel forward extraction footprint
            if message.forward_origin and message.forward_origin.type == "channel":
                target_chat_id = message.forward_origin.chat.id
            # B. Check if it is a raw username text block string entry input matrix
            elif message.text and message.text.strip().startswith("@"):
                target_chat_id = message.text.strip()
            else:
                await message.answer("❌ <b>Invalid Entry! Please forward a message from your channel or send a valid username starting with @.</b>", parse_mode="HTML")
                return

            try:
                # Resolve target chat target details dynamically using active bot connection parameters
                channel_chat = await message.bot.get_chat(chat_id=target_chat_id)
                if channel_chat.type != "channel":
                    await message.answer("❌ <b>Target Chat is not a valid channel structure. Please check and retry.</b>", parse_mode="HTML")
                    return

                # Read active runtime permissions context via dynamic bot member validation engine
                bot_member = await message.bot.get_chat_member(chat_id=channel_chat.id, user_id=message.bot.id)
                
                # Check for critical administrative status levels
                if bot_member.status not in ["administrator", "creator"]:
                    await message.answer('<tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji><b>The Bot is not an admin inside your target channel!</b>', parse_mode="HTML")
                    return

                # Validate permission arrays meticulously to match execution criteria
                if not bot_member.can_post_messages:
                    await message.answer('<tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji><b>Your Channel Lack Post Messages Permission To The Bot!</b>', parse_mode="HTML")
                    return
                if not bot_member.can_invite_users:
                    await message.answer('<tg-emoji emoji-id="6309648704076782071">🚫</tg-emoji><b>Your Channel Lack Invite User Via Link Permission To The Bot!</b>', parse_mode="HTML")
                    return

                # Export new persistent dynamic custom channel link profile footprint natively
                invite_link_object = await message.bot.create_chat_invite_link(
                    chat_id=channel_chat.id,
                    name=f"Welcome Link"
                )
                generated_link = invite_link_object.invite_link

            except Exception as error:
                await message.answer(f"❌ <b>API Communication Error: Ensure the Bot has been added inside the channel as Admin first. Log: {str(error)}</b>", parse_mode="HTML")
                return

            # Save structure matrix into SQL tables cleanly
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                
                if "welcome_channel_id" not in columns:
                    await db.execute("ALTER TABLE child_bot_settings ADD COLUMN welcome_channel_id TEXT DEFAULT 'None'")
                    await db.commit()
                if "welcome_channel_link" not in columns:
                    await db.execute("ALTER TABLE child_bot_settings ADD COLUMN welcome_channel_link TEXT DEFAULT 'None'")
                    await db.commit()

                # --- FIXED: Check row existence explicitly to run a clean fallback UPDATE or INSERT matrix ---
                async with db.execute("SELECT 1 FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as check_cursor:
                    exists = await check_cursor.fetchone()

                if exists:
                    await db.execute("""
                        UPDATE child_bot_settings 
                        SET welcome_channel_id = ?, welcome_channel_link = ? 
                        WHERE bot_id = ?
                    """, (str(channel_chat.id), generated_link, db_bot_id))
                else:
                    await db.execute("""
                        INSERT INTO child_bot_settings (bot_id, welcome_channel_id, welcome_channel_link) 
                        VALUES (?, ?, ?)
                    """, (db_bot_id, str(channel_chat.id), generated_link))
                await db.commit()

            # Format premium response confirmation wrapper parameters seamlessly
            success_text = (
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Successfully Added <code>{channel_chat.id}</code></b>\n\n'
                f'<tg-emoji emoji-id="6309997365226903510">🔗</tg-emoji> <b>Invite Link: {generated_link}</b>'
            )

            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Console", callback_data="child_back_to_admin"))
            await message.answer(text=success_text, parse_mode="HTML", reply_markup=back_btn.as_markup())
            await state.clear()

        # =================================================================
        # CLONED BOT ADMIN: Ban User Dashboard Utilities
        # =================================================================

        # 1. Triggered when clicking "Ban User" button (child_adm_ban)
        @cloned_dp.callback_query(F.data == "child_adm_ban")
        async def prompt_admin_ban_user(callback_query: types.CallbackQuery, state: FSMContext):
            # Security verification guard: Confirm ownership matrix via DB tracking rows
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the owner can use admin utilities.", show_alert=True)
                return

            ask_ban_content = Text(
                CustomEmoji("✅", custom_emoji_id="6298317205960397843"),
                Bold("Provide User Chat ID To Ban Him!")
            )

            cancel_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Cancel", callback_data="child_back_to_admin"))
            # --- FIXED: Routing safely into your explicit ChildBanSetup state tracker domain ---
            await state.set_state(ChildBanSetup.waiting_for_ban_id)
            await callback_query.message.edit_text(**ask_ban_content.as_kwargs(), reply_markup=cancel_btn.as_markup())
            await callback_query.answer()

        # 2. Input processor that performs isolation ban execution restricted strictly to current bot instance context
        @cloned_dp.message(ChildBanSetup.waiting_for_ban_id)
        async def process_admin_ban_execution(message: types.Message, state: FSMContext):
            # Verify administrative ownership constraints first
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
            
            if not owner_row or message.from_user.id != owner_row[0]:
                await message.answer("❌ <b>Unauthorized Operation Access Blocked.</b>", parse_mode="HTML")
                await state.clear()
                return

            target_input = message.text.strip() if message.text else ""
            if not target_input.isdigit():
                await message.answer("❌ <b>Invalid Input! Please provide a numeric Telegram User Chat ID.</b>", parse_mode="HTML")
                return

            target_ban_user_id = int(target_input)

            # Ensure tracking tables exist natively inside your environment database context engine
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_banned_users (
                        user_id INTEGER,
                        bot_id INTEGER,
                        banned_at TEXT,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # Execute localized target injection context (Banned only from the executing clone bot instance space)
                await db.execute("""
                    INSERT INTO child_banned_users (user_id, !db_bot_id!, banned_at)
                    VALUES (?, ?, DATETIME('now'))
                    ON CONFLICT(user_id, bot_id) DO NOTHING
                """.replace("!db_bot_id!", "bot_id"), (target_ban_user_id, db_bot_id))
                await db.commit()

            # Format premium response confirmation wrapper parameters seamlessly using requested premium emoji strings
            success_ban_content = Text(
                CustomEmoji("🚫", custom_emoji_id="6309648704076782071"),
                " ",
                Bold(f"{target_ban_user_id} Have Been Banned From Bot Successfully !")
            )

            back_btn = InlineKeyboardBuilder().add(types.InlineKeyboardButton(text="⬅️ Back to Console", callback_data="child_back_to_admin"))
            await message.answer(**success_ban_content.as_kwargs(), reply_markup=back_btn.as_markup())
            await state.clear()

        # -----------------------------------------------------------------
        # 1. Callback Query Handler (Using Cloned Dispatcher Pipeline)
        # -----------------------------------------------------------------

        @cloned_dp.callback_query(F.data == "claim_gift_code")
        async def process_claim_gift_code(callback_query: types.CallbackQuery, state: FSMContext):
            # Safe dynamic retrieval of the current running clone's unique ID
            bot_id = callback_query.bot.id

            # Check if at least one active gift code exists for THIS clone bot OR has a default ID of 0
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    """SELECT COUNT(*) FROM gift_codes 
                       WHERE (bot_id = ? OR bot_id = 0) 
                       AND status = 'Active' 
                       AND max_uses > current_uses""",
                    (bot_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    available_codes = row[0] if row else 0

            if available_codes == 0:
                await callback_query.answer()
                await callback_query.message.answer(
                    "<b><tg-emoji emoji-id='6309648704076782071'>🚫</tg-emoji> No Gift Code Available At This Moment!</b>", 
                    parse_mode="HTML"
                )
                return

            # Store the clone's verified context ID inside FSM tracking storage
            await state.update_data(current_clone_db_id=bot_id)

            # Construct custom standard panel keyboard
            builder = ReplyKeyboardBuilder()
            builder.button(text="Back To Panel", style="danger", icon_custom_emoji_id="6309851100115640076")
            
            await state.set_state(GiftCodeForm.waiting_for_code)
            await callback_query.answer()
            await callback_query.message.answer(
                "<b><tg-emoji emoji-id='6300651726844204536'>✨</tg-emoji> Send Gift Code To Claim Reward!</b>", 
                parse_mode="HTML",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )

        # -----------------------------------------------------------------
        # 2. Input Validation Handler (Using Cloned Dispatcher Pipeline)
        # -----------------------------------------------------------------

        @cloned_dp.message(GiftCodeForm.waiting_for_code)
        async def validate_and_claim_code(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            provided_code = message.text.strip()
            
            # Pull tracking identifier from storage or resolve via runtime message context
            state_data = await state.get_data()
            bot_id = state_data.get("current_clone_db_id") or message.bot.id

            if provided_code == "Back To Panel":
                await state.clear()
                await message.answer("<b>Returned to panel.</b>", reply_markup=get_clone_main_menu_keyboard())
                return

            async with aiosqlite.connect(DB_NAME) as db:
                # 1. Fetch exact explicit positions to fully bypass row_factory dictionary naming issues
                async with db.execute(
                    """SELECT id, bot_id, code, amount, req_referrals, max_uses, current_uses, status 
                       FROM gift_codes 
                       WHERE (bot_id = ? OR bot_id = 0) AND code = ? AND status = 'Active'""", 
                    (bot_id, provided_code)
                ) as cursor:
                    code_data = await cursor.fetchone()

                if not code_data:
                    await message.answer("<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> Invalid Gift Code...!</b>", parse_mode="HTML")
                    return

                # Map database values securely by structural index positions
                gift_db_id      = code_data[0]
                reward_amount   = code_data[3]
                required_refers = code_data[4]
                max_uses        = code_data[5]
                current_uses    = code_data[6]

                # 2. Check if already claimed by this specific user on this specific clone
                async with db.execute(
                    "SELECT COUNT(*) FROM claimed_gift_codes WHERE user_id = ? AND bot_id = ? AND code_id = ?", 
                    (user_id, bot_id, gift_db_id)
                ) as check_cursor:
                    already_claimed = (await check_cursor.fetchone())[0]

                if already_claimed > 0:
                    await message.answer("<b><tg-emoji emoji-id='6309980103753341998'>❌</tg-emoji> You have already claimed this gift code!</b>", parse_mode="HTML")
                    return

                # 3. Check usage limit
                if current_uses >= max_uses:
                    await message.answer("<b><tg-emoji emoji-id='6309648704076782071'>🚫</tg-emoji> This gift code has expired or reached its maximum limit!</b>", parse_mode="HTML")
                    return

                # 4. Verify verified refers using your user_verification matrix for this bot
                async with db.execute(
                    """SELECT COUNT(*) FROM user_verification 
                       WHERE bot_id = ? AND seen = 1 
                       AND user_id IN (SELECT referred_id FROM user_referrals WHERE referrer_id = ? AND bot_id = ?)""",
                    (bot_id, user_id, bot_id)
                ) as ref_cursor:
                    verified_refers = (await ref_cursor.fetchone())[0]

                if verified_refers < required_refers:
                    await message.answer(
                        f"<b><tg-emoji emoji-id='5251203410396458957'>🛡️</tg-emoji> You Need {required_refers} Verified Refers To Claim This Code!</b>", 
                        parse_mode="HTML"
                    )
                    return

                # 5. Execute Payout Transaction
                # Update user balance within this specific clone bot's balance domain
                await db.execute(
                    "INSERT INTO user_balances (user_id, bot_id, balance) VALUES (?, ?, ?) ON CONFLICT(user_id, bot_id) DO UPDATE SET balance = balance + ?",
                    (user_id, bot_id, reward_amount, reward_amount)
                )
                
                # Log transaction footprint mapping
                await db.execute("INSERT INTO claimed_gift_codes (user_id, bot_id, code_id) VALUES (?, ?, ?)", (user_id, bot_id, gift_db_id))
                # Increment usage tracker
                await db.execute("UPDATE gift_codes SET current_uses = current_uses + 1 WHERE id = ?", (gift_db_id,))
                await db.commit()

            # 6. Success Response
            success_img = "https://ganga--link--ghhzdp9sv8hk.code.run/i/czaehzl5.jpg"
            success_caption = f"<b><tg-emoji emoji-id='5442939099906325301'>🎉</tg-emoji> Congratulations! You Have Successfully Claimed The Gift Code Of ₹{reward_amount}</b>"
            
            await message.answer_photo(
                photo=success_img, 
                caption=success_caption, 
                parse_mode="HTML", 
                reply_markup=get_clone_main_menu_keyboard()
            )
            await state.clear()

        # -----------------------------------------------------------------
        # Cloned Child Bot Analytics Dashboard Handler
        # -----------------------------------------------------------------
        @cloned_dp.callback_query(F.data == "child_adm_analytics")
        async def process_child_bot_analytics(callback_query: types.CallbackQuery):
            # Extract raw Telegram API identifier context for this sub-instance clone
            bot_id = callback_query.bot.id

            # 1. Fetch deployment owner metadata information
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute("SELECT user_id FROM cloned_bots WHERE id = ?", (db_bot_id,)) as cursor:
                    owner_row = await cursor.fetchone()
                    
            if not owner_row or callback_query.from_user.id != owner_row[0]:
                await callback_query.answer("❌ Access Refused. Only the deployment creator can view analytics.", show_alert=True)
                return

            # 2. Asynchronously calculate metrics from historical system registries
            async with aiosqlite.connect("bot_factory.db") as db:
                # Ensure the user_verification table handles bot isolated scopes safely
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_verification (
                        user_id INTEGER,
                        bot_id INTEGER,
                        seen INTEGER DEFAULT 0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # Calculate verification metrics strictly scoped to THIS specific child bot using Telegram ID
                async with db.execute("""
                    SELECT COUNT(*), 
                           SUM(CASE WHEN seen = 1 THEN 1 ELSE 0 END), 
                           SUM(CASE WHEN seen = 0 THEN 1 ELSE 0 END) 
                    FROM user_verification WHERE bot_id = ?
                """, (bot_id,)) as cursor:
                    v_row = await cursor.fetchone()
                
                total_users = v_row[0] if v_row and v_row[0] else 0
                verified_users = v_row[1] if v_row and v_row[1] else 0
                unverified_users = v_row[2] if v_row and v_row[2] else 0

                # Fetch the overall master fund pool allocated by /setfund from child_bot_settings
                async with db.execute("SELECT bot_funds FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as cursor:
                    funds_row = await cursor.fetchone()
                allocated_funds = funds_row[0] if funds_row and funds_row[0] is not None else 0.00

                # Calculate total distributed payouts dynamically from your processing table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_payout_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot_id INTEGER,
                        amount REAL,
                        status TEXT
                    )
                """)
                await db.commit()
                
                async with db.execute(
                    "SELECT SUM(amount) FROM child_payout_logs WHERE bot_id = ? AND status = 'Success'", 
                    (db_bot_id,)
                ) as cursor:
                    payout_row = await cursor.fetchone()
                total_payout_distributed = payout_row[0] if payout_row and payout_row[0] is not None else 0.00

                # Dynamic calculation matching: Remaining Funds = Allocated Fund Pool - Distributed Payouts
                total_funds_left = max(0.00, allocated_funds - total_payout_distributed)

            # Format the host mention link using user attributes safely
            owner_mention = f'<a href="tg://user?id={owner_row[0]}">{callback_query.from_user.first_name}</a>'

            # 3. Construct premium metrics text interface wrapping exact requested emoji assets
            analytics_text = (
                f'<tg-emoji emoji-id="6309641561546168537">📊</tg-emoji> <b>Bot Analytics Dashboard</b>\n\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="6300797828746711280">📈</tg-emoji> <b>User Metrics</b>\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="4942888689131848546">👥</tg-emoji> <b>Total Users: {total_users}</b>\n'
                f'<tg-emoji emoji-id="6267008582294705964">✅</tg-emoji> <b>Total Verified Users: {verified_users}</b>\n'
                f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji> <b>Total Unverified Users: {unverified_users}</b>\n'
                f'<tg-emoji emoji-id="6267144651153609853">🚨</tg-emoji> <b>Users Who Haven\'t Joined Channels: 0</b>\n\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji> <b>Financial Metrics</b>\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="6068996425146965808">📤</tg-emoji> <b>Total Payout Distributed: ₹{total_payout_distributed:.2f}</b>\n'
                f'<tg-emoji emoji-id="5472030678633684592">💸</tg-emoji> <b>Total Funds Left: ₹{total_funds_left:.2f}</b>\n\n'
                f"━━━━━━━━━━━━━━━\n"
                f'<tg-emoji emoji-id="6300651726844204536">🚀</tg-emoji> <b>Bot Hosted By {owner_mention}</b>'
            )

            # Back button navigation setup to return instantly to the admin console dashboard
            back_builder = InlineKeyboardBuilder()
            back_builder.add(types.InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="child_back_to_admin"))

            # Edit the message directly with the fresh layout dashboard interface
            try:
                await callback_query.message.edit_text(
                    text=analytics_text, 
                    parse_mode="HTML", 
                    reply_markup=back_builder.as_markup()
                )
            except Exception:
                # Fallback backup option: Send fresh message if editing throws a state error
                await callback_query.message.answer(
                    text=analytics_text, 
                    parse_mode="HTML", 
                    reply_markup=back_builder.as_markup()
                )
            await callback_query.answer()


        # =================================================================
        # CLONED BOT ROUTER: Claim Button Membership Verification Core
        # =================================================================
        @cloned_dp.callback_query(F.data == "child_claim_channels_verify")
        async def process_cloned_user_claim_verification(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            raw_bot_token_id = callback_query.bot.id

            async with aiosqlite.connect("bot_factory.db") as db:
                # Pull all target channels linked to this specific clone instance directly using db_bot_id
                async with db.execute("SELECT channel_id FROM child_bot_channels WHERE bot_id = ?", (db_bot_id,)) as c_cursor:
                    linked_channels = await c_cursor.fetchall()

            # Dynamic membership verification loop check across all required records
            has_joined_all = True
            
            async with aiosqlite.connect("bot_factory.db") as db:
                for ch_row in linked_channels:
                    target_channel_chat_id = ch_row[0]
                    clean_chat_id = str(target_channel_chat_id).strip()
                    
                    # Check 1: Is user already an official member according to Telegram API profiles?
                    is_member = False
                    try:
                        resolved_id = int(clean_chat_id) if (clean_chat_id.startswith("-") or clean_chat_id.isdigit()) else clean_chat_id
                        member_profile = await callback_query.bot.get_chat_member(chat_id=resolved_id, user_id=user_id)
                        if member_profile.status not in ["left", "kicked", "left_chat_member"]:
                            is_member = True
                    except Exception:
                        pass

                    # Check 2: Cross-verify using db_bot_id AND raw_bot_token_id to ensure request queue matching
                    if not is_member:
                        async with db.execute("""
                            SELECT 1 FROM child_join_requests 
                            WHERE (bot_id = ? OR bot_id = ?) AND channel_id = ? AND user_id = ?
                        """, (db_bot_id, raw_bot_token_id, clean_chat_id, user_id)) as req_check:
                            has_request = await req_check.fetchone()
                        
                        if not has_request:
                            has_joined_all = False
                            break

            if not has_joined_all:
                await callback_query.answer("⚠️ You must join or request to join all required channels listed above before claiming access!", show_alert=True)
                return

            # --- DYNAMIC MATRIX DISPATCH: Evaluate Device Verification State ---
            async with aiosqlite.connect("bot_factory.db") as db:
                # Map the live token ID safely to check active settings mapping column structure layout
                async with db.execute("SELECT id FROM cloned_bots WHERE bot_id = ?", (str(raw_bot_token_id),)) as lookup_cursor:
                    bot_row = await lookup_cursor.fetchone()
                active_db_bot_id = bot_row[0] if bot_row else None

                async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                    settings_columns = [col[1] for col in await cursor.fetchall()]
                settings_key_column = "bot_id" if "bot_id" in settings_columns else "id"

                device_verify_on = True
                if active_db_bot_id is not None:
                    async with db.execute(f"SELECT device_verification FROM child_bot_settings WHERE {settings_key_column} = ?", (active_db_bot_id,)) as cursor:
                        settings_row = await cursor.fetchone()
                    if settings_row:
                        device_verify_on = settings_row[0] == "On"

            # ✅ STAGE 2 ROUTING: If Device Verification is enabled, serve the external portal request link!
            if device_verify_on:
                await callback_query.answer("🔗 Channels Verified! Proceed to device unlock step.", show_alert=False)
                
                try: await callback_query.message.delete()
                except: pass

                # --- Get Live Bot Profile context to pull clean username ---
                bot_user = await callback_query.bot.get_me()
                clean_username = bot_user.username

                device_verification_text = (
                    f'<b><tg-emoji emoji-id="5296369303661067030">🔐</tg-emoji> Verify Yourself To Unlock Access To Bot!</b>'
                )
                
                # ✅ FIXED: Correctly nested f-string quotes and WebAppInfo instantiation
                device_markup = types.InlineKeyboardMarkup(inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="Verify",
                            web_app=types.WebAppInfo(url=f"https://newdevice.vercel.app/?bot={clean_username}"),
                            style="primary",
                            icon_custom_emoji_id="6267008582294705964"
                        )
                    ]
                ])
                
                await callback_query.message.answer(text=device_verification_text, parse_mode="HTML", reply_markup=device_markup)
                return


            # --- FALLBACK PATHWAY: If Device Verification is completely OFF, authorize entry instantly ---
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    INSERT OR REPLACE INTO user_verification (user_id, bot_id, seen)
                    VALUES (?, ?, 1)
                """, (user_id, raw_bot_token_id))
                await db.commit()

            await callback_query.answer("✅ Verification Success! Access Granted.", show_alert=False)
            
            try: await callback_query.message.delete()
            except: pass
            
            # Reconstruct contextual Message signatures cleanly to prevent pydantic strict field collision crashes
            mock_start_message = types.Message(
                message_id=callback_query.message.message_id,
                date=callback_query.message.date,
                chat=callback_query.message.chat,
                from_user=callback_query.from_user,
                text="/start"
            )
            mock_start_message._bot = callback_query.bot

            from aiogram.filters import CommandObject
            mock_command_args = CommandObject(prefix="/", command="start", mention=None, args="")
            
            # Execute master start logic loop cleanly right away
            await handle_cloned_start(message=mock_start_message, command=mock_command_args)

        

        # =================================================================
        # CLONED BOT ROUTER: Single Process /start Handler
        # =================================================================
        @cloned_dp.message(Command("start"))
        async def handle_cloned_start(message: types.Message, command: CommandObject):
            user_id = message.from_user.id
            raw_bot_token_id = message.bot.id  # The raw unique 10-digit Telegram Token ID
            
            # Safe parsing prevents unhandled AttributeError crashes when args are absent
            start_args = command.args.strip() if command.args else ""
            
            async with aiosqlite.connect("bot_factory.db") as db:
                # Ensure the infrastructure tracking environments exist natively
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS child_bot_settings (
                        bot_id INTEGER PRIMARY KEY,
                        status_state TEXT DEFAULT 'Active',
                        device_verification TEXT DEFAULT 'On',
                        min_withdraw REAL DEFAULT 100.0,
                        max_withdraw REAL DEFAULT 10000.0,
                        req_referrals INTEGER DEFAULT 3,
                        cooldown TEXT DEFAULT 'off'
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_verification (
                        user_id INTEGER,
                        bot_id INTEGER,
                        seen INTEGER DEFAULT 0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_referrals (
                        referrer_id INTEGER,
                        referred_id INTEGER,
                        bot_id INTEGER,
                        PRIMARY KEY(referred_id, bot_id)
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS user_balances (
                        user_id INTEGER,
                        bot_id INTEGER,
                        balance REAL DEFAULT 0.0,
                        PRIMARY KEY(user_id, bot_id)
                    )
                """)
                await db.commit()

                # --- FIXED: Dynamically map the live Telegram bot token ID to get your internal database row id context ---
                async with db.execute("SELECT id FROM cloned_bots WHERE bot_id = ?", (str(raw_bot_token_id),)) as lookup_cursor:
                    bot_row = await lookup_cursor.fetchone()
                
                # Resolve active database row context parameter safely
                active_db_bot_id = bot_row[0] if bot_row else None

                # Hot patch scan structure to detect if child_bot_settings uses 'id' instead of 'bot_id'
                async with db.execute("PRAGMA table_info(child_bot_settings)") as cursor:
                    settings_columns = [col[1] for col in await cursor.fetchall()]
                
                settings_key_column = "bot_id" if "bot_id" in settings_columns else "id"

                # Check if user_balances uses 'bot_id' column format safely
                async with db.execute("PRAGMA table_info(user_balances)") as cursor:
                    balances_columns = [col[1] for col in await cursor.fetchall()]
                
                balances_key_column = "bot_id" if "bot_id" in balances_columns else "id"

                # Fetch global switch parameter criteria safely using dynamic column keys and the mapped row context ID
                device_verify_on = True
                current_state = "Active"
                if active_db_bot_id is not None:
                    async with db.execute(f"SELECT status_state, device_verification FROM child_bot_settings WHERE {settings_key_column} = ?", (active_db_bot_id,)) as cursor:
                        settings_row = await cursor.fetchone()
                    if settings_row:
                        current_state = settings_row[0] if settings_row[0] else "Active"
                        device_verify_on = settings_row[1] == "On"

                # --- STATUS CHECK INTERCEPTION MATRIX ---
                if current_state == "Maintenance":
                    maintenance_text = (
                        f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                        f'<b>The Bot Is Currently Under Maintenance!</b>'
                    )
                    await message.answer(text=maintenance_text, parse_mode="HTML")
                    return

                if current_state in ["Disable", "disabled"]:
                    disabled_text = (
                        f'<tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji>'
                        f'<b>The Bot Is Currently Off!</b>'
                    )
                    await message.answer(text=disabled_text, parse_mode="HTML")
                    return

                # --- IMMEDIATE DATABASE FOOTPRINT REGISTRATION ENGINE ---
                await db.execute(f"""
                    INSERT INTO user_balances (user_id, {balances_key_column}, balance)
                    VALUES (?, ?, 0.0)
                    ON CONFLICT(user_id, {balances_key_column}) DO NOTHING
                """, (user_id, raw_bot_token_id))
                
                # Log deep-link referrer parameters safely into tracking tables right away before verification
                if start_args and start_args.isdigit() and int(start_args) != user_id:
                    await db.execute("""
                        INSERT OR IGNORE INTO user_referrals (referrer_id, referred_id, bot_id)
                        VALUES (?, ?, ?)
                    """, (int(start_args), user_id, raw_bot_token_id))
                await db.commit()

            # 💡 CONDITIONAL GUARD: If Device Verification is OFF, immediately push normal welcome menu and distribute rewards
            if not device_verify_on:
                if start_args and start_args.isdigit() and int(start_args) != user_id:
                    # Direct instant reward payouts engine since device verification check is skipped
                    async with aiosqlite.connect("bot_factory.db") as db:
                        async with db.execute("SELECT refer_amount, refer_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as s_cursor:
                            s_row = await s_cursor.fetchone()
                    
                    raw_reward = s_row[0] if s_row and s_row[0] not in ["健全 Nᴏᴛ Sᴇᴛ", "Tell Me", "❎ Nᴏᴛ Sᴇᴛ"] else "1"
                    refer_mode = s_row[1] if s_row and s_row[1] else "Normal (Fixed Amount)"
                    
                    import random
                    credited_amount = 1.0
                    if "Random" in refer_mode and "-" in raw_reward:
                        try:
                            parts = raw_reward.split("-")
                            credited_amount = round(random.uniform(float(parts[0].strip()), float(parts[1].strip())), 2)
                        except Exception:
                            credited_amount = 1.0
                    else:
                        try:
                            credited_amount = float(raw_reward)
                        except Exception:
                            credited_amount = 1.0

                    async with aiosqlite.connect("bot_factory.db") as db:
                        await db.execute(f"""
                            UPDATE user_balances SET balance = balance + ? 
                            WHERE user_id = ? AND {balances_key_column} = ?
                        """, (credited_amount, int(start_args), raw_bot_token_id))
                        await db.commit()

                    notification_text = (
                        f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> '
                        f'<b><code>{user_id}</code> Got Invited By Your Url: +{credited_amount:.2f} Rs</b>'
                    )
                    try:
                        await message.bot.send_message(chat_id=int(start_args), text=notification_text, parse_mode="HTML")
                    except Exception:
                        pass

                await send_clone_normal_welcome(message)
                return

            # --- VERIFICATION ON FLOW ---
            async with aiosqlite.connect("bot_factory.db") as db:
                # 1. Process deep-link incoming verification validation parameters
                if start_args in ["verified", "failed"]:
                    seen_status = 1 if start_args == "verified" else 0
                    
                    await db.execute("""
                        INSERT OR REPLACE INTO user_verification (user_id, bot_id, seen) 
                        VALUES (?, ?, ?)
                    """, (user_id, raw_bot_token_id, seen_status))
                    await db.commit()
                    
                    if start_args == "verified":
                        # Check if this verified user has an active pending inviter record logged
                        async with db.execute("SELECT referrer_id FROM user_referrals WHERE referred_id = ? AND bot_id = ?", (user_id, raw_bot_token_id)) as ref_cursor:
                            ref_row = await ref_cursor.fetchone()
                        
                        if ref_row:
                            referrer_id = ref_row[0]
                            
                            # Pull active dynamic balance rewards configuration keys safely using db_bot_id target
                            async with db.execute("SELECT refer_amount, refer_mode FROM child_bot_settings WHERE bot_id = ?", (db_bot_id,)) as settings_cursor:
                                settings_row = await settings_cursor.fetchone()
                            
                            raw_reward = settings_row[0] if settings_row and settings_row[0] not in ["健全 Nᴏᴛ Sᴇᴛ", "Tell Me", "❎ Nᴏᴛ Sᴇᴛ"] else "1"
                            refer_mode = settings_row[1] if settings_row and settings_row[1] else "Normal (Fixed Amount)"
                            
                            import random
                            credited_amount = 1.0
                            if "Random" in refer_mode and "-" in raw_reward:
                                try:
                                    parts = raw_reward.split("-")
                                    credited_amount = round(random.uniform(float(parts[0].strip()), float(parts[1].strip())), 2)
                                except Exception:
                                    credited_amount = 1.0
                            else:
                                try:
                                    credited_amount = float(raw_reward)
                                except Exception:
                                    credited_amount = 1.0

                            # Credit the verified currency directly into the inviter's ledger balance
                            await db.execute(f"""
                                UPDATE user_balances SET balance = balance + ? 
                                WHERE user_id = ? AND {balances_key_column} = ?
                            """, (credited_amount, referrer_id, raw_bot_token_id))
                            await db.commit()

                            # Fire real-time notification with your requested custom premium emoji token
                            notification_text = (
                                f'<tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> '
                                f'<b><code>{user_id}</code> Got Invited By Your Url: +{credited_amount:.2f} Rs</b>'
                            )
                            try:
                                await message.bot.send_message(chat_id=referrer_id, text=notification_text, parse_mode="HTML")
                            except Exception:
                                pass

                        await send_clone_normal_welcome(message)
                    else:
                        failed_content = Text(
                            CustomEmoji("⚠️", custom_emoji_id="5447644880824181073"), 
                            Bold(" Device Verification Failed!!\n\n"),
                            CustomEmoji("➡️", custom_emoji_id="6267119710278522544"), 
                            Bold(" You Can Still Participate In Our Refer & Earn Program!\n\n"),
                            CustomEmoji("💫", custom_emoji_id="5469741319330996757"), 
                            Bold(" Welcome To Cash Giveaway Bot! "), 
                            CustomEmoji("💫", custom_emoji_id="5469741319330996757")
                        )
                        await message.answer(**failed_content.as_kwargs(), reply_markup=get_clone_main_menu_keyboard())
                    return

                # 2. Scope verification lookup context isolated safely by raw Telegram token bot_id matrix parameters
                async with db.execute("SELECT seen FROM user_verification WHERE user_id = ? AND bot_id = ?", (user_id, raw_bot_token_id)) as cursor:
                    row = await cursor.fetchone()
                    
            # Safe passage check for historical confirmations
            if row is not None and row[0] == 1:
                await send_clone_normal_welcome(message)
                return

            # FIRST TIME RUNNING WITH VERIFICATION ON: Log the dynamic footprint profile entries as Unverified state first (seen=0)
            async with aiosqlite.connect("bot_factory.db") as db:
                await db.execute("""
                    INSERT OR IGNORE INTO user_verification (user_id, bot_id, seen) 
                    VALUES (?, ?, 0)
                """, (user_id, raw_bot_token_id))
                await db.commit()

                # ✅ IMPLEMENTED: Fetch active channels list for the specific cloned bot layout structure
                async with db.execute("SELECT invite_link FROM child_bot_channels WHERE bot_id = ?", (db_bot_id,)) as c_cursor:
                    saved_channels_list = await c_cursor.fetchall()

            # Beautifully formatted bold descriptions using your premium custom emoji tokens
            channels_verify_welcome_text = (
                f'<b><tg-emoji emoji-id="6118333272821865260">👑</tg-emoji> Hey !! User Welcome To Bot</b>\n\n'
                f'<b><tg-emoji emoji-id="6300633168290517241">🟢</tg-emoji> Must Join All Channels To Use Bot</b>\n\n'
                f'<b><tg-emoji emoji-id="4996755833950831347">🎉</tg-emoji> After Joining Click Claim</b>'
            )

            # Build list using raw InlineKeyboardButton objects to preserve custom premium parameters flawlessly
            keyboard_rows = []
            current_row = []

            for ch_entry in saved_channels_list:
                invite_url_target = ch_entry[0]
                
                # Restore your primary style and custom emoji configurations
                btn = types.InlineKeyboardButton(
                    text="Join",
                    url=invite_url_target,
                    style="primary",
                    icon_custom_emoji_id="6267008582294705964"
                )
                current_row.append(btn)
                
                # Bundle into 2 buttons per row grid mapping format cleanly
                if len(current_row) == 2:
                    keyboard_rows.append(current_row)
                    current_row = []
            
            # Append any trailing single button row if left over
            if current_row:
                keyboard_rows.append(current_row)

            # Append your Success Claim button right below with its custom parameters
            claim_button_row = [
                types.InlineKeyboardButton(
                    text="Claim",
                    callback_data="child_claim_channels_verify",
                    style="success",
                    icon_custom_emoji_id="5296369303661067030"
                )
            ]
            keyboard_rows.append(claim_button_row)

            # Render markup explicitly bypassing any aiogram stripping limitations
            custom_markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            await message.answer(text=channels_verify_welcome_text, parse_mode="HTML", reply_markup=custom_markup)

        # =================================================================
        # CLONED BOT ROUTER: /livefund Announcement Handler
        # =================================================================
        @cloned_dp.message(Command("livefund"))
        async def handle_cloned_live_fund_announcement(message: types.Message):
            # Safe runtime validation mapping of the executing clone bot instance profile
            raw_telegram_bot_id = message.bot.id
            me = await message.bot.get_me()
            bot_username_formatted = f"@{me.username}"

            # Extract the bot token safely across different aiogram versions
            bot_token_str = ""
            if hasattr(message.bot, 'token'):
                bot_token_str = message.bot.token
            elif hasattr(message.bot, '_token'):
                bot_token_str = message.bot._token

            # 1. Resolve internal db_bot_id row key context securely using robust fallback checks
            async with aiosqlite.connect("bot_factory.db") as db:
                async with db.execute(
                    "SELECT id FROM cloned_bots WHERE bot_id = ? OR bot_token = ?", 
                    (str(raw_telegram_bot_id), bot_token_str)
                ) as lookup_cursor:
                    bot_row = await lookup_cursor.fetchone()
                
                active_db_bot_id = bot_row[0] if bot_row else (db_bot_id if 'db_bot_id' in globals() else None)

                if not active_db_bot_id:
                    await message.answer("<b>❌ Structural Error: Failed to resolve this clone bot's database profile configuration context.</b>", parse_mode="HTML")
                    return

                # 2. Dynamic column extraction check to find where you store the set fund balance configuration
                async with db.execute("PRAGMA table_info(child_bot_settings)") as col_cursor:
                    columns = [r[1] for r in await col_cursor.fetchall()]
                
                fund_column_to_read = None
                for candidate in ["total_funds", "bot_funds", "funds", "min_withdraw"]:
                    if candidate in columns:
                        fund_column_to_read = candidate
                        break
                
                query_select_fields = "welcome_channel_id, welcome_channel_link"
                welcome_user_col = ", welcome_channel_user" if "welcome_channel_user" in columns else ""
                
                if fund_column_to_read:
                    query_string = f"SELECT {query_select_fields}{welcome_user_col}, {fund_column_to_read} FROM child_bot_settings WHERE bot_id = ?"
                else:
                    query_string = f"SELECT {query_select_fields}{welcome_user_col} FROM child_bot_settings WHERE bot_id = ?"

                async with db.execute(query_string, (active_db_bot_id,)) as settings_cursor:
                    settings_data = await settings_cursor.fetchone()

            if not settings_data or not settings_data[0] or settings_data[0] == "None":
                await message.answer("<b>❌ Setup Incomplete: You must configure a Welcome Channel via the Admin Panel first!</b>", parse_mode="HTML")
                return

            # Map settings payload parameters securely from structural database row matrix positions
            channel_target_id = settings_data[0]
            saved_welcome_link = settings_data[1]
            
            # Dynamically determine index offsets depending on whether the welcome user column exists
            has_user_field = "welcome_channel_user" in columns
            saved_channel_username = settings_data[2] if has_user_field else None
            
            fund_index = 3 if has_user_field else 2
            remaining_funds_raw = settings_data[fund_index] if fund_column_to_read and len(settings_data) > fund_index else 500.0
            
            try:
                remaining_funds_clean = float(str(remaining_funds_raw).replace("₹", "").strip())
            except ValueError:
                remaining_funds_clean = 500.0

            # --- FIXED: Dynamically fetch real channel title from Telegram API for accurate branding ---
            channel_display_title = "Our Channel Network"
            try:
                chat_info = await message.bot.get_chat(chat_id=channel_target_id)
                if chat_info.title:
                    channel_display_title = chat_info.title
            except Exception:
                pass

            # 3. Meticulously resolve Power Branding details using the dynamic channel title
            if saved_channel_username and saved_channel_username != "None" and str(saved_channel_username).startswith("@"):
                branding_power_element = TextLink(saved_channel_username, url=f"https://t.me/{saved_channel_username.replace('@', '').strip()}")
            elif saved_welcome_link and saved_welcome_link != "None" and "t.me" in str(saved_welcome_link):
                branding_power_element = TextLink(channel_display_title, url=saved_welcome_link)
            else:
                branding_power_element = Text(channel_display_title)

            # 4. Synthesize structural premium message layout text context using your explicit Custom Emoji payload mappings
            live_fund_broadcast_content = Text(
                CustomEmoji("✅", custom_emoji_id="6298317205960397843"), 
                Bold(f" Total Remaining Fund In\n{bot_username_formatted} ➠ ₹{remaining_funds_clean:.2f}\n\n"),
                CustomEmoji("👑", custom_emoji_id="6118333272821865260"),
                Bold("Loot As Much As You Can"),
                CustomEmoji("🎀", custom_emoji_id="5375152498656961898"),
                "\n\n",
                CustomEmoji("🎁", custom_emoji_id="5442939099906325301"),
                Bold(" Specially Powered By "), 
                branding_power_element
            )

            # 5. Build premium inline button layout matching the exact design architecture requested
            button_label = f"{bot_username_formatted} ➠ ₹{remaining_funds_clean:.2f}"
            live_fund_markup_builder = InlineKeyboardBuilder()
            live_fund_markup_builder.add(types.InlineKeyboardButton(
                text=button_label,
                url=f"https://t.me/{me.username}",
                icon_custom_emoji_id="6068996425146965808"
            ))

            # 6. Execute direct transmission to the configured welcome channel destination
            try:
                kwargs_payload = live_fund_broadcast_content.as_kwargs()
                kwargs_payload["reply_markup"] = live_fund_markup_builder.as_markup()
                kwargs_payload["link_preview_options"] = types.LinkPreviewOptions(is_disabled=True)
                
                await message.bot.send_message(chat_id=int(channel_target_id), **kwargs_payload)
                await message.answer("<b>🚀 Live Fund announcement successfully transmitted to your welcome channel network!</b>", parse_mode="HTML")
            except Exception as dispatch_err:
                await message.answer(f"<b>❌ Dispatch Failed: Couldn't send message to target channel. Ensure the bot is an admin inside it! Log: {dispatch_err}</b>", parse_mode="HTML")

    # =================================================================
    # Long-Polling Initialization Start
    # =================================================================
    try:
        # ✅ FIXED: Explicitly force the cloned dispatcher to receive chat join request update packages
        await cloned_dp.start_polling(cloned_bot, allowed_updates=["message", "callback_query", "chat_join_request"])
    except Exception as polling_err:
        print(f"Operational long-polling error caught inside runtime context: {polling_err}")

# The authorized administrator user identifier
OWNER_ID = 8662999892

@dp.message(Command("cleardata"))
async def cmd_clear_data(message: types.Message):
    # Security checkpoint: Validate if the sender matches the owner profile restriction
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ **Unauthorized Access!** This administrative option is restricted to the system owner only.")
        return

    # Create confirmation formatting ledger using your premium emojis layout
    progress_msg = await message.answer("⏳ **Purging all isolated workspace matrices and wiping database registries...**")

    try:
        # Use a single connection pool cleanly to clear out all system dependencies
        async with aiosqlite.connect(DB_NAME) as db:
            # 1. ✅ FIXED: Added all missing tracking structures to prevent old data leaks from ghost entries
            tables_to_clear = [
                "child_bot_settings", 
                "child_gateways", 
                "cloned_bots",
                "user_balances",
                "user_bonus_cooldowns",
                "user_verification",
                "user_linked_wallets",
                "user_referrals"
            ]
            
            for table in tables_to_clear:
                await db.execute(f"DROP TABLE IF EXISTS {table}")
            await db.commit()
            
            # 2. Reset the system sequence mapping matrices entirely
            await db.execute("DELETE FROM sqlite_sequence")
            await db.commit()
            
            # 3. Clean up the disk file footprints instantly by defragmenting the storage layer
            await db.execute("VACUUM")
            await db.commit()

        # Build dynamic completion layout with bold rows matching your specific design format
        success_content = Text(
            CustomEmoji("🎉", custom_emoji_id="4996755833950831347"), 
            Bold(" System Database Cleared Safely!\n\n"),
            CustomEmoji("✅", custom_emoji_id="6267008582294705964"), 
            Bold(" All cloned bots, balances, logs, and cooldown parameters have been wiped cleanly.\n\n"),
            CustomEmoji("🔄", custom_emoji_id="6068806600477383919"),
            Bold(" NOTE: Please restart your terminal script now to flush active bot instances from your server's memory completely.")
        )
        
        await progress_msg.delete()
        await message.answer(**success_content.as_kwargs())

    except Exception as e:
        try:
            await progress_msg.edit_text(f"❌ **An unexpected storage failure occurred during execution:**\n`{str(e)}`")
        except Exception:
            await message.answer(f"❌ **An unexpected storage failure occurred during execution:**\n`{str(e)}`")

@dp.message(Command("botping"))
async def cmd_bot_ping(message: types.Message):
    # 1. Security Checkpoint
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ **Unauthorized Access Blocked.**")
        return

    import time
    from datetime import datetime

    # 2. Compute Execution Ping
    start_ping = time.time()
    progress_indicator = await message.answer("⚡ Checking system heartbeat...")
    end_ping = time.time()
    
    # Calculate Latency: Time taken for the bot to edit/delete the message
    api_latency = (end_ping - start_ping) * 1000
    execution_ping = end_ping - start_ping

    # 3. Pull live active user metrics from the database matrix
    async with aiosqlite.connect(DB_NAME) as db:
        # ✅ FIXED: Counting users from user_verification ensures every user is counted, 
        # not just those who have claimed a balance.
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM user_verification") as cursor:
            row = await cursor.fetchone()
            active_users = row[0] if row else 0

    # 4. Compute Structural System Uptime Duration
    current_time_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
    uptime_duration = current_time_ist - START_TIME_IST
    
    total_seconds = int(uptime_duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    uptime_string = f"{days}d {hours}h {minutes}m {seconds}s"
    started_on_string = START_TIME_IST.strftime("%Y-%m-%d %I:%M:%S %p")

    # 5. Construct the high-tech matrix layout
    ping_panel_content = Text(
        "╭───〔 ", CustomEmoji("🤖", custom_emoji_id="5372981976804366741"), " Bot Statistics 〕───╮\n\n",
        CustomEmoji("⚡", custom_emoji_id="6068806600477383919"), " Ping              » ", Bold(f"{execution_ping:.3f} s"), "\n",
        CustomEmoji("🎀", custom_emoji_id="5375203677487248777"), " API Latency       » ", Bold(f"{api_latency:.2f} ms"), "\n",
        CustomEmoji("⏳", custom_emoji_id="5017179932451668652"), " Uptime            » ", Bold(uptime_string), "\n",
        CustomEmoji("📅", custom_emoji_id="5274055917766202507"), " Started On        » ", Bold(started_on_string), "\n",
        CustomEmoji("🎉", custom_emoji_id="4996755833950831347"), " Total User        » ", Bold(str(active_users)), "\n",
        CustomEmoji("👑", custom_emoji_id="6118333272821865260"), " Owner             » ", TextLink("Administrator", url=f"tg://user?id={OWNER_ID}"), "\n",
        CustomEmoji("🛡️", custom_emoji_id="5251203410396458957"), " Security          » ", CustomEmoji("✅", custom_emoji_id="6267008582294705964"), " ", Bold("Protected\n\n"),
        "╰──────────────────────────╯"
    )

    try:
        await progress_indicator.delete()
    except Exception:
        pass

    await message.answer(**ping_panel_content.as_kwargs())

# -----------------------------------------------------------------
# Main Bot Admin Panel: Master Bot Catalog & Purge Engine
# -----------------------------------------------------------------

@dp.message(Command("allbot"))
async def cmd_view_all_cloned_bots(message: types.Message):
    # 1. Security Checkpoint: Enforce strictly restricted administrative visibility
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ **Unauthorized Access!** This view is reserved for the system owner only.")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, bot_username, theme, created_at, user_id FROM cloned_bots ORDER BY id DESC") as cursor:
            bots_records = await cursor.fetchall()

    if not bots_records:
        await message.answer("<b>📂 No active cloned bots found inside the platform registries.</b>", parse_mode="HTML")
        return

    await message.answer(f"📦 <b>Retrieving all deployed child instances ({len(bots_records)} total)...</b>", parse_mode="HTML")

    # 2. Iterate and render separate descriptive cards for every live instance
    for record in bots_records:
        db_id, username, theme, created_at, creator_id = record
        
        card_layout_text = (
            f"╭───〔 🤖 <b>Bot Deployment Details</b> 〕───╮\n\n"
            f"🆔 <b>Database Index  »</b> <code>{db_id}</code>\n"
            f"🔗 <b>Bot Username    »</b> {username}\n"
            f"⚡ <b>Selected Theme  »</b> <code>{theme}</code>\n"
            f"👤 <b>Deployer ID     »</b> <code>{creator_id}</code>\n"
            f"📅 <b>Created On       »</b> <code>{created_at}</code>\n\n"
            f"╰──────────────────────────╯"
        )

        # Build individual secure callback trigger mapping onto the database ID
        delete_markup_builder = InlineKeyboardBuilder()
        delete_markup_builder.add(types.InlineKeyboardButton(
            text="🗑️ Delete Bot", 
            callback_data=f"purge_bot_target_{db_id}"
        ))

        await message.answer(text=card_layout_text, parse_mode="HTML", reply_markup=delete_markup_builder.as_markup())
        await asyncio.sleep(0.1) # Smooth pacing stream overhead protection


@dp.callback_query(F.data.startswith("purge_bot_target_"))
async def process_cloned_bot_purge_callback(callback_query: types.CallbackQuery):
    # 1. Re-verify runtime ownership authorizations before committing any disk mutations
    if callback_query.from_user.id != OWNER_ID:
        await callback_query.answer("❌ Access Refused. Administrative clearance required.", show_alert=True)
        return

    # Extract targeted database sequence key identifier out of payload string layout
    target_db_id = int(callback_query.data.split("_")[3])

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Check row properties to verify identity context logs for console output tracking
            async with db.execute("SELECT bot_username FROM cloned_bots WHERE id = ?", (target_db_id,)) as cursor:
                bot_row = await cursor.fetchone()
            
            target_username = bot_row[0] if bot_row else f"Index #{target_db_id}"

            # Execute drop query permanently clearing out configuration parameters from workspace ledgers
            await db.execute("DELETE FROM cloned_bots WHERE id = ?", (target_db_id,))
            await db.commit()

        # 2. Instant interface sanitation updates
        try:
            await callback_query.message.delete()
        except Exception:
            pass

        await callback_query.answer(f"✅ Successfully deleted {target_username} registry entries permanently.", show_alert=True)
        print(f"⚙️ Administrative Master Control cleanly purged cloned bot entry {target_username} from server files.")

    except Exception as runtime_error:
        await callback_query.answer(f"❌ Database execution failure: {runtime_error}", show_alert=True)

# Updated handler to perfectly catch your exact styled button text
@dp.message(lambda message: message.text == "Cʀᴇᴀᴛᴇ Bᴏᴛ")
async def handle_create_bot(message: types.Message):
    # Safely building text with premium emoji to prevent byte-offset crashes
    content = Text(
        CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
        " ",
        Bold("Select Which Type Of Bot!")
    )
    
    await message.answer(
        **content.as_kwargs(), 
        reply_markup=get_bot_type_keyboard()
    )

@dp.message(lambda message: message.text == "Back To Main Panel")
async def handle_back_to_main(message: types.Message):
    # Triggers your original main menu setup safely
    await send_welcome_message(message, get_main_menu_reply_keyboard())

# Handler to catch when the user presses "Wallet Bot" on the reply keyboard
@dp.message(lambda message: message.text == "Wallet Bot")
async def handle_wallet_bot_selection(message: types.Message):
    content = Text(
        CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
        " ",
        Bold("Select Which Type Of Wallet Bot!")
    )
    
    await message.answer(
        **content.as_kwargs(),
        reply_markup=get_wallet_bot_options_keyboard()
    )

# 3. Handler when user clicks "Premium Wallet Bot"
@dp.message(F.text == "Premium Wallet Bot")
async def handle_premium_wallet_bot(message: types.Message, state: FSMContext):
    await state.set_state(CloneBotForm.waiting_for_theme)
    
    caption = Text(
        CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
        " ",
        Bold("Configure your Premium Wallet Bot installation below:")
    )
    
    await message.answer_photo(
        photo="https://files.catbox.moe/j0xp8r.jpg",
        **caption.as_kwargs(),
        reply_markup=get_theme_selection_keyboard()
    )

# 1. Handler when the user clicks "Task Payment Bot" on the reply menu
@dp.message(F.text == "Task Payment Bot")
async def handle_task_payment_bot_request(message: types.Message, state: FSMContext):
    await state.set_state(TaskPaymentBotForm.waiting_for_theme)
    
    caption = Text(
        CustomEmoji("✨", custom_emoji_id="4999015678238262018"),
        " ",
        Bold("Configure your Task Payment Bot installation below:")
    )
    
    # Inline button to match your required custom properties
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Select Theme", 
        callback_data="select_task_bot_theme", 
        style="primary",
        icon_custom_emoji_id="6267008582294705964"
    ))
    
    await message.answer_photo(
        photo="https://ganga--link--ghhzdp9sv8hk.code.run/i/fhbyq3dy.jpg",
        **caption.as_kwargs(),
        reply_markup=builder.as_markup()
    )

# 5. Handler catching the sent Bot Token
@dp.message(StateFilter(CloneBotForm.waiting_for_token))
async def handle_token_input(message: types.Message, state: FSMContext):
    user_input = message.text.strip() if message.text else ""
    
    if ":" not in user_input or len(user_input) < 25:
        await message.answer("❌ Invalid Token format. Please send a valid Bot Token from @BotFather.")
        return

    # 1. Pre-check if the bot token already exists in the SQLite storage matrix
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id FROM cloned_bots WHERE bot_token = ?", (user_input,)) as cursor:
            existing_bot = await cursor.fetchone()
            
    if existing_bot:
        duplicate_error = (
            f'<tg-emoji emoji-id="6309980103753341998">❌</tg-emoji>'
            f" <b>This Bot Already Exists In Our Database.</b>"
        )
        await message.answer(text=duplicate_error, parse_mode="HTML")
        await state.clear()
        return

    loading_msg = await message.answer("⏳ Connecting to Bot API servers...")
    await asyncio.sleep(1.0)
    
    # Dynamically detect bot username using an isolated, explicitly closed session layer instance context
    try:
        from aiogram.client.default import DefaultBotProperties
        temp_bot = Bot(token=user_input, properties=DefaultBotProperties(parse_mode="HTML"))
        bot_user = await temp_bot.get_me()
        bot_username = f"@{bot_user.username}"
        await temp_bot.session.close()
    except Exception:
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await message.answer("❌ Failed to verify token. Please check your token or make sure it's valid from @BotFather.")
        return

    await loading_msg.edit_text("⚙️ Setting up database environment profiles...")
    await asyncio.sleep(1.0)
    try:
        await loading_msg.delete()
    except Exception:
        pass

    # Get Current Time in Indian Standard Time (IST)
    ist_tz = pytz.timezone('Asia/Kolkata')
    current_time_ist = datetime.now(ist_tz).strftime("%Y-%m-%d %I:%M:%S %p")

    theme_chosen = "Premium Wallet Bot"

    # Save to aiosqlite database and capture the auto-increment row id
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            INSERT INTO cloned_bots (user_id, bot_token, bot_username, theme, created_at) 
            VALUES (?, ?, ?, ?, ?)
        """, (message.from_user.id, user_input, bot_username, theme_chosen, current_time_ist))
        await db.commit()
        db_bot_id = cursor.lastrowid  # Grab the generated dynamic ID

    # Run the clone's worker loop instantly in the background thread context!
    asyncio.create_task(start_cloned_bot_worker(user_input, db_bot_id))

    # Success Response with Bold Rows and Custom Premium Emojis
    success_text = Text(
        CustomEmoji("🎉", custom_emoji_id="4996755833950831347"), Bold(" New Bot Deployed Successfully!\n\n"),
        CustomEmoji("🤖", custom_emoji_id="5372981976804366741"), Bold(f" Bot Username: {bot_username}\n"),
        CustomEmoji("⚡", custom_emoji_id="6068806600477383919"), Bold(f" Theme: {theme_chosen}\n"),
        CustomEmoji("💰", custom_emoji_id="5375296873982604963"), Bold(" Points Used: Free\n"),
        CustomEmoji("✅", custom_emoji_id="6267008582294705964"), Bold(f" Created On: {current_time_ist}\n\n"),
        CustomEmoji("🔐", custom_emoji_id="5296369303661067030"), Bold(" To Login Admin Panel Use : /adminpanel")
    )

    await message.answer(**success_text.as_kwargs(), reply_markup=get_main_menu_reply_keyboard())
    await state.clear()

# -----------------------------------------------------------------
# Main Bot Support Handler (No Link Preview)
# -----------------------------------------------------------------

@dp.message(F.text == "Cᴏɴᴛᴀᴄᴛ Sᴜᴘᴘᴏʀᴛ")
async def main_bot_contact_support(message: types.Message):
    support_text = (
        f"<b><tg-emoji emoji-id='6068806600477383919'>⚡</tg-emoji> 𝗡𝗲𝗲𝗱 𝗛𝗲𝗹𝗽?</b>\n"
        f"<b>╭━━━━━━━━━━━━━━━━━━╮</b>\n\n"
        f"<b><tg-emoji emoji-id='6300834808415130459'>➡️</tg-emoji> 𝗦𝘂𝗽𝗽𝗼𝗿𝘁: <a href='https://tg://openmessage?user_id=8156429182'>𝐀𝐌𝐀𝐍 𝐒𝐀𝐈𝐍𝐈 !!</a></b>\n\n"
        f"<b>╰━━━━━━━━━━━━━━━━━━╯</b>\n"
        f"<b><tg-emoji emoji-id='5465300082628763143'>💬</tg-emoji> 𝗙𝗮𝘀𝘁 • 𝗙𝗿𝗶𝗲𝗻𝗱𝗹𝘆 • 𝗥𝗲𝗹𝗶𝗮𝗯𝗹𝗲 𝗦𝘂𝗽𝗽𝗼𝗿𝘁</b>"
    )
    
    # Setting disable_web_page_preview=True removes the box seen in 7566.png
    await message.answer(text=support_text, parse_mode="HTML", disable_web_page_preview=True)

# -----------------------------------------------------------------
# Main Bot Purchase Points Handler
# -----------------------------------------------------------------

@dp.message(F.text == "Pᴜʀᴄʜᴀsᴇ Pᴏɪɴᴛs")
async def main_bot_purchase_points(message: types.Message):
    points_text = (
        f"<b><tg-emoji emoji-id='6267008582294705964'>✅</tg-emoji> All Type Of Bot Making Is Free Currently! Enjoy Our Service <tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji>.</b>\n\n"
        f"<b><tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> It's A Limited Time Offer!</b>"
    )
    
    await message.answer(text=points_text, parse_mode="HTML")

# -----------------------------------------------------------------
# Main Bot Statistics Handler
# -----------------------------------------------------------------

@dp.message(F.text == "Sᴛᴀᴛɪsᴛɪᴄs")
async def main_bot_statistics(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Global Stats
        async with db.execute("SELECT COUNT(*) FROM cloned_bots") as cursor:
            total_bots = (await cursor.fetchone())[0]
            
        async with db.execute("SELECT created_at FROM cloned_bots ORDER BY id DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
            last_bot_global = row[0] if row else "Coming Soon"

        # 2. User Stats
        async with db.execute("SELECT COUNT(*) FROM cloned_bots WHERE user_id = ?", (message.from_user.id,)) as cursor:
            user_bots_created = (await cursor.fetchone())[0]
            
        async with db.execute("SELECT created_at FROM cloned_bots WHERE user_id = ? ORDER BY id DESC LIMIT 1", (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            last_bot_user = row[0] if row else "Coming Soon"

    # Placeholder for Total Users (Assuming a 'users' table exists)
    total_users = 1 
    user_points = "0.00"

    stats_text = (
        f"<b><tg-emoji emoji-id='6309641561546168537'>📊</tg-emoji> Global Platform Statistics</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b><tg-emoji emoji-id='4942888689131848546'>👥</tg-emoji> Total Users: {total_users}</b>\n"
        f"<b><tg-emoji emoji-id='5372981976804366741'>🤖</tg-emoji> Total Bots Created: {total_bots}</b>\n"
        f"<b><tg-emoji emoji-id='5274055917766202507'>📅</tg-emoji> Last Bot Created: {last_bot_global}</b>\n\n"
        f"<b><tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji> Most Popular Theme: Premium Wallet Theme</b>\n\n"
        f"<b><tg-emoji emoji-id='4996755833950831347'>🎉</tg-emoji> Your Bot Statistics</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b><tg-emoji emoji-id='5375296873982604963'>💰</tg-emoji> Your Points: {user_points}</b>\n"
        f"<b><tg-emoji emoji-id='5296369303661067030'>🔐</tg-emoji> Total Bots You Created: {user_bots_created}</b>\n"
        f"<b><tg-emoji emoji-id='5274055917766202507'>📅</tg-emoji> Last Bot You Created: {last_bot_user}</b>\n"
        f"<b><tg-emoji emoji-id='5375152498656961898'>🎀</tg-emoji> Your Most Used Theme: Premium Wallet Bot Theme</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b><tg-emoji emoji-id='6309997365226903510'>🔗</tg-emoji> Bot Creator: 𝐀𝐌𝐀𝐍 𝐒𝐀𝐈𝐍𝐈 !!</b>\n\n"
        f"<b><tg-emoji emoji-id='4999015678238262018'>✨</tg-emoji> Keep Building Powerful Bots And Grow Your Network!</b>\n\n"
        f"<b><tg-emoji emoji-id='6300651726844204536'>🚀</tg-emoji> Be A Proud User Of The Rapid Auto  Maker Bot!</b>"
    )
    
    await message.answer(text=stats_text, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "check_membership")
async def process_verification(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_joined = await is_user_member(user_id)
    
    if user_joined:
        await callback_query.message.delete()
        await send_welcome_message(callback_query.message, get_main_menu_reply_keyboard())
        await callback_query.answer("Verification Successful! Welcome.")
    else:
        await callback_query.answer(
            text="❌ You haven't joined all required channels yet!", 
            show_alert=True
        )

# 4. Callback Handler when user clicks "Select Theme" - Deletes image and sends prompt
@dp.callback_query(F.data == "select_premium_theme", StateFilter(CloneBotForm.waiting_for_theme))
async def handle_theme_selection(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(CloneBotForm.waiting_for_token)
    
    # Delete the previous photo message to clear clutter
    try:
        await callback_query.message.delete()
    except TelegramBadRequest:
        pass  # Prevents crash if the message was already deleted or missing
    
    prompt_text = Text(
        CustomEmoji("✅", custom_emoji_id="6267008582294705964"),
        " ",
        Bold("Please Send Me Your Bot Token:")
    )
    
    # Send a clean new text message prompt
    await callback_query.message.answer(**prompt_text.as_kwargs())
    await callback_query.answer()

# 2. Callback Handler when clicking "Select Theme" under Task Payment Bot
@dp.callback_query(F.data == "select_task_bot_theme", StateFilter(TaskPaymentBotForm.waiting_for_theme))
async def handle_task_theme_selection(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(TaskPaymentBotForm.waiting_for_token)
    
    try:
        await callback_query.message.delete()
    except TelegramBadRequest:
        pass  
    
    prompt_text = Text(
        CustomEmoji("✅", custom_emoji_id="6267008582294705964"),
        " ",
        Bold("Please Send Me Your Bot Token:")
    )
    
    await callback_query.message.answer(**prompt_text.as_kwargs())
    await callback_query.answer()

@dp.message(lambda message: message.text in ["🤖 Mʏ Bᴏᴛs", "📡 Bʀᴏᴀᴅᴄᴀsᴛ Hᴜʙ", "📈 Sᴛᴀᴛɪsᴛɪᴄs", "💳 Pᴜʀᴄʜᴀsᴇ Pᴏɪɴᴛs", "💬 Cᴏɴᴛᴀᴄᴛ Sᴜᴘᴘᴏʀᴛ"])
async def handle_menu_options(message: types.Message):
    await message.answer(f"You opened: {message.text}")

async def main():
    # 1. Initialize tables and run essential structural migrations
    await init_db()
    await init_system_tables()
    await init_gift_code_tables()
    await migrate_database()
    
    # Executing dynamic structural upgrades to fix the missing 'id' column safely
    print("⚙️ Checking for missing database table columns...")
    async with aiosqlite.connect(DB_NAME) as db:
        # Check gift_codes table schema properties
        async with db.execute("PRAGMA table_info(gift_codes)") as cursor:
            gift_cols = [row[1] for row in await cursor.fetchall()]
        
        if gift_cols:
            # If 'id' is completely missing, we perform a clean table rebuild migration
            if "id" not in gift_cols:
                print("⚠️ Table 'gift_codes' is missing its 'id' primary key. Rebuilding table structures safely...")
                # 1. Rename existing legacy table
                await db.execute("ALTER TABLE gift_codes RENAME TO old_gift_codes")
                
                # 2. Re-create the correct structural layout with standard auto-increment primary keys
                await db.execute("""
                    CREATE TABLE gift_codes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot_id INTEGER DEFAULT 0,
                        code TEXT,
                        amount REAL,
                        req_referrals INTEGER DEFAULT 0,
                        max_uses INTEGER DEFAULT 1,
                        current_uses INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'Active',
                        UNIQUE(bot_id, code)
                    )
                """)
                
                # 3. Dynamically read existing legacy columns to safely map database values across migrations
                has_bot_id = "bot_id" in gift_cols
                has_status = "status" in gift_cols
                has_max_uses = "max_uses" in gift_cols
                has_current_uses = "current_uses" in gift_cols
                has_req_ref = "req_referrals" in gift_cols

                select_cols = ["code", "amount"]
                insert_cols = ["code", "amount"]
                
                if has_bot_id: select_cols.append("bot_id"); insert_cols.append("bot_id")
                if has_status: select_cols.append("status"); insert_cols.append("status")
                if has_max_uses: select_cols.append("max_uses"); insert_cols.append("max_uses")
                if has_current_uses: select_cols.append("current_uses"); insert_cols.append("current_uses")
                if has_req_ref: select_cols.append("req_referrals"); insert_cols.append("req_referrals")
                
                select_str = ", ".join(select_cols)
                insert_str = ", ".join(insert_cols)
                
                # Copy live elements into newly structured matrix
                await db.execute(f"INSERT INTO gift_codes ({insert_str}) SELECT {select_str} FROM old_gift_codes")
                # Drop backup mirror cleanly
                await db.execute("DROP TABLE old_gift_codes")
                await db.commit()
                print("✅ Table 'gift_codes' structural primary key rebuild completed successfully!")
            else:
                # Add individual missing columns normally if 'id' already exists but others are absent
                if "bot_id" not in gift_cols:
                    await db.execute("ALTER TABLE gift_codes ADD COLUMN bot_id INTEGER DEFAULT 0")
                    await db.commit()
                if "status" not in gift_cols:
                    await db.execute("ALTER TABLE gift_codes ADD COLUMN status TEXT DEFAULT 'Active'")
                    await db.commit()
                if "max_uses" not in gift_cols:
                    await db.execute("ALTER TABLE gift_codes ADD COLUMN max_uses INTEGER DEFAULT 1")
                    await db.commit()
                if "current_uses" not in gift_cols:
                    await db.execute("ALTER TABLE gift_codes ADD COLUMN current_uses INTEGER DEFAULT 0")
                    await db.commit()
                if "req_referrals" not in gift_cols:
                    await db.execute("ALTER TABLE gift_codes ADD COLUMN req_referrals INTEGER DEFAULT 0")
                    await db.commit()

        # Check and migrate claimed_gift_codes table schema
        async with db.execute("PRAGMA table_info(claimed_gift_codes)") as cursor:
            claimed_cols = [row[1] for row in await cursor.fetchall()]
        if claimed_cols and "bot_id" not in claimed_cols:
            await db.execute("ALTER TABLE claimed_gift_codes ADD COLUMN bot_id INTEGER DEFAULT 0")
            await db.commit()
            print("Successfully migrated 'claimed_gift_codes' table to add 'bot_id' column!")
   
    # 2. Automatically scan storage and spin up active dynamic clone instances
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            async with db.execute("SELECT bot_token, id FROM cloned_bots") as cursor:
                async for row in cursor:
                    token, db_id = row
                    print(f"🔄 Re-activating Cloned Bot ID {db_id}...")
                    asyncio.create_task(start_cloned_bot_worker(token, db_id))
                    await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ Error restoring cloned bots on startup: {e}")

    # 3. Spin up the mainframe statistics web server
    from aiohttp import web
    import json

    # 1. Clear Webhook for the Main Master Control Bot
    print("🤖 Clearing active webhook for the Master Bot...")
    await bot.delete_webhook(drop_pending_updates=True)

    # 2. Clear Webhooks for all active Cloned Bots dynamically
    print("⚙️ Scanning and purging conflicting webhooks from Cloned Bots...")
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT bot_token FROM cloned_bots") as cursor:
                async for row in cursor:
                    try:
                        # Temporary clone instance just to tear down its conflicting webhook
                        clone_bot = Bot(token=row['bot_token'])
                        await clone_bot.delete_webhook(drop_pending_updates=True)
                        await clone_bot.session.close() # Always close short-lived sessions
                    except Exception as clone_err:
                        print(f"⚠️ Could not clear webhook for clone: {str(clone_err)}")
    except Exception as db_err:
        print(f"❌ Database error checking clone webhooks: {str(db_err)}")

    # 3. Mainframe Stats API Endpoints Initialization
    async def handle_mainframe_stats(request):
        try:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT COUNT(*) FROM cloned_bots") as cursor:
                    row = await cursor.fetchone()
                    total_clones = row[0] if row else 0
                async with db.execute("SELECT COUNT(DISTINCT user_id) FROM user_balances") as cursor:
                    row = await cursor.fetchone()
                    active_users = row[0] if row else 0
            
            payload = {
                "total_clones": total_clones,
                "active_users": active_users,
                "total_gateways": 2
            }
            return web.Response(
                text=json.dumps(payload), 
                content_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"}
            )
        except Exception as route_err:
            return web.Response(text=json.dumps({"error": str(route_err)}), status=500)

    server_app = web.Application()
    server_app.router.add_get('/api/mainframe-stats', handle_mainframe_stats)
    runner = web.AppRunner(server_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    asyncio.create_task(site.start())
    print("🌐 Statistics API server listening at http://0.0.0.0:8080/api/mainframe-stats")

    # 4. Launch long-polling loop for the master control bot safely
    print("🚀 Master Control Panel Bot polling sequence initialized...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_join_request"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Bot system execution manually halted safely.")

