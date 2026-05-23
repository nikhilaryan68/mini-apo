from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os

app = Flask(__name__)

used_devices = {}
used_ips = {}

BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_TOKEN = '8394044106:AAErwWRDt4hB_kwBZVXB1n1M7Q-YyjKx2c'

ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

@app.route('/')
def home():
    return render_template('index.html') 

@app.route('/verify', methods=['POST'])
def verify_user():
    data = request.json
    telegram_id = data.get('telegram_id')
    device_token = data.get('device_token')
    
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    if device_token in used_devices and used_devices[device_token] == telegram_id:
        # Fire the success message even if already verified
        send_telegram_menu(telegram_id)
        return jsonify({
            "status": "already_verified", 
            "message": "Your account is already verified on this device."
        })

    if device_token in used_devices and used_devices[device_token] != telegram_id:
        try:
            conn = sqlite3.connect('task_bot.db')
            # Create table if it doesn't exist yet to prevent crashes
            conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned INTEGER DEFAULT 0, device_verified INTEGER DEFAULT 0)''')
            conn.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (telegram_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database error during ban: {e}")

        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: This device is linked to another account."
        })

    if user_ip in used_ips and used_ips[user_ip] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: Multiple accounts detected on this network."
        })

    used_devices[device_token] = telegram_id
    used_ips[user_ip] = telegram_id

    # Update SQLite database safely
    try:
        conn = sqlite3.connect('task_bot.db')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned INTEGER DEFAULT 0, device_verified INTEGER DEFAULT 0)''')
        conn.execute("UPDATE users SET device_verified = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error during verification update: {e}")

    # Command Telegram bot to send the menu automatically
    send_telegram_menu(telegram_id)

    return jsonify({"status": "success", "message": "Device successfully verified."})

def send_telegram_menu(telegram_id):
    """Helper function to guarantee the Telegram menu is sent"""
    if not BOT_TOKEN:
        print("CRITICAL ERROR: BOT_TOKEN is missing in Railway Variables!")
        return

    # Try to get custom text, fallback to default if DB is locked
    menu_text = "Welcome to the Task Bot! Complete tasks to earn INR."
    try:
        conn = sqlite3.connect('task_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key='menu_text'")
        row = cursor.fetchone()
        if row:
            menu_text = row[0]
        conn.close()
    except Exception:
        pass # Use default text if config table doesn't exist yet

    admin_ids = [int(x.strip()) for x in ADMIN_IDS_RAW.split(',') if x.strip().isdigit()]
    
    reply_keyboard = [
        [{"text": "📝 Get Task"}],
        [{"text": "💰 Wallet"}, {"text": "💸 Withdraw"}],
        [{"text": "👥 Refer & Earn"}, {"text": "📞 Support"}]
    ]
    
    try:
        if int(telegram_id) in admin_ids:
            reply_keyboard.append([{"text": "⚙️ Admin Panel"}])
    except ValueError:
        pass

    payload = {
        "chat_id": telegram_id,
        "text": f"✅ Device Successfully Verified!\n\n{menu_text}",
        "reply_markup": {
            "keyboard": reply_keyboard,
            "resize_keyboard": True
        }
    }
    
    # Send message via Telegram API
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
