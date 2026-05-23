from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os

app = Flask(__name__)

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
    
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    if device_token in used_devices and used_devices[device_token] == telegram_id:
        return jsonify({
            "status": "already_verified", 
            "message": "Your account is already verified on this device."
        })

    if device_token in used_devices and used_devices[device_token] != telegram_id:
        try:
            conn = sqlite3.connect('task_bot.db')
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

    try:
        conn = sqlite3.connect('task_bot.db')
        conn.execute("UPDATE users SET device_verified = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key='menu_text'")
        row = cursor.fetchone()
        menu_text = row[0] if row else "Welcome to the Task Bot! Complete tasks to earn INR."
        conn.close()

        # Command Telegram bot to send the menu automatically
        if BOT_TOKEN:
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
            
            # Send message silently in the background
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)

    except Exception as e:
        print(f"Database/API error during verification completion: {e}")

    return jsonify({"status": "success", "message": "Device successfully verified."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
