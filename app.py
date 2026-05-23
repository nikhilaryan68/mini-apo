from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os

app = Flask(__name__)

# Temporary memory to track active sessions
used_devices = {}
used_ips = {}

# Make sure you have your Bot Token and Admin IDs set in your Railway Environment Variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

@app.route('/')
def home():
    # Serves your cyber-themed index.html
    return render_template('index.html') 

@app.route('/verify', methods=['POST'])
def verify_user():
    data = request.json
    telegram_id = data.get('telegram_id')
    device_token = data.get('device_token')
    
    # 1. Capture the User's IP Address (Handles proxies like Railway/Cloudflare)
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    # 2. Check if this exact user + device is ALREADY verified
    if device_token in used_devices and used_devices[device_token] == telegram_id:
        return jsonify({
            "status": "already_verified", 
            "message": "Your account is already verified on this device."
        })

    # 3. Check if the device is registered to SOMEONE ELSE (AUTO-BAN TRIGGER)
    if device_token in used_devices and used_devices[device_token] != telegram_id:
        try:
            # Connect to bot database and immediately ban the user
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

    # 4. Check if the IP is registered to SOMEONE ELSE
    if user_ip in used_ips and used_ips[user_ip] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: Multiple accounts detected on this network."
        })

    # 5. If completely new and clean, register them
    used_devices[device_token] = telegram_id
    used_ips[user_ip] = telegram_id

    # Update SQLite database so the Telegram bot knows they are verified
    try:
        conn = sqlite3.connect('task_bot.db')
        
        # Mark user as verified
        conn.execute("UPDATE users SET device_verified = 1 WHERE user_id = ?", (telegram_id,))
        conn.commit()
        
        # Fetch the current main menu text from the database
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key='menu_text'")
        row = cursor.fetchone()
        menu_text = row[0] if row else "Welcome to the Task Bot! Complete tasks to earn INR."
        conn.close()

        # Automatically send the Main Menu Reply Keyboard using Telegram's API
        if BOT_TOKEN:
            admin_ids = [int(x.strip()) for x in ADMIN_IDS_RAW.split(',') if x.strip().isdigit()]
            
            # Construct the bottom Reply Keyboard
            reply_keyboard = [
                [{"text": "📝 Get Task"}],
                [{"text": "💰 Wallet"}, {"text": "💸 Withdraw"}],
                [{"text": "👥 Refer & Earn"}, {"text": "📞 Support"}]
            ]
            
            # Add admin panel button if the user is an admin
            try:
                if int(telegram_id) in admin_ids:
                    reply_keyboard.append([{"text": "⚙️ Admin Panel"}])
            except ValueError:
                pass

            reply_markup = {
                "keyboard": reply_keyboard,
                "resize_keyboard": True
            }
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": telegram_id,
                "text": f"✅ Device Successfully Verified!\n\n{menu_text}",
                "reply_markup": reply_markup
            })

    except Exception as e:
        print(f"Database/API error during verification completion: {e}")

    return jsonify({"status": "success", "message": "Device successfully verified."})

if __name__ == '__main__':
    # Runs the app
    app.run(host='0.0.0.0', port=5000)
