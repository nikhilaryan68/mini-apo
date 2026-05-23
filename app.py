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
    
    # Logic to verify or ban
    # ... [Keep your existing logic here, it is correct] ...

    # Update Database
    try:
        conn = sqlite3.connect('task_bot.db')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned INTEGER DEFAULT 0, device_verified INTEGER DEFAULT 0)''')
        conn.execute("UPDATE users SET device_verified = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")

    # TRIGGER AUTOMATIC MESSAGE
    send_telegram_menu_debug(telegram_id)

    return jsonify({"status": "success", "message": "Device verified."})

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
