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
TOKEN = "8394044106:AAErmMRDt4hB_kw8ZVXBin1VW7QIYjjKx2c"
if not TOKEN:
    raise ValueError("No BOT_TOKEN provided in environment variables!")

DATABASE_URL = "postgresql://postgres:nikhil2008@127.0.0.1:5432/railway"
if not DATABASE_URL:
    raise ValueError("No DATABASE_URL provided in environment variables!")

# Vercel WebApp Links
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

def generate_password():
    words = ["Fire", "Care", "Love", "Hope", "Blue", "Dark", "Star", "Moon", "Fast", "Cool", "Bird", "Tree", "Wild", "Wind"]
    word = random.choice(words).capitalize()
    nums = str(random.randint(100, 999))
    return f"{word}@{nums}"

# --- Database Pool Setup ---
db_pool = None

async def init_db():
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
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

            await cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                task_data TEXT,
                status TEXT DEFAULT 'available',
                assigned_to BIGINT,
                assigned_at TEXT,
                submission_data TEXT,
                message_id BIGINT
            )''')

            await cursor.execute('''CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')

            await cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
                chat_id TEXT PRIMARY KEY,
                invite_link TEXT
            )''')

            await cursor.execute('''CREATE TABLE IF NOT EXISTS old_mails (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                email_user TEXT,
                email_pass TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )''')
            await cursor.execute("COMMIT")
            
            # Initial defaults
            await set_config('menu_text', 'Welcome to the Task Bot! Complete tasks to earn INR.', init=True)
            await set_config('bot_status', 'ON', init=True)
            await set_config('withdrawal_status', 'ON', init=True)
            await set_config('instant_wd_status', 'ON', init=True)
            await set_config('manual_wd_status', 'ON', init=True)
            await set_config('total_wd_processed', '0', init=True)
            await set_config('min_withdrawal', '10', init=True)
            await set_config('max_withdrawal', '10000', init=True)
            await set_config('withdrawal_tax', '0', init=True)
            await set_config('task_price', '15', init=True)
            await set_config('old_mail_amount', '50', init=True)

async def setup_db(application: Application):
    global db_pool
    try:
        db_pool = await aiopg.create_pool(
            DATABASE_URL, 
            minsize=1, 
            maxsize=10, 
            client_encoding='utf8'
        )
        logger.info("Async Database connection pool created successfully!")
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
                if fetchall: 
                    res = await cursor.fetchall()
                elif fetchone: 
                    res = await cursor.fetchone()
                    
                if commit:
                    await cursor.execute("COMMIT")
                return res
            except Exception as e:
                if commit:
                    await cursor.execute("ROLLBACK")
                logger.error(f"DB Query Error: {e}")
                raise

async def set_config(key, value, init=False):
    check = await db_query("SELECT value FROM config WHERE key = ?", (key,), fetchone=True)
    if check:
        if not init:
            await db_query("UPDATE config SET value = ? WHERE key = ?", (value, key), commit=True)
    else:
        await db_query("INSERT INTO config (key, value) VALUES (?, ?)", (key, value), commit=True)

async def set_channel(chat_id, invite_link):
    check = await db_query("SELECT invite_link FROM channels WHERE chat_id = ?", (chat_id,), fetchone=True)
    if check:
        await db_query("UPDATE channels SET invite_link = ? WHERE chat_id = ?", (invite_link, chat_id), commit=True)
    else:
        await db_query("INSERT INTO channels (chat_id, invite_link) VALUES (?, ?)", (chat_id, invite_link), commit=True)

async def reset_task_password(tid):
    t = await db_query("SELECT task_data FROM tasks WHERE id=?", (tid,), fetchone=True)
    if t:
        username = t[0].split(":")[0]
        new_pass = generate_password()
        await db_query("UPDATE tasks SET task_data=? WHERE id=?", (f"{username}:{new_pass}", tid), commit=True)

async def check_user_joined_channels(bot, user_id):
    channels = await db_query("SELECT chat_id FROM channels", fetchall=True)
    if not channels: return True
    for row in channels:
        try:
            c_id = row[0].strip()
            if c_id.startswith("-") or c_id.isdigit(): c_id = int(c_id)
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
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ Verify Channels", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

def get_webapp_verify_keyboard(bot_username, safe_name, user_id):
    cache_buster_url = f"{WEBAPP_URL.rstrip('/')}/index.html?v={int(datetime.now().timestamp())}&bot={bot_username}&name={safe_name}&uid={user_id}"
    keyboard = [
        [InlineKeyboardButton("✅ Verify Your Device", web_app=WebAppInfo(url=cache_buster_url))]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(user_id):
    keyboard = [
        [KeyboardButton("📝 Get Task", style="success"), KeyboardButton("🤝 Sell Old Gmail", style="primary")],
        [KeyboardButton("💰 Wallet", style="primary"), KeyboardButton("💸 Withdraw", style="danger")],
        [KeyboardButton("👥 Refer & Earn", style="primary"), KeyboardButton("💳 Pay User", style="primary")],
        [KeyboardButton("📞 Support")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_admin_panel_text():
    min_wd_row = await db_query("SELECT value FROM config WHERE key='min_withdrawal'", fetchone=True)
    min_wd = min_wd_row[0] if min_wd_row else '10'
    
    max_wd_row = await db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)
    max_wd = max_wd_row[0] if max_wd_row else '10000'
    
    wd_tax_row = await db_query("SELECT value FROM config WHERE key='withdrawal_tax'", fetchone=True)
    wd_tax = wd_tax_row[0] if wd_tax_row else '0'
    
    task_p_row = await db_query("SELECT value FROM config WHERE key='task_price'", fetchone=True)
    task_p = task_p_row[0] if task_p_row else '15'

    old_m_row = await db_query("SELECT value FROM config WHERE key='old_mail_amount'", fetchone=True)
    old_m = old_m_row[0] if old_m_row else '50'

    i_wd_row = await db_query("SELECT value FROM config WHERE key='instant_wd_status'", fetchone=True)
    i_wd = i_wd_row[0] if i_wd_row else 'ON'

    m_wd_row = await db_query("SELECT value FROM config WHERE key='manual_wd_status'", fetchone=True)
    m_wd = m_wd_row[0] if m_wd_row else 'ON'
    
    api_link_row = await db_query("SELECT value FROM config WHERE key='payment_api_url'", fetchone=True)
    api_link = api_link_row[0] if api_link_row else ''
    
    status_link_row = await db_query("SELECT value FROM config WHERE key='payment_status_url'", fetchone=True)
    status_link = status_link_row[0] if status_link_row else ''
    
    return (
        "⚙️ **Admin Panel**\n\n"
        f"📉 Min Withdrawal: `₹{min_wd}`\n"
        f"📈 Max Withdrawal: `₹{max_wd}`\n"
        f"💸 Instant WD Tax: `₹{wd_tax}`\n"
        f"🏷️ Task Reg Price: `₹{task_p}`\n"
        f"💰 Old Mail Price: `₹{old_m}`\n"
        f"⚡ Instant WD Status: `[{i_wd}]`\n"
        f"🏦 Manual WD Status: `[{m_wd}]`\n"
        f"🔗 Pay API Link: `{api_link if api_link else 'Not Set'}`\n"
        f"🔗 Status Link: `{status_link if status_link else 'Not Set'}`"
    )

def get_admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Bulk Upload Tasks", callback_data="adm_bulk"), InlineKeyboardButton("📋 Tasks Queue", callback_data="adm_pending_tasks")],
        [InlineKeyboardButton("📥 Task Approvals", callback_data="adm_list_task_app"), InlineKeyboardButton("🏧 WD Requests", callback_data="adm_list_wd")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"), InlineKeyboardButton("💬 DM User", callback_data="adm_dm")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"), InlineKeyboardButton("🔓 Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("🤖 Toggle Bot", callback_data="adm_tog_bot"), InlineKeyboardButton("📝 Menu Text", callback_data="adm_chg_text")],
        [InlineKeyboardButton("⚡ Toggle Instant WD", callback_data="adm_tog_inst_wd"), InlineKeyboardButton("🏦 Toggle Manual WD", callback_data="adm_tog_manu_wd")],
        [InlineKeyboardButton("📉 Min WD", callback_data="adm_min_wd"), InlineKeyboardButton("📈 Max WD", callback_data="adm_max_wd")],
        [InlineKeyboardButton("💸 WD Tax", callback_data="adm_wd_tax"), InlineKeyboardButton("🔗 Set Pay API", callback_data="adm_set_api")],
        [InlineKeyboardButton("🔗 Set Status Link", callback_data="adm_set_status_link"), InlineKeyboardButton("✅ Verify User", callback_data="adm_verify_user")],
        [InlineKeyboardButton("🏷️ Edit Task Price", callback_data="adm_set_task_price"), InlineKeyboardButton("💰 Old Mail Amount", callback_data="adm_set_old_mail_amt")],
        [InlineKeyboardButton("📥 Pending Old Mails", callback_data="adm_list_old_mails"), InlineKeyboardButton("📢 Manage Channels", callback_data="adm_manage_channels")],
        [InlineKeyboardButton("🪙 Check Balance", callback_data="adm_chk_bal"), InlineKeyboardButton("💳 Mod Balance", callback_data="adm_mod_bal")],
        [InlineKeyboardButton("🏆 Top 10 Bal", callback_data="adm_top_bal"), InlineKeyboardButton("📊 Task Checkup", callback_data="adm_task_checkup")],
        [InlineKeyboardButton("🔍 Task Lookup", callback_data="adm_task_status_lookup"), InlineKeyboardButton("⏪ Task Pullback", callback_data="adm_task_pullback")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats"), InlineKeyboardButton("❌ Close", callback_data="main_menu")]
    ])

async def task_timeout_monitor(context: ContextTypes.DEFAULT_TYPE):
    cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()
    expired = await db_query("SELECT id, assigned_to, message_id FROM tasks WHERE status = 'assigned' AND assigned_at < ?", (cutoff,), fetchall=True)
    for tid, uid, mid in expired:
        await reset_task_password(tid)
        await db_query("UPDATE tasks SET status = 'available', assigned_to = NULL, assigned_at = NULL, message_id = NULL WHERE id = ?", (tid,), commit=True)
        if mid:
            try: await context.bot.delete_message(chat_id=uid, message_id=mid)
            except: pass
        try: await context.bot.send_message(chat_id=uid, text="⚠️ Task expired (30m limit). It has been removed. Please request a new task.")
        except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, username = update.effective_user.id, update.effective_user.username or "Unknown"

    bot_status_row = await db_query("SELECT value FROM config WHERE key='bot_status'", fetchone=True)
    bot_status = bot_status_row[0] if bot_status_row else 'ON'

    if bot_status == 'OFF' and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Maintenance mode.")
        return

    user = await db_query("SELECT is_banned, device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)

    if user and user[0] == 1:
        await update.message.reply_text("❌ Access Denied.")
        return

    if not user:
        ref_id = None
        if context.args and context.args[0].isdigit() and int(context.args[0]) != user_id:
            ref_id = int(context.args[0])

        await db_query(
            "INSERT INTO users (user_id, username, referred_by, device_verified) VALUES (?, ?, ?, 0) ON CONFLICT (user_id) DO NOTHING",
            (user_id, username, ref_id),
            commit=True
        )
        device_verified = 0
    else:
        device_verified = user[1]

    if context.args and context.args[0].startswith("v_"):
        hw_id = context.args[0][2:]
        
        existing_device = await db_query("SELECT user_id FROM users WHERE hw_id = ? AND user_id != ?", (hw_id, user_id), fetchone=True)
        if existing_device:
            await update.message.reply_text(
                "❌ **Security Violation Detected**\n\nThis physical device is already linked to another Telegram account. Multiple accounts on a single device are strictly prohibited.", 
                parse_mode="Markdown"
            )
            return
            
        await db_query("UPDATE users SET device_verified=1, hw_id=? WHERE user_id=?", (hw_id, user_id), commit=True)
        device_verified = 1
        await update.message.reply_text("✅ *Device Verified Successfully!*", parse_mode="Markdown")

    if device_verified == 1:
        menu_text_row = await db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)
        menu_text = menu_text_row[0] if menu_text_row else "Welcome to the Task Bot! Complete tasks to earn INR."
        await update.message.reply_text(menu_text, reply_markup=get_main_menu_keyboard(user_id))
        return

    if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ Join channels first:", reply_markup=await get_channel_verification_keyboard())
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
            user = await db_query("SELECT device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
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
                menu_text_row = await db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)
                menu_text = menu_text_row[0] if menu_text_row else "Welcome to the Task Bot! Complete tasks to earn INR."
                await query.message.delete()
                await context.bot.send_message(chat_id=user_id, text="✅ All Verifications Complete!\n\n" + menu_text, reply_markup=get_main_menu_keyboard(user_id))
        else: 
            await query.message.edit_text("❌ Join all channels.", reply_markup=await get_channel_verification_keyboard())
        return

    if data == "admin_panel" and user_id in ADMIN_IDS:
        await query.message.edit_text(await get_admin_panel_text(), parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())

    elif data == "adm_verify_user" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_VERIFY_USER'
        await query.message.reply_text("Enter User ID to manually verify:")

    elif data == "adm_stats" and user_id in ADMIN_IDS:
        total_u = (await db_query("SELECT COUNT(*) FROM users", fetchone=True))[0]
        total_t = (await db_query("SELECT COUNT(*) FROM tasks WHERE status='completed'", fetchone=True))[0]
        total_wd_row = await db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)
        total_wd = total_wd_row[0] if total_wd_row else '0'
        
        verified_u = 0
        all_u = await db_query("SELECT user_id FROM users", fetchall=True)
        for u in all_u:
            if await check_user_joined_channels(context.bot, u[0]): verified_u += 1
        stats_msg = f"Total users in bot :- \"{total_u}\"\n\nTotal verified users :- \"{verified_u}\"\n\nTotal withdrawal:- \"₹{total_wd}\"\n\nTotal tasks completed:- \"{total_t}\""
        await query.message.reply_text(stats_msg)
    
    elif data == "main_menu":
        menu_text_row = await db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)
        menu_text = menu_text_row[0] if menu_text_row else "Welcome to the Task Bot!"
        await query.message.delete()
        await context.bot.send_message(chat_id=user_id, text=menu_text, reply_markup=get_main_menu_keyboard(user_id))
    
    elif data == "get_task":
        if not await check_user_joined_channels(context.bot, user_id) and user_id not in ADMIN_IDS:
            await query.message.reply_text("⚠️ You must join all channels to get tasks.", reply_markup=await get_channel_verification_keyboard())
            return
            
        active = await db_query("SELECT id FROM tasks WHERE assigned_to = ? AND status = 'assigned'", (user_id,), fetchone=True)
        if active: await update.message.reply_text("⚠️ Finish active task first."); return
        task = await db_query("SELECT id, task_data FROM tasks WHERE status = 'available' LIMIT 1", fetchone=True)
        if not task: await query.message.reply_text("📭 No tasks."); return
        
        tid, tdata = task
        try: t_user, t_pass = tdata.split(":")
        except: await update.message.reply_text("⚠️ Task Error."); return
        
        msg_text = f"TASK ID :- \"{tid}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nTASK TIMEOUT IN 30MINS."
        sent_msg = await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit", callback_data=f"subm_t_{tid}"), InlineKeyboardButton("❌ Cancel", callback_data=f"canc_t_{tid}")]]))
        
        await db_query("UPDATE tasks SET status = 'assigned', assigned_to = ?, assigned_at = ?, message_id = ? WHERE id = ?", (user_id, datetime.now().isoformat(), sent_msg.message_id, tid), commit=True)

    elif data.startswith("canc_t_"):
        tid = int(data.split("_")[2])
        t = await db_query("SELECT message_id FROM tasks WHERE id=?", (tid,), fetchone=True)
        if t and t[0]:
            try: await context.bot.delete_message(chat_id=user_id, message_id=t[0])
            except: pass
            
        await reset_task_password(tid)
        await db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=? AND assigned_to=?", (tid, user_id), commit=True)
        try: await query.message.edit_text("❌ Task canceled. It is now back in the public queue.")
        except: await context.bot.send_message(user_id, "❌ Task canceled. It is now back in the public queue.")
    
    elif data.startswith("subm_t_"):
        tid = int(data.split("_")[2])
        await db_query("UPDATE tasks SET status = 'pending_approval' WHERE id = ?", (tid,), commit=True)
        await query.message.edit_text("⏳ Submitted for approval. You can now get another task!")
        
        t_info = await db_query("SELECT assigned_to, task_data FROM tasks WHERE id=?", (tid,), fetchone=True)
        try: 
            t_user, t_pass = t_info[1].split(":")
        except: 
            t_user, t_pass = "Error", "Error"
        
        adm_msg = f"TASK ID :- \"{tid}\"\n\nUSER ID :- \"{t_info[0]}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nSUBMIT TIME:- \"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\""
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(admin, adm_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_t_{tid}", style="success"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_t_{tid}", style="danger")]]))
            except: pass

    elif data.startswith(("adm_app_t_", "adm_rej_t_")):
        parts = data.split("_")
        act = parts[1]
        tid = int(parts[3])
        
        uid_row = await db_query("SELECT assigned_to FROM tasks WHERE id=?", (tid,), fetchone=True)
        uid = uid_row[0] if uid_row else None
        
        if act == 'app':
            await db_query("UPDATE tasks SET status='completed' WHERE id=?", (tid,), commit=True)
            if uid:
                t_pr_row = await db_query("SELECT value FROM config WHERE key='task_price'", fetchone=True)
                t_pr = float(t_pr_row[0]) if t_pr_row else 15.0
                await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (t_pr, uid), commit=True)
            status_msg = "APPROVED"
        else:
            await reset_task_password(tid)
            await db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=?", (tid,), commit=True)
            status_msg = "REJECTED"
        
        if uid:
            try:
                await context.bot.send_message(uid, f"TASK ID :- \"{tid}\"\n\nSTATUS:- \"{status_msg}\"\n\nREMARKS:- \"Processed by Admin\"")
            except:
                pass
                
        await query.message.edit_text(f"✅ Task {tid} processed as {status_msg}.")

    # --- PROCESS OLD GMAIL APPROVALS/REJECTIONS ---
    elif data.startswith(("adm_app_om_", "adm_rej_om_")):
        parts = data.split("_")
        act = parts[1]
        oid = int(parts[3])

        om_row = await db_query("SELECT user_id, email_user, email_pass, status FROM old_mails WHERE id=?", (oid,), fetchone=True)
        if not om_row or om_row[3] != 'pending':
            await query.message.edit_text("❌ Already processed or not found.")
            return
        
        ouid, o_user, o_pass, _ = om_row

        if act == 'app':
            await db_query("UPDATE old_mails SET status='approved' WHERE id=?", (oid,), commit=True)
            o_amt_row = await db_query("SELECT value FROM config WHERE key='old_mail_amount'", fetchone=True)
            o_amt = float(o_amt_row[0]) if o_amt_row else 50.0
            await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (o_amt, ouid), commit=True)
            
            try:
                await context.bot.send_message(ouid, f"✅ **Old Gmail Approved!**\nYour account `{o_user}` was verified successfully. ₹{o_amt} credited to your wallet.", parse_mode="Markdown")
            except: pass
            await query.message.edit_text(f"✅ Old Gmail ID {oid} APPROVED.")
        else:
            await db_query("UPDATE old_mails SET status='rejected' WHERE id=?", (oid,), commit=True)
            try:
                await context.bot.send_message(ouid, f"❌ **Old Gmail Rejected**\nYour account `{o_user}` was rejected during verification setup.", parse_mode="Markdown")
            except: pass
            await query.message.edit_text(f"❌ Old Gmail ID {oid} REJECTED.")

    elif data == "wallet":
        u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        await query.message.edit_text(f"💳 Balance: ₹{u[0]:.2f}\nUPI: `{u[1] or 'None'}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Link UPI", callback_data="add_upi")], [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")], [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))
    
    elif data == "add_upi": 
        context.user_data['state'] = 'WAITING_UPI'
        await query.message.reply_text("Send UPI:")
    
    elif data == "withdraw": 
        kb = [
            [InlineKeyboardButton("⚡ Instant Withdrawal", callback_data="wd_instant")],
            [InlineKeyboardButton("🏦 Manual Withdrawal", callback_data="wd_manual")],
            [InlineKeyboardButton("⬅️ Back", callback_data="wallet")]
        ]
        await query.message.edit_text("Select Withdrawal Method:", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data in ["wd_instant", "wd_manual"]:
        wd_type = data.split('_')[1].upper()
        
        # Check specific toggles separately
        if wd_type == 'INSTANT':
            c_check = await db_query("SELECT value FROM config WHERE key='instant_wd_status'", fetchone=True)
            if not c_check or c_check[0] == 'OFF':
                await query.message.reply_text("⚠️ Instant withdrawals are currently turned OFF by Admin.")
                return
        else:
            c_check = await db_query("SELECT value FROM config WHERE key='manual_wd_status'", fetchone=True)
            if not c_check or c_check[0] == 'OFF':
                await query.message.reply_text("⚠️ Manual withdrawals are currently turned OFF by Admin.")
                return

        u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        if not u[1]: 
            await query.message.reply_text("❌ Please link your UPI ID first from the wallet menu.")
            return
        if u[0] <= 0: 
            await query.message.reply_text("❌ Insufficient balance.")
            return
        
        context.user_data['state'] = f'WAITING_WD_AMOUNT_{wd_type}'
        
        max_wd_row = await db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)
        max_wd = float(max_wd_row[0]) if max_wd_row else 10000.0
        
        await query.message.reply_text(f"Enter Amount for {wd_type} withdrawal (Wallet: ₹{u[0]}, Max/Txn: ₹{max_wd}):")

    elif data in ["wd_confirm", "wd_cancel"]:
        temp_wd = context.user_data.pop('temp_wd', None)
        if not temp_wd:
            await query.message.edit_text("❌ Session expired or request already processed.")
            return
            
        if data == "wd_cancel":
            await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (temp_wd['amount'], user_id), commit=True)
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
                    try: await context.bot.send_message(a, adm_wd_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_w_{wid}", style="success"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_w_{wid}", style="danger")]]))
                    except: pass

            elif wd_type == 'INSTANT':
                api_url_row = await db_query("SELECT value FROM config WHERE key='payment_api_url'", fetchone=True)
                if not api_url_row or not api_url_row[0]:
                    await query.message.edit_text("❌ API not configured by admin. Refunding balance.")
                    await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, user_id), commit=True)
                    return
                
                formatted_url = api_url_row[0].replace("{upi id}", u_upi).replace("{amount}", str(actual_amt))
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
                
                status_api_url_row = await db_query("SELECT value FROM config WHERE key='payment_status_url'", fetchone=True)
                status_api_url = status_api_url_row[0] if status_api_url_row else ''
                
                params = {
                    'uid': user_id,
                    'name': update.effective_user.first_name or update.effective_user.username or "User",
                    'amt': actual_amt,
                    'upi': u_upi,
                    'txnid': txn_id,
                    'api': status_api_url
                }
                
                query_string = urllib.parse.urlencode(params)
                full_webapp_url = f"https://mini-app-2-kappa.vercel.app/index1.html?{query_string}"
                
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Check payment status", web_app=WebAppInfo(url=full_webapp_url))]])
                await query.message.edit_text("YOUR WITHDRAWAL IS SUCCESSFULLY PAID FROM GATEWAY ✅\n\n⚠️IF NOT RECEIVED THEN CONTACT SUPPORT", reply_markup=btn)
                
                adm_msg = f"⚡ **Instant Withdrawal Triggered**\n\nUSER ID :- `{user_id}`\nUPI ID :- `{u_upi}`\nGROSS AMOUNT :- `₹{amt}`\nACTUAL TRANSFERRED :- `₹{actual_amt}`\nTAX CUT :- `₹{amt - actual_amt}`\nTIME :- `{get_ist_time()}`\n\nAPI RESPONSE :- `{comment}`"
                for admin in ADMIN_IDS:
                    try: await context.bot.send_message(admin, adm_msg, parse_mode="Markdown")
                    except: pass
                    
                cur_total_row = await db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)
                cur_total = float(cur_total_row[0]) if cur_total_row else 0.0
                await set_config('total_wd_processed', str(cur_total + actual_amt))

    elif data == "refer_earn":
        bot_me = await context.bot.get_me()
        c = (await db_query("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,), fetchone=True))[0]
        await query.message.edit_text(f"👥 Referrals: {c}\nLink: `t.me/{bot_me.username}?start={user_id}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))
    
    elif data == "adm_bulk": 
        context.user_data['state'] = 'ADM_WAITING_BULK'
        await query.message.reply_text("Format: `u,u,u,...` (Usernames separated by comma)")
    
    elif data == "adm_pending_tasks" and user_id in ADMIN_IDS:
        tks = await db_query("SELECT id, task_data FROM tasks WHERE status='available'", fetchall=True)
        kb = [[InlineKeyboardButton("🗑️ Clear All", callback_data="adm_del_all_tasks")], [InlineKeyboardButton("🗑️ Delete Indiv", callback_data="adm_del_indiv_task")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
        msg = "📋 Available Tasks:\n\n" + "\n".join([f"ID {t[0]}: {t[1].split(':')[0]}" for t in tks]) if tks else "No available tasks."
        await query.message.edit_text(msg[:4000], reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "adm_del_all_tasks" and user_id in ADMIN_IDS:
        await db_query("DELETE FROM tasks WHERE status='available'", commit=True)
        await query.message.reply_text("Queue cleared.")
    
    elif data == "adm_del_indiv_task" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_DEL_INDIV'
        await query.message.reply_text("Enter Task ID to delete:")

    elif data == "adm_list_task_app":
        p = await db_query("SELECT id, assigned_to, task_data, assigned_at FROM tasks WHERE status='pending_approval'", fetchall=True)
        if not p: 
            await query.message.reply_text("No pending approvals.")
            return
        for t in p: 
            tid, assigned_to, task_data, assigned_at = t
            try: 
                t_user, t_pass = task_data.split(":")
            except: 
                t_user, t_pass = "Error", "Error"
            
            detail_msg = (
                f"📝 **PENDING TASK APPROVAL**\n\n"
                f"TASK ID :- \"{tid}\"\n"
                f"USER ID :- \"{assigned_to}\"\n"
                f"USERNAME :- `{t_user}`\n"
                f"PASSWORD :- `{t_pass}`\n"
                f"SUBMIT TIME:- \"{assigned_at if assigned_at else 'N/A'}\""
            )
            await query.message.reply_text(detail_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_t_{tid}", style="success"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_t_{tid}", style="danger")]]))

    elif data == "adm_list_wd":
        w = context.bot_data.get('withdrawals', {})
        if not w: 
            await query.message.reply_text("No pending Manual WD.")
            return
        for k, v in list(w.items()): 
            detail_wd_msg = (
                f"🏧 **PENDING MANUAL WITHDRAWAL**\n\n"
                f"REQUEST ID :- \"{k}\"\n"
                f"USER ID :- \"{v['user_id']}\"\n"
                f"UPI ID :- `{v['upi']}`\n"
                f"AMOUNT :- \"{v['amount']}\"\n"
                f"WITHDRAWAL TIME :- \"{v['time']}\""
            )
            await query.message.reply_text(detail_wd_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_w_{k}", style="success"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_w_{k}", style="danger")]]))
    
    elif data.startswith(("adm_app_w_", "adm_rej_w_")):
        parts = data.split("_")
        act = parts[1]
        wid = parts[3]
        
        wd = context.bot_data.get('withdrawals', {}).pop(wid, None)
        if wd:
            if act == 'app':
                cur_total_row = await db_query("SELECT value FROM config WHERE key='total_wd_processed'", fetchone=True)
                cur_total = float(cur_total_row[0]) if cur_total_row else 0.0
                await set_config('total_wd_processed', str(cur_total + wd['amount']))
                status_msg = "APPROVED"
            else:
                await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (wd['amount'], wd['user_id']), commit=True)
                status_msg = "REJECTED"
            
            try:
                await context.bot.send_message(wd['user_id'], f"WITHDRAWAL STATUS:- \"{status_msg}\"\n\nWITHDRAWAL TIME :- \"{get_ist_time()}\"\n\nREMARKS :- \"Processed by Admin\"")
            except:
                pass
            await query.message.edit_text(f"✅ Withdrawal {wid} processed as {status_msg}.")
        else:
            await query.message.edit_text("❌ Withdrawal request already processed or not found.")
    
    elif data == "adm_broadcast" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_BROADCAST'
        await query.message.reply_text("Msg:")
        
    elif data == "adm_dm" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_DM'
        await query.message.reply_text("Format: `id:msg`")
        
    elif data == "adm_ban" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_BAN'
        await query.message.reply_text("ID to ban:")
        
    elif data == "adm_unban" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_UNBAN'
        await query.message.reply_text("ID to unban:")
        
    elif data == "adm_tog_bot" and user_id in ADMIN_IDS:
        c_row = await db_query("SELECT value FROM config WHERE key='bot_status'", fetchone=True)
        c = c_row[0] if c_row else 'ON'
        s = 'OFF' if c == 'ON' else 'ON'
        await set_config('bot_status', s)
        await query.message.reply_text(f"Bot Status turned {s}")

    elif data == "adm_tog_inst_wd" and user_id in ADMIN_IDS:
        c_row = await db_query("SELECT value FROM config WHERE key='instant_wd_status'", fetchone=True)
        c = c_row[0] if c_row else 'ON'
        s = 'OFF' if c == 'ON' else 'ON'
        await set_config('instant_wd_status', s)
        await query.message.reply_text(f"⚡ Instant WD turned {s}")

    elif data == "adm_tog_manu_wd" and user_id in ADMIN_IDS:
        c_row = await db_query("SELECT value FROM config WHERE key='manual_wd_status'", fetchone=True)
        c = c_row[0] if c_row else 'ON'
        s = 'OFF' if c == 'ON' else 'ON'
        await set_config('manual_wd_status', s)
        await query.message.reply_text(f"🏦 Manual WD turned {s}")
    
    elif data == "adm_chk_bal" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_CHK_BAL'
        await query.message.reply_text("ID:")
        
    elif data == "adm_mod_bal" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_MOD_BAL'
        await query.message.reply_text("Format: `id:amt`")
        
    elif data == "adm_top_bal" and user_id in ADMIN_IDS:
        t = await db_query("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
        await query.message.reply_text("\n".join([f"{i+1}) {r[0]} - ₹{r[1]:.2f}" for i, r in enumerate(t)]))
    
    elif data == "adm_chg_text" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_CHG_TEXT'
        await query.message.reply_text("📝 Enter New Menu Text:")
    
    elif data == "adm_min_wd" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_SET_MIN_WD'
        await query.message.reply_text("Enter New Minimum Withdrawal Amount:")
        
    elif data == "adm_max_wd" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_SET_MAX_WD'
        await query.message.reply_text("Enter New Maximum Withdrawal Amount:")
        
    elif data == "adm_wd_tax" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_SET_WD_TAX'
        await query.message.reply_text("Enter New Instant Withdrawal Tax Amount (e.g. 5):")

    elif data == "adm_set_task_price" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_SET_TASK_PRICE'
        await query.message.reply_text("Enter New Registration Task Price (INR):")

    elif data == "adm_set_old_mail_amt" and user_id in ADMIN_IDS:
        context.user_data['state'] = 'ADM_SET_OLD_MAIL_AMT'
        await query.message.reply_text("Enter Payout Amount for Old Gmails (INR):")

    elif data == "adm_list_old_mails" and user_id in ADMIN_IDS:
        pending = await db_query("SELECT id, user_id, email_user, email_pass FROM old_mails WHERE status='pending'", fetchall=True)
        if not pending:
            await query.message.reply_text("📭 No pending old mails found.")
            return
        for item in pending:
            oid, ouid, o_user, o_pass = item
            msg = (
                f"📥 **PENDING OLD GMAIL APPLICATION**\n\n"
                f"ID: `{oid}`\n"
                f"USER ID: `{ouid}`\n"
                f"USERNAME: `{o_user}`\n"
                f"PASSWORD: `{o_pass}`"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_om_{oid}", style="success"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_om_{oid}", style="danger")
            ]])
            await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=kb, parse_mode="Markdown")
    
    elif data == "adm_task_status_lookup" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_LOOKUP_TASK'
        await query.message.reply_text("Task ID or Username:")
        
    elif data == "adm_task_checkup" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_BULK_CHECK'
        await query.message.reply_text("Enter task usernames separated by comma or newline:")
        
    elif data == "adm_task_pullback" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_PULLBACK'
        await query.message.reply_text("Enter Task ID or Username to Pullback:")
        
    elif data == "adm_set_api" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_SET_API'
        await query.message.reply_text("Enter API Link (Use `{upi id}` and `{amount}` as placeholders):")
        
    elif data == "adm_set_status_link" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_SET_STATUS_LINK'
        await query.message.reply_text("Enter Status API Link (Use `{txnid}` as a placeholder if required by the API):")
    
    elif data == "adm_manage_channels" and user_id in ADMIN_IDS:
        kb = [[InlineKeyboardButton("➕ Add", callback_data="adm_add_chan"), InlineKeyboardButton("❌ Rem", callback_data="adm_rem_chan")], [InlineKeyboardButton("📋 List", callback_data="adm_list_chan")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
        await query.message.edit_text("Channels:", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data == "adm_add_chan" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_ADD_CHAN_DATA'
        await query.message.reply_text("Format -> chat_id:invite_link")
        
    elif data == "adm_rem_chan" and user_id in ADMIN_IDS: 
        context.user_data['state'] = 'ADM_REM_CHAN_DATA'
        await query.message.reply_text("Enter chat_id to remove:")

    elif data == "adm_list_chan" and user_id in ADMIN_IDS:
        channels = await db_query("SELECT chat_id, invite_link FROM channels", fetchall=True)
        msg = "📋 Active Channels:\n\n" + "\n".join([f"`{c[0]}` - {c[1]}" for c in channels]) if channels else "No active channels."
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_manage_channels")]]))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get('state')

    user = await db_query("SELECT is_banned, device_verified FROM users WHERE user_id = ?", (user_id,), fetchone=True)
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
        await update.message.reply_text("⚠️ Join channels first to continue.", reply_markup=await get_channel_verification_keyboard())
        return

    if text == "📝 Get Task":
        active = await db_query("SELECT id FROM tasks WHERE assigned_to = ? AND status = 'assigned'", (user_id,), fetchone=True)
        if active: await update.message.reply_text("⚠️ Finish active task first."); return
        task = await db_query("SELECT id, task_data FROM tasks WHERE status = 'available' LIMIT 1", fetchone=True)
        if not task: await update.message.reply_text("📭 No tasks."); return
        
        tid, tdata = task
        try: t_user, t_pass = tdata.split(":")
        except: await update.message.reply_text("⚠️ Task Error."); return
        
        msg_text = f"TASK ID :- \"{tid}\"\n\nUSERNAME :- `{t_user}`\n\nPASSWORD :- `{t_pass}`\n\nTASK TIMEOUT IN 30MINS."
        sent_msg = await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit", callback_data=f"subm_t_{tid}"), InlineKeyboardButton("❌ Cancel", callback_data=f"canc_t_{tid}")]]))
        
        await db_query("UPDATE tasks SET status = 'assigned', assigned_to = ?, assigned_at = ?, message_id = ? WHERE id = ?", (user_id, datetime.now().isoformat(), sent_msg.message_id, tid), commit=True)
        return

    elif text == "🤝 Sell Old Gmail":
        context.user_data['state'] = 'WAITING_OLD_EMAIL_USER'
        await update.message.reply_text("📩 Please send the old Gmail **username**:\n(GMAIL MUST BE 3 MONTHS OLD)")
        return

    elif text == "💰 Wallet":
        u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
        await update.message.reply_text(f"💳 Balance: ₹{u[0]:.2f}\nUPI: `{u[1] or 'None'}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Link UPI", callback_data="add_upi")], [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]]))
        return

    elif text == "💸 Withdraw":
        kb = [
            [InlineKeyboardButton("⚡ Instant Withdrawal", callback_data="wd_instant")],
            [InlineKeyboardButton("🏦 Manual Withdrawal", callback_data="wd_manual")]
        ]
        await update.message.reply_text("Choose withdrawal method:", reply_markup=InlineKeyboardMarkup(kb))
        return

    elif text == "👥 Refer & Earn":
        bot_me = await context.bot.get_me()
        c = (await db_query("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,), fetchone=True))[0]
        await update.message.reply_text(f"👥 Referrals: {c}\nLink: `t.me/{bot_me.username}?start={user_id}`", parse_mode="Markdown")
        return

    elif text == "💳 Pay User":
        context.user_data['state'] = 'WAITING_P2P_DATA'
        await update.message.reply_text("💸 Enter transfer details using format -> `user_id:amount` \n*(Example: `6197579049:50`)*")
        return

    elif text == "📞 Support":
        admin_contact_url = f"tg://openmessage?user_id=7930010364"
        await update.message.reply_text(f"📞 Contact Support: {admin_contact_url}")
        return

    elif text == "⚙️ Admin Panel" and user_id in ADMIN_IDS:
        await update.message.reply_text(await get_admin_panel_text(), parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())
        return

    if not state: return

    try:
        if state == 'WAITING_OLD_EMAIL_USER':
            context.user_data['old_email_username'] = text
            context.user_data['state'] = 'WAITING_OLD_EMAIL_PASS'
            await update.message.reply_text("🔒 Now enter the **password** for this specific Gmail address:")
            return

        elif state == 'WAITING_OLD_EMAIL_PASS':
            context.user_data['state'] = None
            o_username = context.user_data.pop('old_email_username', 'Unknown')
            o_password = text
            
            # Insert into database logs
            res = await db_query(
                "INSERT INTO old_mails (user_id, email_user, email_pass, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                (user_id, o_username, o_password, get_ist_time()), commit=True, fetchone=True
            )
            oid = res[0] if res else 0

            await update.message.reply_text("⏳ Your old Gmail details have been submitted to admins for age verification!")

            # Admin alert routing loops
            adm_msg = (
                f"🤝 **NEW OLD GMAIL FOR SALE**\n\n"
                f"ID: `{oid}`\n"
                f"USER ID: `{user_id}`\n"
                f"USERNAME: `{o_username}`\n"
                f"PASSWORD: `{o_password}`"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_om_{oid}", style="success"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_om_{oid}", style="danger")
            ]])
            for admin in ADMIN_IDS:
                try: await context.bot.send_message(admin, adm_msg, reply_markup=kb, parse_mode="Markdown")
                except: pass
            return

        elif state == 'WAITING_P2P_DATA':
            context.user_data['state'] = None
            if ":" not in text:
                await update.message.reply_text("❌ Invalid format. Please resend using `user_id:amount` format structure.")
                return
            
            try:
                target_uid_str, target_amt_str = text.split(":", 1)
                target_uid = int(target_uid_str.strip())
                transfer_amount = float(target_amt_str.strip())
            except ValueError:
                await update.message.reply_text("❌ Processing error. Verify structure parameters match numbers fields perfectly.")
                return

            if transfer_amount <= 0:
                await update.message.reply_text("❌ You can't deduct balance of others.")
                return

            sender_row = await db_query("SELECT balance FROM users WHERE user_id=?", (user_id,), fetchone=True)
            if not sender_row or sender_row[0] < transfer_amount:
                await update.message.reply_text("❌ Insufficient funds in wallet balance.")
                return

            receiver_exists = await db_query("SELECT user_id FROM users WHERE user_id=?", (target_uid,), fetchone=True)
            if not receiver_exists:
                await update.message.reply_text("❌ Receiver User ID not found inside database records.")
                return

            # Perform balance swap atomically
            await db_query("UPDATE users SET balance = balance - ? WHERE user_id = ?", (transfer_amount, user_id), commit=True)
            await db_query("UPDATE users SET balance = balance + ? WHERE user_id = ?", (transfer_amount, target_uid), commit=True)

            await update.message.reply_text(f"✅ Transferred ₹{transfer_amount:.2f} successfully to User `{target_uid}`!")
            try:
                await context.bot.send_message(target_uid, f"💰 You received ₹{transfer_amount:.2f} internally from User `{user_id}`!")
            except: pass
            return

        context.user_data['state'] = None

        if state == 'ADM_VERIFY_USER' and user_id in ADMIN_IDS:
            if text.isdigit():
                target_id = int(text)
                await db_query("UPDATE users SET device_verified=1 WHERE user_id=?", (target_id,), commit=True)
                await update.message.reply_text(f"✅ User {target_id} has been manually verified and can now access the bot.")
                try:
                    menu_text_row = await db_query("SELECT value FROM config WHERE key='menu_text'", fetchone=True)
                    menu_text = menu_text_row[0] if menu_text_row else "Welcome to the Task Bot! Complete tasks to earn INR."
                    await context.bot.send_message(
                        chat_id=target_id, 
                        text="✅ You have been manually verified by an Admin!\n\n" + menu_text, 
                        reply_markup=get_main_menu_keyboard(target_id)
                    )
                except: pass
            else:
                await update.message.reply_text("❌ Invalid User ID. Please enter numbers only.")

        elif state == 'WAITING_UPI': 
            await db_query("UPDATE users SET upi_id=? WHERE user_id=?", (text, user_id), commit=True)
            await update.message.reply_text("✅ UPI Linked Successfully.")
        
        elif state.startswith('WAITING_WD_AMOUNT_'):
            wd_type = state.split('_')[3]
            try: amt = float(text)
            except: await update.message.reply_text("❌ Invalid amount format."); return
            
            u = await db_query("SELECT balance, upi_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
            
            min_wd_row = await db_query("SELECT value FROM config WHERE key='min_withdrawal'", fetchone=True)
            min_wd = float(min_wd_row[0]) if min_wd_row else 10.0
            
            max_wd_row = await db_query("SELECT value FROM config WHERE key='max_withdrawal'", fetchone=True)
            max_wd = float(max_wd_row[0]) if max_wd_row else 10000.0
            
            wd_tax_row = await db_query("SELECT value FROM config WHERE key='withdrawal_tax'", fetchone=True)
            wd_tax = float(wd_tax_row[0]) if wd_tax_row else 0.0
            
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
                        
                await db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, user_id), commit=True)
                context.user_data['temp_wd'] = {'amount': amt, 'actual_amount': actual_amt, 'type': wd_type, 'upi': u[1]}
                confirm_msg = f"⚠️ **Confirm Your Withdrawal**\n\n🏦 Linked UPI ID: `{u[1]}`\n💰 Entered Amount: `₹{amt}`"
                if wd_type == 'INSTANT': confirm_msg += f"\n📉 Actual Amount Received (After Tax): `₹{actual_amt}`"

                kb = [[InlineKeyboardButton("✅ Confirm", callback_data="wd_confirm"), InlineKeyboardButton("❌ Cancel", callback_data="wd_cancel")]]
                await update.message.reply_text(confirm_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await update.message.reply_text("❌ Invalid amount or insufficient balance.")

        elif state == 'ADM_LOOKUP_TASK' and user_id in ADMIN_IDS:
            if text.isdigit(): t = await db_query("SELECT status, assigned_to, assigned_at, task_data FROM tasks WHERE id=?", (int(text),), fetchone=True)
            else: t = await db_query("SELECT status, assigned_to, assigned_at, task_data FROM tasks WHERE task_data LIKE ?", (f"{text}:%",), fetchone=True)
                
            if t:
                status_db, assigned_to_db, assigned_at_db, task_data_db = t
                display_status = {'available': 'NOT ASSIGNED', 'assigned': 'PENDING', 'pending_approval': 'PENDING', 'completed': 'COMPLETED'}.get(status_db, 'NOT ASSIGNED')
                try: task_user, task_pass = task_data_db.split(":")
                except: task_user, task_pass = "N/A", "N/A"
                    
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

        elif state == 'ADM_BULK_CHECK' and user_id in ADMIN_IDS:
            res = []
            for u in text.replace('\n', ',').split(','):
                u = u.strip()
                if not u: continue
                t = await db_query("SELECT status, task_data FROM tasks WHERE task_data LIKE ?", (f"{u}:%",), fetchone=True)
                if t:
                    tu, tp = t[1].split(":")
                    res.append(f"`{tu}` - `{tp}`" if t[0] == 'completed' else f"{tu} - PENDING")
                else: res.append(f"{u} - NOT FOUND")
            await update.message.reply_text("\n".join(res), parse_mode="Markdown")

        elif state == 'ADM_PULLBACK' and user_id in ADMIN_IDS:
            if text.isdigit(): t = await db_query("SELECT id, assigned_to, message_id, status FROM tasks WHERE id=?", (int(text),), fetchone=True)
            else: t = await db_query("SELECT id, assigned_to, message_id, status FROM tasks WHERE task_data LIKE ?", (f"{text}:%",), fetchone=True)
                
            if t:
                tid, uid, mid, st = t
                if st == 'assigned' and uid:
                    if mid:
                        try: await context.bot.delete_message(chat_id=uid, message_id=mid)
                        except: pass
                    try: await context.bot.send_message(uid, "THE TASK IS PULLED BY ADMINS PLEASE GET A NEW TASKS")
                    except: pass
                
                await reset_task_password(tid)
                await db_query("UPDATE tasks SET status='available', assigned_to=NULL, assigned_at=NULL, message_id=NULL WHERE id=?", (tid,), commit=True)
                await update.message.reply_text(f"✅ Task pulled back successfully and reset into the queue.")
            else:
                await update.message.reply_text("❌ Task not found.")

        elif state == 'ADM_SET_API' and user_id in ADMIN_IDS:
            await set_config('payment_api_url', text)
            await update.message.reply_text("✅ Payment API Link Updated Successfully.")
            
        elif state == 'ADM_SET_STATUS_LINK' and user_id in ADMIN_IDS:
            await set_config('payment_status_url', text)
            await update.message.reply_text("✅ Payment Status Link Updated Successfully.")

        elif state == 'ADM_SET_MIN_WD' and user_id in ADMIN_IDS:
            try: float(text)
            except: await update.message.reply_text("❌ Need numbers."); return
            await set_config('min_withdrawal', text)
            await update.message.reply_text("✅ Min Withdrawal Amount Updated.")
            
        elif state == 'ADM_SET_MAX_WD' and user_id in ADMIN_IDS:
            try: float(text)
            except: await update.message.reply_text("❌ Need numbers."); return
            await set_config('max_withdrawal', text)
            await update.message.reply_text("✅ Max Withdrawal Amount Updated.")
            
        elif state == 'ADM_SET_WD_TAX' and user_id in ADMIN_IDS:
            try: float(text)
            except: await update.message.reply_text("❌ Need numbers."); return
            await set_config('withdrawal_tax', text)
            await update.message.reply_text("✅ Withdrawal Tax Updated.")

        elif state == 'ADM_SET_TASK_PRICE' and user_id in ADMIN_IDS:
            try: float(text)
            except: await update.message.reply_text("❌ Numbers only parameters supported."); return
            await set_config('task_price', text)
            await update.message.reply_text(f"✅ Registration Task reward modified to: ₹{text}")

        elif state == 'ADM_SET_OLD_MAIL_AMT' and user_id in ADMIN_IDS:
            try: float(text)
            except: await update.message.reply_text("❌ Numbers only parameters supported."); return
            await set_config('old_mail_amount', text)
            await update.message.reply_text(f"✅ Old Gmail submission credit amount set to: ₹{text}")
            
        elif state == 'ADM_CHG_TEXT' and user_id in ADMIN_IDS: 
            await set_config('menu_text', text)
            await update.message.reply_text("✅ Menu Text Updated Successfully.")

        elif state == 'ADM_ADD_CHAN_DATA' and user_id in ADMIN_IDS:
            if ":" in text: 
                cid, lnk = text.split(":", 1)
                await set_channel(cid.strip(), lnk.strip())
                await update.message.reply_text("✅ Channel added.")
            else:
                await update.message.reply_text("❌ Format must be chat_id:invite_link")
        
        elif state == 'ADM_REM_CHAN_DATA' and user_id in ADMIN_IDS: 
            await db_query("DELETE FROM channels WHERE chat_id=?", (text,), commit=True)
            await update.message.reply_text("✅ Channel removed.")
        
        elif state == 'ADM_DEL_INDIV' and user_id in ADMIN_IDS:
            if text.isdigit(): 
                await db_query("DELETE FROM tasks WHERE id=? AND status='available'", (int(text),), commit=True)
                await update.message.reply_text("✅ Task deleted.")
            
        elif state == 'ADM_WAITING_BULK' and user_id in ADMIN_IDS:
            for u in text.split(","): 
                u = u.strip()
                if u:
                    p = generate_password()
                    await db_query("INSERT INTO tasks (task_data) VALUES (?)", (f"{u}:{p}",), commit=True)
            await update.message.reply_text("✅ Bulk tasks added.")

        elif state == 'ADM_BROADCAST' and user_id in ADMIN_IDS:
            for u in await db_query("SELECT user_id FROM users", fetchall=True):
                try: await context.bot.send_message(u[0], f"📢 **Announcement**\n\n{text}", parse_mode="Markdown")
                except: pass
            await update.message.reply_text("✅ Broadcast Sent.")
                
        elif state == 'ADM_DM' and user_id in ADMIN_IDS:
            if ":" in text:
                target, msg = text.split(":", 1)
                try: 
                    await context.bot.send_message(int(target), f"💬 **Admin Msg:** {msg}")
                    await update.message.reply_text("✅ Direct message sent.")
                except: await update.message.reply_text("❌ Failed to send DM. User might have blocked the bot.")
                
        elif state == 'ADM_BAN' and user_id in ADMIN_IDS: 
            await db_query("UPDATE users SET is_banned=1 WHERE user_id=?", (int(text),), commit=True)
            await update.message.reply_text("✅ User banned.")
            
        elif state == 'ADM_UNBAN' and user_id in ADMIN_IDS: 
            await db_query("UPDATE users SET is_banned=0 WHERE user_id=?", (int(text),), commit=True)
            await update.message.reply_text("✅ User unbanned.")
            
        elif state == 'ADM_CHK_BAL' and user_id in ADMIN_IDS:
            b = await db_query("SELECT balance FROM users WHERE user_id=?", (int(text),), fetchone=True)
            await update.message.reply_text(f"Bal: ₹{b[0] if b else 'N/A'}")
            
        elif state == 'ADM_MOD_BAL' and user_id in ADMIN_IDS:
            if ":" in text:
                target, amt = text.split(":", 1)
                await db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (float(amt), int(target)), commit=True)
                await update.message.reply_text("✅ Balance successfully updated.")
                
    except Exception as e:
        logger.error(f"Critical error processing text state: {e}")
        await update.message.reply_text(f"❌ **Database Processing Error**:\n`{str(e)}`", parse_mode="Markdown")

def main():
    app = Application.builder().token(TOKEN).post_init(setup_db).build()
    
    app.job_queue.run_repeating(task_timeout_monitor, interval=60)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    app.run_polling()

if __name__ == '__main__': main()
