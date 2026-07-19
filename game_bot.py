import logging
import psycopg2
import psycopg2.extensions
import aiopg
import asyncio
import os
import random
import requests
import urllib.parse
from datetime import datetime, timedelta, timezone
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    WebAppInfo, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# --- Force PostgreSQL to accept Emojis and Special Characters ---
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

# --- Configuration ---
# ADD YOUR NEW GAME BOT TOKEN HERE:
TOKEN = "8659779936:AAE5IU6UAoDuY4XNrJxiGr9JgWkT5j14cbY" 

DATABASE_URL = "postgresql://postgres:nikhil2008@127.0.0.1:5432/railway"
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://mini-app-2-kappa.vercel.app/')

admin_ids_raw = os.getenv('ADMIN_IDS', '6197579049')
ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(',') if x.strip().isdigit()]

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def get_ist_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

# --- Database Pool Setup ---
db_pool = None

async def init_db():
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            # Users, config, channels tables are shared with Task Bot
            await cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance FLOAT DEFAULT 0.0,
                referred_by BIGINT,
                upi_id TEXT,
                is_banned INT DEFAULT 0,
                device_verified INT DEFAULT 0,
                device_token TEXT,
                hw_id TEXT
            )''')

            await cursor.execute('''CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')

            await cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
                chat_id TEXT PRIMARY KEY,
                invite_link TEXT
            )''')

            # Unique to Game Bot
            await cursor.execute('''CREATE TABLE IF NOT EXISTS deposits (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount FLOAT,
                utr TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )''')
            await cursor.execute("COMMIT")
            
            # Initial Game Bot defaults (Prefixed with g_ so they don't overwrite task bot)
            await set_config('g_menu_text', 'Welcome to the Game Bot! 🎮 Multiply your balance today!', init=True)
            await set_config('g_bot_status', 'ON', init=True)
            await set_config('g_instant_wd_status', 'ON', init=True)
            await set_config('g_manual_wd_status', 'ON', init=True)
            await set_config('g_min_wd', '10', init=True)
            await set_config('g_max_wd', '10000', init=True)
            await set_config('g_wd_tax', '0', init=True)
            await set_config('g_min_bet', '10', init=True)
            await set_config('g_max_bet', '5000', init=True)
            await set_config('wingo_win_rate', '40', init=True)
            await set_config('deposit_qr', 'https://via.placeholder.com/300?text=Set+QR+In+Admin', init=True)

async def setup_db(application: Application):
    global db_pool
    try:
        db_pool = await aiopg.create_pool(DATABASE_URL, minsize=1, maxsize=10, client_encoding='utf8')
        logger.info("Database connection pool created successfully!")
        await init_db()
    except Exception as e:
        logger.error(f"Failed to create database pool: {e}")
        raise

async def db_query(query, params=(), commit=False, fetchall=False, fetchone=False):
    pg_query = query.replace('?', '%s')
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(pg_query, params)
                res = None
                if fetchall: res = await cursor.fetchall()
                elif fetchone: res = await cursor.fetchone()
                if commit: await cursor.execute("COMMIT")
                return res
            except Exception as e:
                if commit: await cursor.execute("ROLLBACK")
                logger.error(f"DB Query Error: {e}")
                raise

async def set_config(key, value, init=False):
    check = await db_query("SELECT value FROM config WHERE key = ?", (key,), fetchone=True)
    if check:
        if not init:
            await db_query("UPDATE config SET value = ? WHERE key = ?", (value, key), commit=True)
    else:
        await db_query("INSERT INTO config (key, value) VALUES (?, ?)", (key, value), commit=True)

async def check_user_joined_channels(bot, user_id):
    channels = await db_query("SELECT chat_id FROM channels", fetchall=True)
    if not channels: return True
    for row in channels:
        try:
            c_id = int(row[0]) if str(row[0]).lstrip('-').isdigit() else row[0].strip()
            member = await bot.get_chat_member(chat_id=c_id, user_id=user_id)
            if member.status in ['left', 'kicked']: return False
        except: return False
    return True

async def get_channel_verification_keyboard():
    channels = await db_query("SELECT invite_link FROM channels", fetchall=True)
    keyboard = []
    row = []
    for i, row_data in enumerate(channels):
        row.append(InlineKeyboardButton(f"🔗 Join Channel {i+1}", url=row_data[0]))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🟢 Verify Channels", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

def get_webapp_verify_keyboard(bot_username, safe_name, user_id):
    url = f"{WEBAPP_URL.rstrip('/')}/index.html?v={int(datetime.now().timestamp())}&bot={bot_username}&name={safe_name}&uid={user_id}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Verify Your Device", web_app=WebAppInfo(url=url))]])

def get_main_menu_keyboard(user_id):
    keyboard = [
        [KeyboardButton("🎮 PLAY GAMES 🎮", style="success")],
        [KeyboardButton("📥 Deposit", style="primary"), KeyboardButton("💰 Wallet", style="primary")],
        [KeyboardButton("💸 Withdraw", style="danger"), KeyboardButton("💳 Pay To User", style="danger")],
        [KeyboardButton("📊 Detailed Odds", style="success"), KeyboardButton("📞 Support", style="success")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Admin Panel ---
async def get_admin_panel_text():
    c = {}
    keys = ['g_min_wd', 'g_max_wd', 'g_wd_tax', 'g_min_bet', 'g_max_bet', 'wingo_win_rate', 'g_instant_wd_status', 'g_manual_wd_status']
    for k in keys:
        row = await db_query("SELECT value FROM config WHERE key=?", (k,), fetchone=True)
        c[k] = row[0] if row else 'N/A'

    return (
        "⚙️ **Game Bot Admin Panel**\n\n"
        f"📉 Min WD: `₹{c['g_min_wd']}` | 📈 Max WD: `₹{c['g_max_wd']}`\n"
        f"💸 WD Tax: `₹{c['g_wd_tax']}`\n"
        f"🎲 Min Bet: `₹{c['g_min_bet']}` | 🎰 Max Bet: `₹{c['g_max_bet']}`\n"
        f"🎯 Wingo Win Rate: `{c['wingo_win_rate']}%`\n"
        f"⚡ Instant WD: `[{c['g_instant_wd_status']}]` | 🏦 Manual WD: `[{c['g_manual_wd_status']}]`"
    )

def get_admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Mod Balance", callback_data="adm_mod_bal"), InlineKeyboardButton("🎰 Wingo Rate", callback_data="adm_wingo_rate")],
        [InlineKeyboardButton("📝 Main Menu Text", callback_data="adm_chg_text"), InlineKeyboardButton("🔴 Toggle Bot", callback_data="adm_tog_bot")],
        [InlineKeyboardButton("⚡ Toggle Inst WD", callback_data="adm_tog_inst_wd"), InlineKeyboardButton("🏦 Toggle Manu WD", callback_data="adm_tog_manu_wd")],
        [InlineKeyboardButton("📉 Min WD", callback_data="adm_min_wd"), InlineKeyboardButton("📈 Max WD", callback_data="adm_max_wd")],
        [InlineKeyboardButton("💸 WD Tax", callback_data="adm_wd_tax"), InlineKeyboardButton("🏆 Top 10 Bal", callback_data="adm_top_bal")],
        [InlineKeyboardButton("🔴 Ban User", callback_data="adm_ban"), InlineKeyboardButton("🟢 Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("🎲 Min Bet", callback_data="adm_min_bet"), InlineKeyboardButton("🎰 Max Bet", callback_data="adm_max_bet")],
        [InlineKeyboardButton("🏧 WD Requests", callback_data="adm_list_wd"), InlineKeyboardButton("🔍 WD Lookup", callback_data="adm_wd_lookup")],
        [InlineKeyboardButton("📥 Dep Requests", callback_data="adm_list_dep"), InlineKeyboardButton("🔍 Dep Lookup", callback_data="adm_dep_lookup")],
        [InlineKeyboardButton("🖼️ Set Deposit QR", callback_data="adm_set_dep_qr"), InlineKeyboardButton("❌ Close", callback_data="close_panel")]
    ])

# --- Core Bot Startup Flow ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, username = update.effective_user.id, update.effective_user.username or "Unknown"

    bot_status = (await db_query("SELECT value FROM config WHERE key='g_bot_status'", fetchone=True))[0]
    if bot_status == 'OFF' and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Bot is in Maintenance mode.")
        return

    user = await db_query("SELECT is_banned, device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if user and user[0] == 1:
        await update.message.reply_text("❌ Access Denied.")
        return

    if not user:
        ref_id = int(context.args[0]) if context.args and context.args[0].isdigit() else None
        await db_query(
            "INSERT INTO users (user_id, username, referred_by, device_verified) VALUES (?, ?, ?, 0) ON CONFLICT (user_id) DO NOTHING",
            (user_id, username, ref_id), commit=True
        )
        device_verified = 0
    else:
        device_verified = user[1]

    if context.args and context.args[0].startswith("v_"):
        hw_id = context.args[0][2:]
        existing = await db_query("SELECT user_id FROM users WHERE hw_id = ? AND user_id != ?", (hw_id, user_id), fetchone=True)
        if existing:
            await update.message.reply_text("❌ **Security Violation**\nDevice linked to another account.", parse_mode="Markdown")
            return
        await db_query("UPDATE users SET device_verified=1, hw_id=? WHERE user_id=?", (hw_id, user_id), commit=True)
        device_verified = 1
        await update.message.reply_text("✅ *Device Verified!*", parse_mode="Markdown")

    if device_verified == 1:
        menu_text = (await db_query("SELECT value FROM config WHERE key='g_menu_text'", fetchone=True))[0]
        await update.message.reply_text(menu_text, reply_markup=get_main_menu_keyboard(user_id))
        return

    if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Join channels first:", reply_markup=await get_channel_verification_keyboard())
        return

    bot_user = await context.bot.get_me()
    safe_name = urllib.parse.quote(update.effective_user.first_name or "User")
    await update.message.reply_text(
        "🔒 *Verify Yourself To Start Bot*\nClick below for device security check.",
        parse_mode="Markdown", reply_markup=get_webapp_verify_keyboard(bot_user.username, safe_name, user_id)
    )

# --- UI Callback Intercepts ---
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    data = query.data

    if data == "close_panel":
        await query.message.delete()
        return

    # Channel Check
    if data == "check_membership":
        if await check_user_joined_channels(context.bot, user_id):
            user = await db_query("SELECT device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
            if not user[0] and user_id not in ADMIN_IDS:
                bot_user = await context.bot.get_me()
                safe_name = urllib.parse.quote(query.from_user.first_name or "User")
                await query.message.edit_text(
                    "✅ Channels Joined!\n\n🔒 *Verify Yourself To Start Bot*", 
                    parse_mode="Markdown", reply_markup=get_webapp_verify_keyboard(bot_user.username, safe_name, user_id)
                )
            else:
                menu_text = (await db_query("SELECT value FROM config WHERE key='g_menu_text'", fetchone=True))[0]
                await query.message.delete()
                await context.bot.send_message(chat_id=user_id, text="✅ Verification Complete!\n" + menu_text, reply_markup=get_main_menu_keyboard(user_id))
        else:
            await query.message.edit_text("❌ Join all channels.", reply_markup=await get_channel_verification_keyboard())
        return

    # --- GAMES SYSTEM ---
    if data.startswith("play_"):
        game = data.split("_")[1]
        context.user_data['temp_game'] = {'type': game}
        
        if game in ['dice', 'bowl', 'wingo']:
            kb = [
                [InlineKeyboardButton("Low Difficulty", style="success", callback_data=f"diff_{game}_low")],
                [InlineKeyboardButton("High Difficulty", style="danger", callback_data=f"diff_{game}_high")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
            ]
            await query.message.edit_text(f"Select Difficulty for {game.capitalize()}:", reply_markup=InlineKeyboardMarkup(kb))
        
        elif game == 'dart':
            kb = [
                [InlineKeyboardButton("🔴 Red", callback_data="pick_dart_red"), InlineKeyboardButton("⚪ White", callback_data="pick_dart_white")],
                [InlineKeyboardButton("🎯 Center", callback_data="pick_dart_center")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
            ]
            await query.message.edit_text("🎯 Select Dart Outcome Target:", reply_markup=InlineKeyboardMarkup(kb))
            
    elif data.startswith("diff_"):
        _, game, diff = data.split("_")
        context.user_data['temp_game']['diff'] = diff
        
        if diff == "low":
            if game in ['dice', 'bowl']:
                kb = [[InlineKeyboardButton("🔵 Odd", callback_data=f"pick_{game}_odd"), InlineKeyboardButton("🔵 Even", callback_data=f"pick_{game}_even")]]
                await query.message.edit_text("Select Outcome Type:", reply_markup=InlineKeyboardMarkup(kb))
            elif game == 'wingo':
                kb = [
                    [InlineKeyboardButton("🔵 Odd", callback_data="pick_wingo_odd"), InlineKeyboardButton("🔵 Even", callback_data="pick_wingo_even")],
                    [InlineKeyboardButton("🟢 Big (5-9)", callback_data="pick_wingo_big"), InlineKeyboardButton("🔴 Small (0-4)", callback_data="pick_wingo_small")]
                ]
                await query.message.edit_text("🎰 Wingo Low Difficulty Selection:", reply_markup=InlineKeyboardMarkup(kb))
        
        elif diff == "high":
            if game in ['dice', 'bowl']:
                kb = [[InlineKeyboardButton(f"🔵 {i}", callback_data=f"pick_{game}_{i}") for i in range(1, 4)], [InlineKeyboardButton(f"🔵 {i}", callback_data=f"pick_{game}_{i}") for i in range(4, 7)]]
                await query.message.edit_text("Select Exact Number:", reply_markup=InlineKeyboardMarkup(kb))
            elif game == 'wingo':
                kb = [
                    [InlineKeyboardButton(f"🔵 {i}", callback_data=f"pick_wingo_{i}") for i in range(0, 5)],
                    [InlineKeyboardButton(f"🔵 {i}", callback_data=f"pick_wingo_{i}") for i in range(5, 10)]
                ]
                await query.message.edit_text("🎰 Wingo High Difficulty - Select Number (0-9):", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("pick_"):
        parts = data.split("_")
        game, choice = parts[1], parts[2]
        context.user_data['temp_game']['choice'] = choice
        
        c = {}
        for k in ['g_min_bet', 'g_max_bet']: c[k] = float((await db_query("SELECT value FROM config WHERE key=?", (k,), fetchone=True))[0])
        
        context.user_data['state'] = 'WAITING_BET_AMT'
        await query.message.edit_text(f"💸 **Enter amount to bet!**\n\n📉 Min Bet: `₹{c['g_min_bet']}`\n📈 Max Bet: `₹{c['g_max_bet']}`", parse_mode="Markdown")

    elif data == "cancel_action":
        context.user_data.clear()
        await query.message.edit_text("❌ Action Cancelled.")

    # --- Wallet Buttons ---
    elif data == "add_upi":
        context.user_data['state'] = 'WAITING_UPI'
        await query.message.reply_text("Send UPI:")
        
    elif data == "withdraw":
        kb = [
            [InlineKeyboardButton("⚡ Instant Withdrawal", callback_data="wd_instant")],
            [InlineKeyboardButton("🏦 Manual Withdrawal", callback_data="wd_manual")]
        ]
        await query.message.edit_text("Choose withdrawal method:", reply_markup=InlineKeyboardMarkup(kb))

    # --- Withdrawals & Deposits ---
    elif data in ["wd_instant", "wd_manual"]:
        wd_type = data.split('_')[1].upper()
        c_check = (await db_query(f"SELECT value FROM config WHERE key='g_{wd_type.lower()}_wd_status'", fetchone=True))[0]
        if c_check == 'OFF':
            await query.message.edit_text(f"⚠️ {wd_type} withdrawals are OFF.")
            return

        u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        if not u[1]: 
            await query.message.edit_text("❌ Please link your UPI ID in Wallet first.")
            return
            
        context.user_data['state'] = f'WAITING_WD_AMOUNT_{wd_type}'
        max_wd = float((await db_query("SELECT value FROM config WHERE key='g_max_wd'", fetchone=True))[0])
        await query.message.edit_text(f"Enter Amount for {wd_type} withdrawal (Wallet: ₹{u[0]:.2f}, Max/Txn: ₹{max_wd}):")

    elif data in ["wd_confirm", "wd_cancel"]:
        temp_wd = context.user_data.pop('temp_wd', None)
        if not temp_wd: return await query.message.edit_text("❌ Expired.")
        
        if data == "wd_cancel":
            await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (temp_wd['amount'], user_id), commit=True)
            return await query.message.edit_text("❌ Refunded to wallet.")
            
        elif data == "wd_confirm":
            await query.message.edit_text("⏳ Processing...")
            amt, a_amt, u_upi, w_type = temp_wd['amount'], temp_wd['actual_amount'], temp_wd['upi'], temp_wd['type']
            
            if w_type == 'MANUAL':
                if 'withdrawals' not in context.bot_data: context.bot_data['withdrawals'] = {}
                wid = str(int(datetime.now().timestamp()))
                context.bot_data['withdrawals'][wid] = {'user_id': user_id, 'amount': amt, 'upi': u_upi, 'time': get_ist_time()}
                await query.message.edit_text("✅ Manual WD Requested. Wait for admin.")
                
                adm_msg = f"🏧 **NEW MANUAL WD**\nID: `{wid}`\nUID: `{user_id}`\nUPI: `{u_upi}`\nAMT: `{amt}`"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Approve", callback_data=f"adm_app_w_{wid}"), InlineKeyboardButton("🔴 Reject", callback_data=f"adm_rej_w_{wid}")]])
                for a in ADMIN_IDS:
                    try: await context.bot.send_message(a, adm_msg, parse_mode="Markdown", reply_markup=kb)
                    except: pass
            elif w_type == 'INSTANT':
                api_url = (await db_query("SELECT value FROM config WHERE key='payment_api_url'", fetchone=True))
                if not api_url or not api_url[0]:
                    await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, user_id), commit=True)
                    return await query.message.edit_text("❌ API not set. Refunded.")
                
                f_url = api_url[0].replace("{upi id}", u_upi).replace("{amount}", str(a_amt))
                try:
                    resp = requests.get(f_url, timeout=15).json()
                    txn_id = str(resp.get('txnid') or resp.get('id') or "UNKNOWN")
                except: txn_id = "UNKNOWN"
                
                s_url = (await db_query("SELECT value FROM config WHERE key='payment_status_url'", fetchone=True))
                status_url = s_url[0] if s_url else ""
                
                qs = urllib.parse.urlencode({'uid': user_id, 'amt': a_amt, 'upi': u_upi, 'txnid': txn_id, 'api': status_url})
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Check Status", web_app=WebAppInfo(url=f"{WEBAPP_URL}/index1.html?{qs}"))]])
                await query.message.edit_text("YOUR WITHDRAWAL IS PAID ✅", reply_markup=btn)

    # --- Admin Callbacks ---
    elif data == "adm_set_dep_qr" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_SET_DEP_QR'
        await query.message.reply_text("📸 Please send the new Deposit QR Code as a Photo to set it:")

    elif data.startswith("adm_app_w_") or data.startswith("adm_rej_w_"):
        act, wid = data.split("_")[1], data.split("_")[3]
        wd = context.bot_data.get('withdrawals', {}).pop(wid, None)
        if wd:
            if act == 'app': status_msg = "APPROVED"
            else:
                await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (wd['amount'], wd['user_id']), commit=True)
                status_msg = "REJECTED"
            try: await context.bot.send_message(wd['user_id'], f"WITHDRAWAL STATUS: {status_msg}")
            except: pass
            await query.message.edit_text(f"✅ WD {wid} {status_msg}")
            
    elif data.startswith("adm_app_dep_") or data.startswith("adm_rej_dep_"):
        act, did = data.split("_")[2], data.split("_")[3]
        dep = await db_query("SELECT user_id, amount, status FROM deposits WHERE id=?", (int(did),), fetchone=True)
        if dep and dep[2] == 'pending':
            uid, amt = dep[0], dep[1]
            if act == 'app':
                await db_query("UPDATE deposits SET status='approved' WHERE id=?", (int(did),), commit=True)
                await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid), commit=True)
                try: await context.bot.send_message(uid, f"✅ Deposit of ₹{amt} APPROVED and credited!")
                except: pass
                await query.message.edit_text(f"✅ Deposit {did} APPROVED.")
            else:
                await db_query("UPDATE deposits SET status='rejected' WHERE id=?", (int(did),), commit=True)
                try: await context.bot.send_message(uid, f"❌ Deposit of ₹{amt} REJECTED.")
                except: pass
                await query.message.edit_text(f"❌ Deposit {did} REJECTED.")
        else: await query.message.edit_text("❌ Already processed.")

    elif user_id in ADMIN_IDS:
        admin_states = {
            "adm_mod_bal": "ADM_MOD_BAL", "adm_wingo_rate": "ADM_WINGO_RATE",
            "adm_chg_text": "ADM_CHG_TEXT", "adm_min_wd": "ADM_MIN_WD",
            "adm_max_wd": "ADM_MAX_WD", "adm_wd_tax": "ADM_WD_TAX",
            "adm_ban": "ADM_BAN", "adm_unban": "ADM_UNBAN",
            "adm_min_bet": "ADM_MIN_BET", "adm_max_bet": "ADM_MAX_BET",
            "adm_wd_lookup": "ADM_WD_LOOKUP", "adm_dep_lookup": "ADM_DEP_LOOKUP"
        }
        if data in admin_states:
            context.user_data['state'] = admin_states[data]
            await query.message.reply_text(f"Enter value for {data}:")
            
        elif data == "adm_list_wd":
            w = context.bot_data.get('withdrawals', {})
            if not w: return await query.message.reply_text("No pending WDs.")
            for k, v in w.items():
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🟢 App", callback_data=f"adm_app_w_{k}"), InlineKeyboardButton("🔴 Rej", callback_data=f"adm_rej_w_{k}")]])
                await query.message.reply_text(f"ID: `{k}`\nUID: {v['user_id']}\nAmt: ₹{v['amount']}\nUPI: `{v['upi']}`", reply_markup=kb, parse_mode="Markdown")
                
        elif data == "adm_list_dep":
            deps = await db_query("SELECT id, user_id, amount, utr, created_at FROM deposits WHERE status='pending'", fetchall=True)
            if not deps: return await query.message.reply_text("No pending deposits.")
            for d in deps:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🟢 App", callback_data=f"adm_app_dep_{d[0]}"), InlineKeyboardButton("🔴 Rej", callback_data=f"adm_rej_dep_{d[0]}")]])
                await query.message.reply_text(f"DEP ID: `{d[0]}`\nUID: {d[1]}\nAmt: ₹{d[2]}\nUTR: `{d[3]}`\nTime: {d[4]}", reply_markup=kb, parse_mode="Markdown")

        elif data.startswith("adm_tog_"):
            key_map = {"adm_tog_bot": "g_bot_status", "adm_tog_inst_wd": "g_instant_wd_status", "adm_tog_manu_wd": "g_manual_wd_status"}
            k = key_map[data]
            cur = (await db_query("SELECT value FROM config WHERE key=?", (k,), fetchone=True))[0]
            new_s = 'OFF' if cur == 'ON' else 'ON'
            await set_config(k, new_s)
            await query.message.reply_text(f"✅ {k} is now {new_s}")
            
        elif data == "adm_top_bal":
            t = await db_query("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
            await query.message.reply_text("\n".join([f"{i+1}) `{r[0]}` - ₹{r[1]:.2f}" for i, r in enumerate(t)]), parse_mode="Markdown")

async def execute_game_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float):
    user_id = update.effective_user.id
    game_data = context.user_data.pop('temp_game')
    game, choice = game_data['type'], game_data['choice']
    
    # 1. Deduct Immediately
    deducted = await db_query("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ? RETURNING balance", (amount, user_id, amount), commit=True, fetchone=True)
    if not deducted:
        return await update.message.reply_text("❌ Insufficient Balance.")

    chat_id = update.message.chat_id
    win = False
    payout_mult = 0.0

    if game == 'dice':
        msg = await context.bot.send_dice(chat_id, emoji='🎲')
        await asyncio.sleep(4)
        val = msg.dice.value
        
        if game_data['diff'] == 'low':
            payout_mult = 1.9
            win = (choice == 'even' and val % 2 == 0) or (choice == 'odd' and val % 2 != 0)
        else:
            payout_mult = 4.0
            win = (str(val) == choice)
            
    elif game == 'bowl':
        msg = await context.bot.send_dice(chat_id, emoji='🎳')
        await asyncio.sleep(4)
        val = msg.dice.value # 1-6
        
        if game_data['diff'] == 'low':
            payout_mult = 1.9
            win = (choice == 'even' and val % 2 == 0) or (choice == 'odd' and val % 2 != 0)
        else:
            payout_mult = 4.0
            win = (str(val) == choice)
            
    elif game == 'dart':
        msg = await context.bot.send_dice(chat_id, emoji='🎯')
        await asyncio.sleep(4)
        val = msg.dice.value # 1 miss, 2/4 white, 3/5 red, 6 center
        
        if choice == 'center':
            payout_mult = 2.9
            win = (val == 6)
        elif choice == 'red':
            payout_mult = 1.8
            win = (val in [2, 4]) # Fixed logic mapping!
        elif choice == 'white':
            payout_mult = 1.8
            win = (val in [3, 5]) # Fixed logic mapping!

    elif game == 'wingo':
        await context.bot.send_message(chat_id, "🎰 Drawing Wingo Result...")
        await asyncio.sleep(2)
        
        rate = float((await db_query("SELECT value FROM config WHERE key='wingo_win_rate'", fetchone=True))[0])
        is_win_roll = random.uniform(0, 100) < rate
        
        if game_data['diff'] == 'low':
            payout_mult = 1.8
            odd_pool, even_pool, big_pool, small_pool = [1,3,5,7,9], [0,2,4,6,8], [5,6,7,8,9], [0,1,2,3,4]
            
            if is_win_roll:
                win = True
                if choice == 'odd': val = random.choice(odd_pool)
                elif choice == 'even': val = random.choice(even_pool)
                elif choice == 'big': val = random.choice(big_pool)
                else: val = random.choice(small_pool)
            else:
                win = False
                if choice == 'odd': val = random.choice(even_pool)
                elif choice == 'even': val = random.choice(odd_pool)
                elif choice == 'big': val = random.choice(small_pool)
                else: val = random.choice(big_pool)
        else:
            payout_mult = 8.0
            if is_win_roll:
                win = True
                val = int(choice)
            else:
                win = False
                pool = [i for i in range(10) if str(i) != choice]
                val = random.choice(pool)
                
        await context.bot.send_message(chat_id, f"🎰 Wingo Result Drawn: **{val}**", parse_mode="Markdown")

    if win:
        won_amt = amount * payout_mult
        await db_query("UPDATE users SET balance = balance + ? WHERE user_id = ?", (won_amt, user_id), commit=True)
        await context.bot.send_message(chat_id, f"🎉 **CONGRATULATIONS!** 🎉\n\nYou won the bet!\n💰 `₹{won_amt:.2f}` has been credited to your wallet. Please check ✅", parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id, "😢 **YOU LOST**\n\nBetter luck next time!", parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return
    user_id = update.effective_user.id
    state = context.user_data.get('state')

    # Handle Photo Uploads for Admin Deposit QR
    if update.message.photo:
        if state == 'ADM_SET_DEP_QR' and user_id in ADMIN_IDS:
            file_id = update.message.photo[-1].file_id
            await set_config('deposit_qr', file_id)
            context.user_data['state'] = None
            await update.message.reply_text("✅ Deposit QR Photo Updated Successfully!")
        return

    # Skip if not text
    if not update.message.text: return
    text = update.message.text.strip()

    if text == "🎮 PLAY GAMES 🎮":
        kb = [
            [InlineKeyboardButton("🎲 Dice", callback_data="play_dice"), InlineKeyboardButton("🎳 Bowling", callback_data="play_bowl")],
            [InlineKeyboardButton("🎯 Dart", callback_data="play_dart"), InlineKeyboardButton("🎰 Wingo", callback_data="play_wingo")]
        ]
        await update.message.reply_text(
            "🎮 **Select a Game to Play!**\n\n⚠️ *Disclaimer: Neither the bot owner nor the bot will be responsible for any type of losses and profits.*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    elif text == "📥 Deposit":
        context.user_data['state'] = 'WAITING_DEPOSIT_AMT'
        await update.message.reply_text("💸 Enter the amount you want to deposit (e.g. 50):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]))
        return

    elif text == "💰 Wallet":
        u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        kb = [[InlineKeyboardButton("🔗 Link UPI", style="success", callback_data="add_upi")], [InlineKeyboardButton("💸 Withdraw", style="danger", callback_data="withdraw")]]
        await update.message.reply_text(f"💳 **Wallet Details**\n\n🆔 Account ID: `{user_id}`\n💰 Balance: `₹{u[0]:.2f}`\n🏦 UPI: `{u[1] or 'None'}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    elif text == "💸 Withdraw":
        kb = [[InlineKeyboardButton("⚡ Instant", callback_data="wd_instant")], [InlineKeyboardButton("🏦 Manual", callback_data="wd_manual")]]
        await update.message.reply_text("Choose method:", reply_markup=InlineKeyboardMarkup(kb))
        return
        
    elif text == "💳 Pay To User":
        context.user_data['state'] = 'WAITING_P2P'
        await update.message.reply_text("💸 Format -> `user_id:amount`", parse_mode="Markdown")
        return

    elif text == "📊 Detailed Odds":
        odds_msg = """**DICE/BOWL GAME ODDS :-**
ODD/EVEN - 1.9X WIN
NUMBER - 4X WIN

**DART GAME ODDS:-**
RED/WHITE - 1.8X WIN
CENTER - 2.9X WIN

**WINGO GAME ODDS:-**
ODD/EVEN/BIG(5-9)/SMALL(0-4) - 1.8X WIN
NUMBER - 8X WIN

FOR MORE INFO CONTACT SUPPORT !!"""
        await update.message.reply_text(odds_msg, parse_mode="Markdown")
        return

    elif text == "⚪ 📞 Support":
        context.user_data['state'] = 'SUPPORT_MSG'
        await update.message.reply_text("📝 Send a message you want to send to Admins:")
        return

    elif text == "⚙️ Admin Panel" and user_id in ADMIN_IDS:
        await update.message.reply_text(await get_admin_panel_text(), parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())
        return

    if not state: return
    context.user_data['state'] = None

    try:
        if state == 'WAITING_BET_AMT':
            try: amt = float(text)
            except: return await update.message.reply_text("❌ Invalid Amount.")
            
            c = {}
            for k in ['g_min_bet', 'g_max_bet']: c[k] = float((await db_query("SELECT value FROM config WHERE key=?", (k,), fetchone=True))[0])
            if amt < c['g_min_bet'] or amt > c['g_max_bet']: return await update.message.reply_text("❌ Limit Error.")
            
            await execute_game_logic(update, context, amt)

        elif state == 'WAITING_DEPOSIT_AMT':
            try: amt = float(text)
            except: return await update.message.reply_text("❌ Numbers only.")
            context.user_data['dep_amt'] = amt
            context.user_data['state'] = 'WAITING_DEPOSIT_UTR'
            
            qr_file_id = (await db_query("SELECT value FROM config WHERE key='deposit_qr'", fetchone=True))[0]
            if qr_file_id.startswith("http"): 
                await update.message.reply_photo(photo=qr_file_id, caption=f"SCAN TO PAY: **₹{amt}**\n\nAfter paying, enter the 12-digit UTR numeric reference number below:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]))
            else:
                await update.message.reply_photo(photo=qr_file_id, caption=f"SCAN TO PAY: **₹{amt}**\n\nAfter paying, enter the 12-digit UTR numeric reference number below:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]))

        elif state == 'WAITING_DEPOSIT_UTR':
            if not text.isdigit() or len(text) != 12:
                context.user_data['state'] = 'WAITING_DEPOSIT_UTR'
                return await update.message.reply_text("❌ WRONG UTR PLEASE ENTER CORRECT UTR TO PROCEED (12 Digits Numeric).")
                
            amt = context.user_data.pop('dep_amt')
            res = await db_query("INSERT INTO deposits (user_id, amount, utr, created_at) VALUES (?, ?, ?, ?) RETURNING id", (user_id, amt, text, get_ist_time()), commit=True, fetchone=True)
            did = res[0]
            
            await update.message.reply_text("⏳ Deposit submitted. Pending Admin Verification.")
            
            adm_msg = f"📥 **NEW DEPOSIT**\nID: `{did}`\nUID: `{user_id}`\nAMT: `₹{amt}`\nUTR: `{text}`\nTIME: `{get_ist_time()}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🟢 App", callback_data=f"adm_app_dep_{did}"), InlineKeyboardButton("🔴 Rej", callback_data=f"adm_rej_dep_{did}")]])
            for a in ADMIN_IDS:
                try: await context.bot.send_message(a, adm_msg, parse_mode="Markdown", reply_markup=kb)
                except: pass

        elif state == 'SUPPORT_MSG':
            for a in ADMIN_IDS:
                try: await context.bot.send_message(a, f"USER'S MESSAGE :- {user_id}:{text}")
                except: pass
            await update.message.reply_text("✅ Sent to Admins.")
            
        elif state == 'WAITING_P2P':
            if ":" not in text: return await update.message.reply_text("❌ Format: `uid:amt`")
            tid, tamt = text.split(":")
            tid, tamt = int(tid), float(tamt)
            if tamt <= 0: return await update.message.reply_text("❌ No negative deducts.")
            bal = (await db_query("SELECT balance FROM users WHERE user_id=?", (user_id,), fetchone=True))[0]
            if bal < tamt: return await update.message.reply_text("❌ Poor balance.")
            
            await db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (tamt, user_id), commit=True)
            await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (tamt, tid), commit=True)
            await update.message.reply_text(f"✅ ₹{tamt} sent to {tid}")

        # Shared states (UPI, WDs) logic from previous bot context fits exactly here.
        elif state == 'WAITING_UPI':
            await db_query("UPDATE users SET upi_id=? WHERE user_id=?", (text, user_id), commit=True)
            await update.message.reply_text("✅ UPI updated.")

        elif state.startswith('WAITING_WD_AMOUNT_'):
            wd_type = state.split('_')[3]
            amt = float(text)
            
            u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
            c = {}
            for k in ['g_min_wd', 'g_max_wd', 'g_wd_tax']: c[k] = float((await db_query("SELECT value FROM config WHERE key=?", (k,), fetchone=True))[0])
            
            if amt < c['g_min_wd'] or amt > c['g_max_wd']: return await update.message.reply_text("❌ Limit Error.")
            if amt > u[0]: return await update.message.reply_text("❌ Poor balance.")
            
            actual = amt if wd_type == 'MANUAL' else amt - c['g_wd_tax']
            await db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, user_id), commit=True)
            
            context.user_data['temp_wd'] = {'amount': amt, 'actual_amount': actual, 'type': wd_type, 'upi': u[1]}
            kb = [[InlineKeyboardButton("Confirm", callback_data="wd_confirm"), InlineKeyboardButton("🔴 Cancel", callback_data="wd_cancel")]]
            await update.message.reply_text(f"Confirm Withdraw ₹{amt} to `{u[1]}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        # Admin Config states
        elif state in ['ADM_WINGO_RATE', 'ADM_CHG_TEXT', 'ADM_MIN_WD', 'ADM_MAX_WD', 'ADM_WD_TAX', 'ADM_MIN_BET', 'ADM_MAX_BET']:
            key_map = {
                'ADM_WINGO_RATE': 'wingo_win_rate', 'ADM_CHG_TEXT': 'g_menu_text',
                'ADM_MIN_WD': 'g_min_wd', 'ADM_MAX_WD': 'g_max_wd', 'ADM_WD_TAX': 'g_wd_tax',
                'ADM_MIN_BET': 'g_min_bet', 'ADM_MAX_BET': 'g_max_bet'
            }
            await set_config(key_map[state], text)
            await update.message.reply_text("✅ Updated.")

        elif state == 'ADM_MOD_BAL':
            tid, tamt = text.split(":")
            await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (float(tamt), int(tid)), commit=True)
            await update.message.reply_text("✅ Bal updated.")

        elif state == 'ADM_BAN':
            await db_query("UPDATE users SET is_banned=1 WHERE user_id=?", (int(text),), commit=True)
            await update.message.reply_text("✅ Banned.")
            
        elif state == 'ADM_UNBAN':
            await db_query("UPDATE users SET is_banned=0 WHERE user_id=?", (int(text),), commit=True)
            await update.message.reply_text("✅ Unbanned.")

        elif state == 'ADM_WD_LOOKUP':
            v = context.bot_data.get('withdrawals', {}).get(text)
            if v: await update.message.reply_text(f"WD ID: `{text}`\nUID: {v['user_id']}\nAmt: {v['amount']}\nUPI: {v['upi']}", parse_mode="Markdown")
            else: await update.message.reply_text("❌ Not found in pending cache.")

        elif state == 'ADM_DEP_LOOKUP':
            d = await db_query("SELECT * FROM deposits WHERE id=?", (int(text),), fetchone=True)
            if d: await update.message.reply_text(f"DEP ID: {d[0]}\nUID: {d[1]}\nAmt: {d[2]}\nUTR: {d[3]}\nStatus: {d[4]}", parse_mode="Markdown")
            else: await update.message.reply_text("❌ Not found.")
            
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Processing Error.")

def main():
    app = Application.builder().token(TOKEN).post_init(setup_db).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    # Added filters.PHOTO here so the bot accepts the QR Code picture uploads!
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__': main()
