from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os
import json

app = Flask(__name__)

# Basic storage
used_devices = {}
used_ips = {}

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
    
    conn = sqlite3.connect('task_bot.db')
    cursor = conn.cursor()
    
    # 1. Check if device is taken by someone else
    cursor.execute("SELECT user_id FROM users WHERE device_token = ? AND device_token IS NOT NULL", (device_token,))
    existing_owner = cursor.fetchone()
    
    if existing_owner and existing_owner[0] != telegram_id:
        # BAN THIS USER IMMEDIATELY
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "blocked", "reason": "Access Denied: Device already linked to another account."})

    # 2. Check if this specific user is ALREADY verified
    cursor.execute("SELECT device_verified, device_token FROM users WHERE user_id = ?", (telegram_id,))
    user = cursor.fetchone()
    
    if user and user[0] == 1:
        conn.close()
        send_telegram_menu(telegram_id)
        return jsonify({"status": "already_verified", "message": "Already verified."})

    # 3. New Verification - Register the device
    cursor.execute("UPDATE users SET device_verified = 1, device_token = ? WHERE user_id = ?", (device_token, telegram_id))
    conn.commit()
    conn.close()
    
    send_telegram_menu(telegram_id)
    return jsonify({"status": "success", "message": "Verified."})

def send_telegram_menu_debug(telegram_id):
    if not BOT_TOKEN:
        print("DEBUG: BOT_TOKEN is missing in Environment Variables!")
        return

    # Prepare Payload
    reply_keyboard = [
        [{"text": "📝 Get Task"}],
        [{"text": "💰 Wallet"}, {"text": "💸 Withdraw"}],
        [{"text": "👥 Refer & Earn"}, {"text": "📞 Support"}]
    ]
    
    payload = {
        "chat_id": telegram_id,
        "text": "✅ Verification Successful! Welcome to the menu.",
        "reply_markup": json.dumps({
            "keyboard": reply_keyboard,
            "resize_keyboard": True
        })
    }
    
    # Send request and LOG the response
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(url, data=payload)
    
    print(f"DEBUG: Telegram API Response Code: {response.status_code}")
    print(f"DEBUG: Telegram API Response Body: {response.text}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
