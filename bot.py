import logging
import psycopg2
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

# --- Configuration ---
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("No BOT_TOKEN provided in environment variables!")

DATABASE_URL = "postgresql://postgres:wAjYOYPUfiPZWfgYddgjjNfmDhqJfngj@postgres.railway.internal:5432/railway"
if not DATABASE_URL:
    raise ValueError("No DATABASE_URL provided in environment variables!")

WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://mini-apo-production.up.railway.app/')

admin_ids_raw = os.getenv('ADMIN_IDS', '6197579049')
ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(',') if x.strip().isdigit()]

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def get_ist_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

def generate_password():
    words = ["Fire", "Care", "Love", "Hope", "Blue", "Dark", "Star", "Moon", "Fast", "Cool", "Bird", "Tree", "Wild", "Wind"]
    word = random.choice(words).capitalize()
    nums = str(random.randint(100, 999))
    return f"{word}@{nums}"

# --- Database Setup (PostgreSQL) ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        task_data TEXT,
        status TEXT DEFAULT 'available',
        assigned_to BIGINT,
        assigned_at TEXT,
        submission_data TEXT,
        message_id BIGINT
    )''')
    
    try:
        cursor.execute('ALTER TABLE tasks ADD COLUMN message_id BIGINT')
        conn.commit()
    except Exception:
        conn.rollback()
        
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN hw_id TEXT')
        conn.commit()
    except Exception:
        conn.rollback()

    cursor.execute('''CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
        chat_id TEXT PRIMARY KEY,
        invite_link TEXT
    )''')

    cursor.execute("INSERT INTO config (key, value) VALUES ('menu_text', 'Welcome to the Task Bot! Complete tasks to earn INR.') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('bot_status', 'ON') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('withdrawal_status', 'ON') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('total_wd_processed', '0') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('payment_api_url', '') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('payment_status_url', '') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('min_withdrawal', '10') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('max_withdrawal', '10000') ON CONFLICT (key) DO NOTHING")
    cursor.execute("INSERT INTO config (key, value) VALUES ('withdrawal_tax', '0') ON CONFLICT (key) DO NOTHING")

    conn.commit()
    conn.close()

init_db()

def db_query(query, params=(), commit=False, fetchall=False, fetchone=False):
    pg_query = query.replace('?', '%s')
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute(pg_query, params)
    res = None
    if commit: conn.commit()
    if fetchall: res = cursor.fetchall()
    elif fetchone: res = cursor.fetchone()
    conn.close()
    return res

def reset_task_password(tid):
    t = db_query("SELECT task_data FROM tasks WHERE id=?", (tid,), fetchone=True)
    if t:
        username = t[0].split(":")[0]
        new_pass = generate_password()
        db_query("UPDATE tasks SET task_data=? WHERE id=?", (f"{username}:{new_pass}", tid), commit=True)

async def check_user_joined_channels(bot, user_id):
    channels = db_query("SELECT chat_id FROM channels", fetchall=True)
    if not channels: return True
    for row in channels:
        try:
            c_id = row[0].strip()
            if c_id.startswith("-") or c_id.isdigit(): c_id = int(c_id)
            member = await bot.get_chat_member(chat_id=c_id, user_id=user_id)
            if member.status in ['left', 'kicked']: return False
        except: return False
    return True

def get_channel_verification_keyboard():
    channels = db_query("SELECT invite_link FROM channels", fetchall=True)
    keyboard = []
    row = []
    for i, row_data in enumerate(channels):
        row.append(InlineKeyboardButton(f"Join Channel {i+1}", url=row_data[0]))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("Verify Channels", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

def get_webapp_verify_keyboard(bot_username, safe_name, user_id):
    # Generates dynamic URL, bypassing Telegram cache & passes user data cleanly
    cache_buster_url = f"{WEBAPP_URL.rstrip('/')}/index.html?v={int(datetime.now().timestamp())}&bot={bot_username}&name={safe_name}&uid={user_id}"
    
    # Beautiful Inline Button restored safely
    keyboard = [
        [InlineKeyboardButton("✅ Verify Your Device", web_app=WebAppInfo(url=cache_buster_url))]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(user_id):
    keyboard = [
        [KeyboardButton("📝 Get Task")],
        [KeyboardButton("💰 Wallet"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("👥 Refer & Earn"), KeyboardButton("📞 Support")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_panel_text():
    min_wd = db_query("SELECT value FROM config WHERE key='min_withdrawal'", fetchone=True)[0]
    max_wd = db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)[0]
    wd_tax = db_query("SELECT value FROM config WHERE key='withdrawal_tax'", fetchone=True)[0]
    api_link = db_query("SELECT value FROM config WHERE key='payment_api_url'", fetchone=True)[0]
    status_link = db_query("SELECT value FROM config WHERE key='payment_status_url'", fetchone=True)[0]
    
    return (
        "⚙️ **Admin Panel**\n\n"
        f"📉 Min Withdrawal: `₹{min_wd}`\n"
        f"📈 Max Withdrawal: `₹{max_wd}`\n"
        f"💸 Instant WD Tax: `₹{wd_tax}`\n"
        f"🔗 Pay API Link: `{api_link if api_link else 'Not Set'}`\n"
        f"🔗 Status Link: `{status_link if status_link else 'Not Set'}`"
    )

def get_admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Bulk Upload Tasks", callback_data="adm_bulk"), InlineKeyboardButton("📋 Tasks Queue", callback_data="adm_pending_tasks")],
        [InlineKeyboardButton("📥 Task Approvals", callback_data="adm_list_task_app"), InlineKeyboardButton("🏧 WD Requests", callback_data="adm_list_wd")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"), InlineKeyboardButton("💬 DM User", callback_data="adm_dm")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"), InlineKeyboardButton("🔓 Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("Toggle WD", callback_data="adm_tog_wd"), InlineKeyboardButton("Toggle Bot", callback_data="adm_tog_bot")],
        [InlineKeyboardButton("🪙 Check Balance", callback_data="adm_chk_bal"), InlineKeyboardButton("💳 Mod Balance", callback_data="adm_mod_bal")],
        [InlineKeyboardButton("🏆 Top 10 Bal", callback_data="adm_top_bal"), InlineKeyboardButton("📝 Menu Text", callback_data="adm_chg_text")],
        [InlineKeyboardButton("📉 Min WD", callback_data="adm_min_wd"), InlineKeyboardButton("📈 Max WD", callback_data="adm_max_wd")],
        [InlineKeyboardButton("💸 WD Tax", callback_data="adm_wd_tax"), InlineKeyboardButton("🔗 Set Pay API", callback_data="adm_set_api")],
        [InlineKeyboardButton("🔗 Set Status Link", callback_data="adm_set_status_link"), InlineKeyboardButton("✅ Verify User", callback_data="adm_verify_user")],
        [InlineKeyboardButton("📢 Manage Channels", callback_data="adm_manage_channels"), InlineKeyboardButton("📊 Task Checkup", callback_data="adm_task_checkup")],
        [InlineKeyboardButton("🔍 Task Lookup", callback_data="adm_task_status_lookup"), InlineKeyboardButton("⏪ Task Pullback", callback_data="adm_task_pullback")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats"), InlineKeyboardButton("❌ Close", callback_data="main_menu")]
    ])

async def task_timeout_monitor(context: ContextTypes.DEFAULT_TYPE):
    cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()
    expired = db_query("SELECT id, assigned_to, message_id FROM tasks WHERE status = 'assigned' AND assigned_at < ?", (cutoff,), fetchall=True)
    for tid, uid, mid in expired:
        reset_task_password(tid)
        db_query("UPDATE tasks SET status = 'available', assigned_to = NULL, assigned_at = NULL, message_id = NULL WHERE id = ?", (tid,), commit=True)
        if mid:
            try: await context.bot.delete_message(chat_id=uid, message_id=mid)
            except: pass
        try: await context.bot.send_message(chat_id=uid, text="⚠️ Task expired (30m limit). It has been removed. Please request a new task.")
        except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, username = update.effective_user.id, update.effective_user.username or "Unknown"

    bot_status = db_query("SELECT value FROM config WHERE key='bot_status'", fetchone=True)[0]

    if bot_status == 'OFF' and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Maintenance mode.")
        return

    user = db_query("SELECT is_banned, device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)

    if user and user[0] == 1:
        await update.message.reply_text("❌ Access Denied.")
        return

    if not user:
        ref_id = None
        if context.args and context.args[0].isdigit() and int(context.args[0]) != user_id:
            ref_id = int(context.args[0])

        db_query(
            "INSERT INTO users (user_id, username, referred_by, device_verified) VALUES (?, ?, ?, 0) ON CONFLICT (user_id) DO NOTHING",
            (user_id, username, ref_id),
            commit=True
        )
        device_verified = 0
    else:
        device_verified = user[1]

    # Handle the automatic Deep Link Redirect from the WebApp for Device Verification
    if context.args and context.args[0].startswith("v_"):
        hw_id = context.args[0][2:]
        
        # Security Block: Strictly checks if this token is already verified by another user
        existing_device = db_query("SELECT user_id FROM users WHERE hw_id = ? AND user_id != ?", (hw_id, user_id), fetchone=True)
        if existing_device:
            await update.message.reply_text(
                "❌ **Security Violation Detected**\n\nThis physical device is already linked to another Telegram account. Multiple accounts on a single device are strictly prohibited.", 
                parse_mode="Markdown"
            )
            return
            
        # Verify user and save their device hardware ID securely
        db_query("UPDATE users SET device_verified=1, hw_id=? WHERE user_id=?", (hw_id, user_id), commit=True)
        device_verified = 1
        await update.message.reply_text("✅ *Device Verified Successfully!*", parse_mode="Markdown")

    # If verified, trigger main menu automatically without asking again
    if device_verified == 1:
        menu_text = db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)[0]
        await update.message.reply_text(menu_text, reply_markup=get_main_menu_keyboard(user_id))
        return

    if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Join channels first:", reply_markup=get_channel_verification_keyboard())
        return

    bot_user = await context.bot.get_me()
    safe_name = urllib.parse.quote(update.effective_user.first_name or update.effective_user.username or "User")

    await update.message.reply_text(
        "🔒 *Verify Yourself To Start Bot*\n\nPlease click the button below to complete the device security check.",
        parse_mode="Markdown",
        reply_markup=get_webapp_verify_keyboard(bot_user.username, safe_name, user_id)
    )

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    data = query.data

    if data == "check_membership":
        if await check_user_joined_channels(context.bot, user_id):
            user = db_query("SELECT device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
            device_verified = user[0] if user else 0
            
            if not device_verified and user_id not in ADMIN_IDS:
                bot_user = await context.bot.get_me()
                safe_name = urllib.parse.quote(query.from_user.first_name or query.from_user.username or "User")
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=user_id, 
                    text="✅ Channels Joined!\n\n🔒 *Verify Yourself To Start Bot*\n\nPlease click the button below to complete the device security check.", 
                    parse_mode="Markdown", 
                    reply_markup=get_webapp_verify_keyboard(bot_user.username, safe_name, user_id)
                )
            else:
                menu_text = db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)[0]
                await query.message.delete()
                await context.bot.send_message(chat_id=user_id, text="✅ All Verifications Complete!\n\n" + menu_text, reply_markup=get_main_menu_keyboard(user_id))
        else: 
            await query.message.edit_text("❌ Join all channels.", reply_markup=get_channel_verification_keyboard())
        return

    if data == "admin_panel" and user_id in ADMIN_IDS:
        await query.message.edit_text(get_admin_panel_text(), parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())

    elif data == "adm_verify_user" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_VERIFY_USER'
        await query.message.reply_text("Enter User ID to manually verify:")

    elif data == "adm_stats" and user_id in ADMIN_IDS:
        total_u = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
        total_t = db_query("SELECT COUNT(*) FROM tasks WHERE status='completed'", fetchone=True)[0]
        total_wd = db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)[0]
        verified_u = 0
        all_u = db_query("SELECT user_id FROM users", fetchall=True)
        for u in all_u:
            if await check_user_joined_channels(context.bot, u[0]): verified_u += 1
        stats_msg = f"Total users in bot :- \"{total_u}\"\n\nTotal verified users :- \"{verified_u}\"\n\nTotal withdrawal:- \"₹{total_wd}\"\n\nTotal tasks completed:- \"{total_t}\""
        await query.message.reply_text(stats_msg)
    
    elif data == "main_menu":
        menu_text = db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)[0]
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text=menu_text, reply_markup=get_main_menu_keyboard(user_id))
    
    elif data == "get_task":
        if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
            await query.message.reply_text("⚠️ You must join all channels to get tasks.", reply_markup=get_channel_verification_keyboard())
            return
            
        active = db_query("SELECT id FROM tasks WHERE assigned_to = ? AND status = 'assigned'", (user_id,), fetchone=True)
        if active: await query.message.reply_text("⚠️ Finish active task first."); return
        task = db_query("SELECT id, task_data FROM tasks WHERE status = 'available' LIMIT 1", fetchone=True)
        if not task: await query.message.reply_text("📭 No tasks."); return
        
        tid, tdata = task
        try: t_user, t_pass = tdata.split(":")
        except: await query.message.reply_text("⚠️ Task Error."); return
        
        msg_text = f"TASK ID :- \"{tid}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nTASK TIMEOUT IN 30MINS."
        sent_msg = await query.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit", callback_data=f"subm_t_{tid}"), InlineKeyboardButton("❌ Cancel", callback_data=f"canc_t_{tid}")]]))
        
        db_query("UPDATE tasks SET status = 'assigned', assigned_to = ?, assigned_at = ?, message_id = ? WHERE id = ?", (user_id, datetime.now().isoformat(), sent_msg.message_id, tid), commit=True)

    elif data.startswith("canc_t_"):
        tid = int(data.split("_")[2])
        t = db_query("SELECT message_id FROM tasks WHERE id=?", (tid,), fetchone=True)
        if t and t[0]:
            try: await context.bot.delete_message(chat_id=user_id, message_id=t[0])
            except: pass
            
        reset_task_password(tid)
        db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=? AND assigned_to=?", (tid, user_id), commit=True)
        try: await query.message.edit_text("❌ Task canceled. It is now back in the public queue.")
        except: await context.bot.send_message(user_id, "❌ Task canceled. It is now back in the public queue.")
    
    elif data.startswith("subm_t_"):
        tid = int(data.split("_")[2])
        db_query("UPDATE tasks SET status = 'pending_approval' WHERE id = ?", (tid,), commit=True)
        await query.message.edit_text("⏳ Submitted for approval. You can now get another task!")
        
        t_info = db_query("SELECT assigned_to, task_data FROM tasks WHERE id=?", (tid,), fetchone=True)
        try: 
            t_user, t_pass = t_info[1].split(":")
        except: 
            t_user, t_pass = "Error", "Error"
        
        adm_msg = f"TASK ID :- \"{tid}\"\n\nUSER ID :- \"{t_info[0]}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nSUBMIT TIME:- \"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\""
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(admin, adm_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"adm_app_t_{tid}"), InlineKeyboardButton("Reject", callback_data=f"adm_rej_t_{tid}")]]))
            except: pass

    elif data.startswith(("adm_app_t_", "adm_rej_t_")):
        parts = data.split("_")
        act = parts[1]
        tid = int(parts[3])
        
        uid_row = db_query("SELECT assigned_to FROM tasks WHERE id=?", (tid,), fetchone=True)
        uid = uid_row[0] if uid_row else None
        
        if act == 'app':
            db_query("UPDATE tasks SET status='completed' WHERE id=?", (tid,), commit=True)
            if uid:
                db_query("UPDATE users SET balance=balance+15 WHERE user_id=?", (uid,), commit=True)
            status_msg = "APPROVED"
        else:
            reset_task_password(tid)
            db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=?", (tid,), commit=True)
            status_msg = "REJECTED"
        
        if uid:
            try:
                await context.bot.send_message(uid, f"TASK ID :- \"{tid}\"\n\nSTATUS:- \"{status_msg}\"\n\nREMARKS:- \"Processed by Admin\"")
            except:
                pass
                
        await query.message.edit_text(f"✅ Task {tid} processed as {status_msg}.")

    elif data == "wallet":
        u = db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        await query.message.edit_text(f"💳 Balance: ₹{u[0]:.2f}\nUPI: `{u[1] or 'None'}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Link UPI", callback_data="add_upi")], [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")], [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))
    
    elif data == "add_upi": context.user_data['state'] = 'WAITING_UPI'; await query.message.reply_text("Send UPI:")
    
    elif data == "withdraw": 
        kb = [
            [InlineKeyboardButton("⚡ Instant Withdrawal", callback_data="wd_instant")],
            [InlineKeyboardButton("🏦 Manual Withdrawal", callback_data="wd_manual")],
            [InlineKeyboardButton("⬅️ Back", callback_data="wallet")]
        ]
        await query.message.edit_text("Select Withdrawal Method:", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data in ["wd_instant", "wd_manual"]:
        wd_s = db_query("SELECT value FROM config WHERE key='withdrawal_status'", fetchone=True)[0]
        if wd_s == 'OFF': await query.message.reply_text("⚠️ Withdrawals are currently OFF"); return
        
        u = db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        if not u[1]: await query.message.reply_text("❌ Please link your UPI ID first from the wallet menu."); return
        if u[0] <= 0: await query.message.reply_text("❌ Insufficient balance."); return
        
        wd_type = data.split('_')[1].upper()
        context.user_data['state'] = f'WAITING_WD_AMOUNT_{wd_type}'
        
        max_wd = db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)[0]
        await query.message.reply_text(f"Enter Amount for {wd_type} withdrawal (Wallet: ₹{u[0]}, Max/Txn: ₹{max_wd}):")

    elif data in ["wd_confirm", "wd_cancel"]:
        temp_wd = context.user_data.pop('temp_wd', None)
        if not temp_wd:
            await query.message.edit_text("❌ Session expired or request already processed.")
            return
            
        if data == "wd_cancel":
            db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (temp_wd['amount'], user_id), commit=True)
            await query.message.edit_text("❌ Withdrawal Cancelled. Amount has been refunded to your wallet.")
            return
            
        elif data == "wd_confirm":
            await query.message.edit_text("⏳ Processing withdrawal...")
            amt = temp_wd['amount']
            actual_amt = temp_wd['actual_amount']
            u_upi = temp_wd['upi']
            wd_type = temp_wd['type']
            
            if wd_type == 'MANUAL':
                if 'withdrawals' not in context.bot_data: context.bot_data['withdrawals'] = {}
                wid = str(int(datetime.now().timestamp()))
                context.bot_data['withdrawals'][wid] = {'user_id': user_id, 'amount': amt, 'upi': u_upi, 'time': get_ist_time()}
                await query.message.edit_text("✅ Manual WD Requested successfully. Please wait for admin approval.")
                
                adm_wd_msg = f"USER ID :- \"{user_id}\"\n\nUPI ID :- `{u_upi}`\n\nAMOUNT:- \"{amt}\"\n\nWITHDRAWAL TIME:- \"{context.bot_data['withdrawals'][wid]['time']}\""
                for a in ADMIN_IDS:
                    try: await context.bot.send_message(a, adm_wd_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"adm_app_w_{wid}"), InlineKeyboardButton("Reject", callback_data=f"adm_rej_w_{wid}")]]))
                    except: pass

            elif wd_type == 'INSTANT':
                api_url = db_query("SELECT value FROM config WHERE key='payment_api_url'", fetchone=True)
                if not api_url or not api_url[0]:
                    await query.message.edit_text("❌ API not configured by admin. Refunding balance.")
                    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, user_id), commit=True)
                    return
                
                formatted_url = api_url[0].replace("{upi id}", u_upi).replace("{amount}", str(actual_amt))
                try:
                    resp = requests.get(formatted_url, timeout=15)
                    try:
                        resp_json = resp.json()
                        txn_id = str(resp_json.get('txnid') or resp_json.get('transaction_id') or resp_json.get('id') or resp_json.get('order_id') or resp.text[:50])
                    except:
                        txn_id = resp.text[:50].strip()
                    comment = resp.text[:100]
                except Exception as e:
                    txn_id = "UNKNOWN"
                    comment = str(e)[:100]
                
                status_api_url = db_query("SELECT value FROM config WHERE key='payment_status_url'", fetchone=True)[0]
                
                params = {
                    'uid': user_id,
                    'name': update.effective_user.first_name or update.effective_user.username or "User",
                    'amt': actual_amt,
                    'upi': u_upi,
                    'txnid': txn_id,
                    'api': status_api_url
                }
                query_string = urllib.parse.urlencode(params)
                full_webapp_url = f"{WEBAPP_URL.rstrip('/')}/index1.html?{query_string}"
                
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Check payment status", web_app=WebAppInfo(url=full_webapp_url))]])
                await query.message.edit_text("YOUR WITHDRAWAL IS SUCCESSFULLY PAID FROM GATEWAY ✅\n\n⚠️IF NOT RECEIVED THEN CONTACT SUPPORT", reply_markup=btn)
                
                adm_msg = f"⚡ **Instant Withdrawal Triggered**\n\nUSER ID :- `{user_id}`\nUPI ID :- `{u_upi}`\nGROSS AMOUNT :- `₹{amt}`\nACTUAL TRANSFERRED :- `₹{actual_amt}`\nTAX CUT :- `₹{amt - actual_amt}`\nTIME :- `{get_ist_time()}`\n\nAPI RESPONSE :- `{comment}`"
                for admin in ADMIN_IDS:
                    try: await context.bot.send_message(admin, adm_msg, parse_mode="Markdown")
                    except: pass
                    
                cur_total = float(db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)[0])
                db_query("UPDATE config SET value=? WHERE key='total_wd_processed'", (str(cur_total + actual_amt),), commit=True)

    elif data == "refer_earn":
        bot_me = await context.bot.get_me()
        c = db_query("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,), fetchone=True)[0]
        await query.message.edit_text(f"👥 Referrals: {c}\nLink: `t.me/{bot_me.username}?start={user_id}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))
    
    elif data == "adm_bulk": context.user_data['state'] = 'ADM_WAITING_BULK'; await query.message.reply_text("Format: `u,u,u,...` (Usernames separated by comma)")
    
    elif data == "adm_pending_tasks" and user_id in ADMIN_IDS:
        tks = db_query("SELECT id, task_data FROM tasks WHERE status='available'", fetchall=True)
        kb = [[InlineKeyboardButton("🗑️ Clear All", callback_data="adm_del_all_tasks")], [InlineKeyboardButton("🗑️ Delete Indiv", callback_data="adm_del_indiv_task")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
        msg = "📋 Available Tasks:\n\n" + "\n".join([f"ID {t[0]}: {t[1].split(':')[0]}" for t in tks]) if tks else "No available tasks."
        await query.message.edit_text(msg[:4000], reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "adm_del_all_tasks" and user_id in ADMIN_IDS:
        db_query("DELETE FROM tasks WHERE status='available'", commit=True); await query.message.reply_text("Queue cleared.")
    
    elif data == "adm_del_indiv_task" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_DEL_INDIV'; await query.message.reply_text("Enter Task ID to delete:")

    elif data == "adm_list_task_app":
        p = db_query("SELECT id, assigned_to, task_data, assigned_at FROM tasks WHERE status='pending_approval'", fetchall=True)
        if not p: await query.message.reply_text("No pending approvals."); return
        for t in p: 
            tid, assigned_to, task_data, assigned_at = t
            try: t_user, t_pass = task_data.split(":")
            except: t_user, t_pass = "Error", "Error"
            
            detail_msg = (
                f"📝 **PENDING TASK APPROVAL**\n\n"
                f"TASK ID :- \"{tid}\"\n"
                f"USER ID :- \"{assigned_to}\"\n"
                f"USERNAME :- `{t_user}`\n"
                f"PASSWORD :- `{t_pass}`\n"
                f"SUBMIT TIME:- \"{assigned_at if assigned_at else 'N/A'}\""
            )
            await query.message.reply_text(detail_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"adm_app_t_{tid}"), InlineKeyboardButton("Reject", callback_data=f"adm_rej_t_{tid}")]]))

    elif data == "adm_list_wd":
        w = context.bot_data.get('withdrawals', {})
        if not w: await query.message.reply_text("No pending Manual WD."); return
        for k, v in list(w.items()): 
            detail_wd_msg = (
                f"🏧 **PENDING MANUAL WITHDRAWAL**\n\n"
                f"REQUEST ID :- \"{k}\"\n"
                f"USER ID :- \"{v['user_id']}\"\n"
                f"UPI ID :- `{v['upi']}`\n"
                f"AMOUNT :- \"{v['amount']}\"\n"
                f"WITHDRAWAL TIME :- \"{v['time']}\""
            )
            await query.message.reply_text(detail_wd_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("App", callback_data=f"adm_app_w_{k}"), InlineKeyboardButton("Rej", callback_data=f"adm_rej_w_{k}")]]))
    
    elif data.startswith(("adm_app_w_", "adm_rej_w_")):
        parts = data.split("_")
        act = parts[1]
        wid = parts[3]
        
        wd = context.bot_data.get('withdrawals', {}).pop(wid, None)
        if wd:
            if act == 'app':
                cur_total = float(db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)[0])
                db_query("UPDATE config SET value=? WHERE key='total_wd_processed'", (str(cur_total + wd['amount']),), commit=True)
                status_msg = "APPROVED"
            else:
                db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (wd['amount'], wd['user_id']), commit=True)
                status_msg = "REJECTED"
            
            try:
                await context.bot.send_message(wd['user_id'], f"WITHDRAWAL STATUS:- \"{status_msg}\"\n\nWITHDRAWAL TIME :- \"{get_ist_time()}\"\n\nREMARKS :- \"Processed by Admin\"")
            except:
                pass
            await query.message.edit_text(f"✅ Withdrawal {wid} processed as {status_msg}.")
        else:
            await query.message.edit_text("❌ Withdrawal request already processed or not found.")
    
    elif data == "adm_broadcast": context.user_data['state'] = 'ADM_BROADCAST'; await query.message.reply_text("Msg:")
    elif data == "adm_dm": context.user_data['state'] = 'ADM_DM'; await query.message.reply_text("Format: `id:msg`")
    elif data == "adm_ban": context.user_data['state'] = 'ADM_BAN'; await query.message.reply_text("ID to ban:")
    elif data == "adm_unban": context.user_data['state'] = 'ADM_UNBAN'; await query.message.reply_text("ID to unban:")
    
    elif data == "adm_tog_wd":
        c = db_query("SELECT value FROM config WHERE key='withdrawal_status'", fetchone=True)[0]
        s = 'OFF' if c == 'ON' else 'ON'; db_query("UPDATE config SET value=? WHERE key='withdrawal_status'", (s,), commit=True); await query.message.reply_text(f"WD {s}")
    elif data == "adm_tog_bot":
        c = db_query("SELECT value FROM config WHERE key='bot_status'", fetchone=True)[0]
        s = 'OFF' if c == 'ON' else 'ON'; db_query("UPDATE config SET value=? WHERE key='bot_status'", (s,), commit=True); await query.message.reply_text(f"Bot {s}")
    
    elif data == "adm_chk_bal": context.user_data['state'] = 'ADM_CHK_BAL'; await query.message.reply_text("ID:")
    elif data == "adm_mod_bal": context.user_data['state'] = 'ADM_MOD_BAL'; await query.message.reply_text("Format: `id:amt`")
    elif data == "adm_top_bal":
        t = db_query("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
        await query.message.reply_text("\n".join([f"{i+1}) {r[0]} - ₹{r[1]:.2f}" for i, r in enumerate(t)]))
    
    elif data == "adm_chg_text": context.user_data['state'] = 'ADM_CHG_TEXT'; await query.message.reply_text("New Menu Text:")
    
    elif data == "adm_min_wd": context.user_data['state'] = 'ADM_SET_MIN_WD'; await query.message.reply_text("Enter New Minimum Withdrawal Amount:")
    elif data == "adm_max_wd": context.user_data['state'] = 'ADM_SET_MAX_WD'; await query.message.reply_text("Enter New Maximum Withdrawal Amount:")
    elif data == "adm_wd_tax": context.user_data['state'] = 'ADM_SET_WD_TAX'; await query.message.reply_text("Enter New Instant Withdrawal Tax Amount (e.g. 5):")
    
    elif data == "adm_task_status_lookup": context.user_data['state'] = 'ADM_LOOKUP_TASK'; await query.message.reply_text("Task ID or Username:")
    elif data == "adm_task_checkup": context.user_data['state'] = 'ADM_BULK_CHECK'; await query.message.reply_text("Enter task usernames separated by comma or newline:")
    elif data == "adm_task_pullback": context.user_data['state'] = 'ADM_PULLBACK'; await query.message.reply_text("Enter Task ID or Username to Pullback:")
    elif data == "adm_set_api": context.user_data['state'] = 'ADM_SET_API'; await query.message.reply_text("Enter API Link (Use `{upi id}` and `{amount}` as placeholders):")
    elif data == "adm_set_status_link": context.user_data['state'] = 'ADM_SET_STATUS_LINK'; await query.message.reply_text("Enter Status API Link (Use `{txnid}` as a placeholder if required by the API):")
    
    elif data == "adm_manage_channels":
        kb = [[InlineKeyboardButton("➕ Add", callback_data="adm_add_chan"), InlineKeyboardButton("❌ Rem", callback_data="adm_rem_chan")], [InlineKeyboardButton("📋 List", callback_data="adm_list_chan")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
        await query.message.edit_text("Channels:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "adm_add_chan": context.user_data['state'] = 'ADM_ADD_CHAN_DATA'; await query.message.reply_text("id:link")
    elif data == "adm_rem_chan": context.user_data['state'] = 'ADM_REM_CHAN_DATA'; await query.message.reply_text("id to rem")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state')

    user = db_query("SELECT is_banned, device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not user:
        await update.message.reply_text("⚠️ Please send /start first.")
        return
    if user[0] == 1:
        return
    if user[1] == 0 and user_id not in ADMIN_IDS:
        bot_user = await context.bot.get_me()
        safe_name = urllib.parse.quote(update.effective_user.first_name or update.effective_user.username or "User")
        await update.message.reply_text(
            "🔒 Please verify your device using /start first.",
            reply_markup=get_webapp_verify_keyboard(bot_user.username, safe_name, user_id)
        )
        return
    if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Join channels first to continue.", reply_markup=get_channel_verification_keyboard())
        return

    if text == "📝 Get Task":
        active = db_query("SELECT id FROM tasks WHERE assigned_to = ? AND status = 'assigned'", (user_id,), fetchone=True)
        if active: await update.message.reply_text("⚠️ Finish active task first."); return
        task = db_query("SELECT id, task_data FROM tasks WHERE status = 'available' LIMIT 1", fetchone=True)
        if not task: await update.message.reply_text("📭 No tasks."); return
        
        tid, tdata = task
        try: t_user, t_pass = tdata.split(":")
        except: await update.message.reply_text("⚠️ Task Error."); return
        
        msg_text = f"TASK ID :- \"{tid}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nTASK TIMEOUT IN 30MINS."
        sent_msg = await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit", callback_data=f"subm_t_{tid}"), InlineKeyboardButton("❌ Cancel", callback_data=f"canc_t_{tid}")]]))
        
        db_query("UPDATE tasks SET status = 'assigned', assigned_to = ?, assigned_at = ?, message_id = ? WHERE id = ?", (user_id, datetime.now().isoformat(), sent_msg.message_id, tid), commit=True)
        return

    elif text == "💰 Wallet":
        u = db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        await update.message.reply_text(f"💳 Balance: ₹{u[0]:.2f}\nUPI: `{u[1] or 'None'}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Link UPI", callback_data="add_upi")], [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]]))
        return

    elif text == "💸 Withdraw":
        wd_s = db_query("SELECT value FROM config WHERE key='withdrawal_status'", fetchone=True)[0]
        if wd_s == 'OFF': await update.message.reply_text("⚠️ WD OFF"); return
        
        kb = [
            [InlineKeyboardButton("⚡ Instant Withdrawal", callback_data="wd_instant")],
            [InlineKeyboardButton("🏦 Manual Withdrawal", callback_data="wd_manual")]
        ]
        await update.message.reply_text("Choose withdrawal method:", reply_markup=InlineKeyboardMarkup(kb))
        return

    elif text == "👥 Refer & Earn":
        bot_me = await context.bot.get_me()
        c = db_query("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,), fetchone=True)[0]
        await update.message.reply_text(f"👥 Referrals: {c}\nLink: `t.me/{bot_me.username}?start={user_id}`", parse_mode="Markdown")
        return

    elif text == "📞 Support":
        admin_contact_url = f"tg://openmessage?user_id=7930010364"
        await update.message.reply_text(f"📞 Contact Support: {admin_contact_url}")
        return

    elif text == "⚙️ Admin Panel" and user_id in ADMIN_IDS:
        await update.message.reply_text(get_admin_panel_text(), parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())
        return

    if not state: return
    context.user_data['state'] = None

    if state == 'ADM_VERIFY_USER' and user_id in ADMIN_IDS:
        if text.isdigit():
            target_id = int(text)
            db_query("UPDATE users SET device_verified=1 WHERE user_id=?", (target_id,), commit=True)
            await update.message.reply_text(f"✅ User {target_id} has been manually verified and can now access the bot.")
            
            try:
                menu_text = db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)[0]
                await context.bot.send_message(
                    chat_id=target_id, 
                    text="✅ You have been manually verified by an Admin!\n\n" + menu_text, 
                    reply_markup=get_main_menu_keyboard(target_id)
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ Invalid User ID. Please enter numbers only.")

    elif state == 'WAITING_UPI': db_query("UPDATE users SET upi_id=? WHERE user_id=?", (text, user_id), commit=True); await update.message.reply_text("UPI Linked.")
    
    elif state.startswith('WAITING_WD_AMOUNT_'):
        wd_type = state.split('_')[3]
        try: amt = float(text)
        except: await update.message.reply_text("❌ Invalid amount format."); return
        
        u = db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        min_wd = float(db_query("SELECT value FROM config WHERE key='min_withdrawal'", fetchone=True)[0])
        max_wd = float(db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)[0])
        wd_tax = float(db_query("SELECT value FROM config WHERE key='withdrawal_tax'", fetchone=True)[0])
        
        if amt < min_wd:
            await update.message.reply_text(f"min. Withdrawal is {min_wd} reenter amount more than min. withdrawal")
            return
            
        if amt > max_wd:
            await update.message.reply_text(f"❌ Cannot withdraw more than the max withdrawal limit (₹{max_wd}) at once.")
            return

        if 0 < amt <= u[0]:
            actual_amt = amt
            if wd_type == 'INSTANT':
                actual_amt = amt - wd_tax
                if actual_amt <= 0:
                    await update.message.reply_text("❌ Amount entered is too low to cover the instantaneous withdrawal tax.")
                    return
                    
            db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, user_id), commit=True)

            context.user_data['temp_wd'] = {
                'amount': amt,
                'actual_amount': actual_amt,
                'type': wd_type,
                'upi': u[1]
            }

            confirm_msg = f"⚠️ **Confirm Your Withdrawal**\n\n🏦 Linked UPI ID: `{u[1]}`\n💰 Entered Amount: `₹{amt}`"
            if wd_type == 'INSTANT':
                confirm_msg += f"\n📉 Actual Amount Received (After Tax): `₹{actual_amt}`"

            kb = [[InlineKeyboardButton("✅ Confirm", callback_data="wd_confirm"), InlineKeyboardButton("❌ Cancel", callback_data="wd_cancel")]]
            await update.message.reply_text(confirm_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            
        else:
            await update.message.reply_text("❌ Invalid amount or insufficient balance.")

    elif state == 'ADM_LOOKUP_TASK':
        if text.isdigit():
            t = db_query("SELECT status, assigned_to, assigned_at, task_data FROM tasks WHERE id=?", (int(text),), fetchone=True)
        else:
            t = db_query("SELECT status, assigned_to, assigned_at, task_data FROM tasks WHERE task_data LIKE ?", (f"{text}:%",), fetchone=True)
            
        if t:
            status_db, assigned_to_db, assigned_at_db, task_data_db = t
            status_map = {
                'available': 'NOT ASSIGNED',
                'assigned': 'PENDING',
                'pending_approval': 'PENDING',
                'completed': 'COMPLETED'
            }
            display_status = status_map.get(status_db, 'NOT ASSIGNED')
            try: 
                task_user, task_pass = task_data_db.split(":")
            except: 
                task_user, task_pass = "N/A", "N/A"
                
            display_pass = f"`{task_pass}`" if status_db == 'completed' else "N/A"
            
            tl = "N/A"
            if status_db == 'assigned' and assigned_at_db:
                df = (datetime.fromisoformat(assigned_at_db) + timedelta(minutes=30)) - datetime.now()
                tl = f"{int(df.total_seconds()//60)}m {int(df.total_seconds()%60)}s" if df.total_seconds() > 0 else "Expired"
                
            lookup_msg = (
                f"TASK STATUS:- \"{display_status}\"\n\n"
                f"TASK USERNAME:- `{task_user}`\n\n"
                f"PASSWORD:- {display_pass}\n\n"
                f"USER ID:- \"{assigned_to_db if assigned_to_db else 'N/A'}\"\n\n"
                f"TIME :- \"{assigned_at_db if assigned_at_db else 'N/A'}\"\n\n"
                f"TIMEOUT LEFT :- \"{tl}\""
            )
            await update.message.reply_text(lookup_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Task not found.")

    elif state == 'ADM_BULK_CHECK':
        usernames = text.replace('\n', ',').split(',')
        res = []
        for u in usernames:
            u = u.strip()
            if not u: continue
            t = db_query("SELECT status, task_data FROM tasks WHERE task_data LIKE ?", (f"{u}:%",), fetchone=True)
            if t:
                st, td = t[0], t[1]
                tu, tp = td.split(":")
                if st == 'completed':
                    res.append(f"`{tu}` - `{tp}`")
                else:
                    res.append(f"{tu} - PENDING")
            else:
                res.append(f"{u} - NOT FOUND")
        await update.message.reply_text("\n".join(res), parse_mode="Markdown")

    elif state == 'ADM_PULLBACK':
        if text.isdigit():
            t = db_query("SELECT id, assigned_to, message_id, status FROM tasks WHERE id=?", (int(text),), fetchone=True)
        else:
            t = db_query("SELECT id, assigned_to, message_id, status FROM tasks WHERE task_data LIKE ?", (f"{text}:%",), fetchone=True)
            
        if t:
            tid, uid, mid, st = t
            if st == 'assigned' and uid:
                if mid:
                    try: await context.bot.delete_message(chat_id=uid, message_id=mid)
                    except: pass
                try: await context.bot.send_message(uid, "THE TASK IS PULLED BY ADMINS PLEASE GET A NEW TASKS")
                except: pass
            
            reset_task_password(tid)
            db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=?", (tid,), commit=True)
            await update.message.reply_text(f"✅ Task pulled back successfully and reset into the queue.")
        else:
            await update.message.reply_text("❌ Task not found.")

    elif state == 'ADM_SET_API':
        db_query("UPDATE config SET value=? WHERE key='payment_api_url'", (text,), commit=True)
        await update.message.reply_text("✅ Payment API Link Updated Successfully.")
        
    elif state == 'ADM_SET_STATUS_LINK':
        db_query("UPDATE config SET value=? WHERE key='payment_status_url'", (text,), commit=True)
        await update.message.reply_text("✅ Payment Status Link Updated Successfully.")

    elif state == 'ADM_SET_MIN_WD':
        try: float(text)
        except: await update.message.reply_text("❌ Need numbers."); return
        db_query("UPDATE config SET value=? WHERE key='min_withdrawal'", (text,), commit=True)
        await update.message.reply_text("✅ Min Withdrawal Amount Updated.")
        
    elif state == 'ADM_SET_MAX_WD':
        try: float(text)
        except: await update.message.reply_text("❌ Need numbers."); return
        db_query("UPDATE config SET value=? WHERE key='max_withdrawal'", (text,), commit=True)
        await update.message.reply_text("✅ Max Withdrawal Amount Updated.")
        
    elif state == 'ADM_SET_WD_TAX':
        try: float(text)
        except: await update.message.reply_text("❌ Need numbers."); return
        db_query("UPDATE config SET value=? WHERE key='withdrawal_tax'", (text,), commit=True)
        await update.message.reply_text("✅ Withdrawal Tax Updated.")

    elif state == 'ADM_ADD_CHAN_DATA':
        if ":" in text: 
            cid, lnk = text.split(":", 1)
            db_query("INSERT INTO channels (chat_id, invite_link) VALUES (?,?) ON CONFLICT (chat_id) DO UPDATE SET invite_link = EXCLUDED.invite_link", (cid.strip(), lnk.strip()), commit=True)
            await update.message.reply_text("Added.")
    
    elif state == 'ADM_REM_CHAN_DATA': db_query("DELETE FROM channels WHERE chat_id=?", (text,), commit=True); await update.message.reply_text("Deleted.")
    
    elif state == 'ADM_DEL_INDIV':
        if text.isdigit(): db_query("DELETE FROM tasks WHERE id=? AND status='available'", (int(text),), commit=True); await update.message.reply_text("Task deleted.")
        
    elif state == 'ADM_WAITING_BULK':
        for u in text.split(","): 
            u = u.strip()
            if u:
                p = generate_password()
                db_query("INSERT INTO tasks (task_data) VALUES (?)", (f"{u}:{p}",), commit=True)
        await update.message.reply_text("Bulk added.")

    elif state == 'ADM_BROADCAST':
        for u in db_query("SELECT user_id FROM users", fetchall=True):
            try: await context.bot.send_message(u[0], f"📢 **Announcement**\n\n{text}", parse_mode="Markdown")
            except: pass
    elif state == 'ADM_DM' and ":" in text:
        target, msg = text.split(":", 1)
        try: await context.bot.send_message(int(target), f"💬 **Admin Msg:** {msg}"); await update.message.reply_text("Sent.")
        except: await update.message.reply_text("Failed.")
    elif state == 'ADM_BAN': db_query("UPDATE users SET is_banned=1 WHERE user_id=?", (int(text),), commit=True); await update.message.reply_text("Banned.")
    elif state == 'ADM_UNBAN': db_query("UPDATE users SET is_banned=0 WHERE user_id=?", (int(text),), commit=True); await update.message.reply_text("Unbanned.")
    elif state == 'ADM_CHK_BAL':
        b = db_query("SELECT balance FROM users WHERE user_id=?", (int(text),), fetchone=True)
        await update.message.reply_text(f"Bal: ₹{b[0] if b else 'N/A'}")
    elif state == 'ADM_MOD_BAL' and ":" in text:
        target, amt = text.split(":", 1)
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (float(amt), int(target)), commit=True); await update.message.reply_text("Updated.")
    elif state == 'ADM_CHG_TEXT': db_query("UPDATE config SET value=? WHERE key='menu_text'", (text,), commit=True); await update.message.reply_text("Menu Updated.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.job_queue.run_repeating(task_timeout_monitor, interval=60)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == '__main__': main()
