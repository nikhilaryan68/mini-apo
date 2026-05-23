from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os
import json

app = Flask(__name__)

# Load variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

@app.route('/')
def home():
    return render_template('index.html') 

@app.route('/verify', methods=['POST'])
def verify_user():
    data = request.json
    telegram_id = data.get('telegram_id')
    device_token = data.get('device_token')
    
    # --- START OF VERIFICATION & BAN LOGIC ---
    conn = sqlite3.connect('task_bot.db')
    cursor = conn.cursor()
    
    # 1. Check if device is linked to another account
    cursor.execute("SELECT user_id FROM users WHERE device_token = ? AND device_token IS NOT NULL", (device_token,))
    existing_owner = cursor.fetchone()
    
    if existing_owner and existing_owner[0] != telegram_id:
        # AUTO-BAN THE CHEATER
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "blocked", "reason": "Access Denied: This device is linked to another account."})

    # 2. Check if user is already verified
    cursor.execute("SELECT device_verified FROM users WHERE user_id = ?", (telegram_id,))
    user = cursor.fetchone()
    
    if user and user[0] == 1:
        conn.close()
        send_telegram_menu(telegram_id) # Send menu again just in case
        return jsonify({"status": "already_verified", "message": "Already verified."})

    # 3. New Verification - Register the device
    cursor.execute("UPDATE users SET device_verified = 1, device_token = ? WHERE user_id = ?", (device_token, telegram_id))
    conn.commit()
    conn.close()
    
    # Send menu immediately after verification
    send_telegram_menu(telegram_id)
    return jsonify({"status": "success", "message": "Verified."})
    # --- END OF VERIFICATION & BAN LOGIC ---

def send_telegram_menu(telegram_id):
    """Sends the Main Menu directly to the user via Telegram API"""
    if not BOT_TOKEN:
        return

    # Fetch custom menu text from database
    menu_text = "Welcome to the Task Bot! Complete tasks to earn INR."
    try:
        conn = sqlite3.connect('task_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key='menu_text'")
        row = cursor.fetchone()
        if row: menu_text = row[0]
        conn.close()
    except: pass

    # Prepare Reply Keyboard
    admin_ids = [int(x.strip()) for x in ADMIN_IDS_RAW.split(',') if x.strip().isdigit()]
    keyboard = [
        [{"text": "📝 Get Task"}],
        [{"text": "💰 Wallet"}, {"text": "💸 Withdraw"}],
        [{"text": "👥 Refer & Earn"}, {"text": "📞 Support"}]
    ]
    if int(telegram_id) in admin_ids:
        keyboard.append([{"text": "⚙️ Admin Panel"}])

    payload = {
        "chat_id": telegram_id,
        "text": f"✅ Device Successfully Verified!\n\n{menu_text}",
        "reply_markup": json.dumps({"keyboard": keyboard, "resize_keyboard": True})
    }
    
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
