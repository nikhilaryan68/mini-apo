from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os
import json

app = Flask(__name__)

# DATABASE PATH
DB_PATH = "task_bot.db"

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

# Temporary memory
used_devices = {}
used_ips = {}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/verify', methods=['POST'])
def verify_user():
    try:
        data = request.json

        telegram_id = data.get('telegram_id')
        device_token = data.get('device_token')
        hw_id = data.get('hw_id') # Fetch the new hardware fingerprint

        if not telegram_id:
            return jsonify({
                "status": "error",
                "message": "Telegram ID missing"
            }), 400

        # CONNECT DATABASE
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # CREATE TABLES IF NOT EXISTS
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                referred_by INTEGER,
                upi_id TEXT,
                is_banned INTEGER DEFAULT 0,
                device_verified INTEGER DEFAULT 0,
                device_token TEXT
            )
        ''')
        
        # New table to permanently track device hardware
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_fingerprints (
                hw_id TEXT,
                user_id INTEGER
            )
        ''')

        # 1. CHECK IF USER EXISTS AND GET STATUS
        user = cursor.execute(
            "SELECT device_verified FROM users WHERE user_id = ?",
            (telegram_id,)
        ).fetchone()

        if not user:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "User not found. Start bot first."
            }), 404

        # 2. ANTI-CHEAT LEVEL 1: Check standard device token
        other_user = cursor.execute(
            "SELECT user_id FROM users WHERE device_token = ? AND user_id != ?",
            (device_token, telegram_id)
        ).fetchone()

        if other_user:
            conn.close()
            return jsonify({
                "status": "device_used",
                "reason": "Same device detected! Multiple accounts are not allowed on one device."
            }), 200

        # 3. ANTI-CHEAT LEVEL 2: Check hardware fingerprint (Catches Cache Clearers)
        if hw_id:
            other_hw = cursor.execute(
                "SELECT user_id FROM device_fingerprints WHERE hw_id = ? AND user_id != ?",
                (hw_id, telegram_id)
            ).fetchone()

            if other_hw:
                conn.close()
                return jsonify({
                    "status": "device_used",
                    "reason": "Same device detected! Clearing cache will not bypass this system."
                }), 200

        # 4. CHECK IF THIS USER IS ALREADY VERIFIED
        if user[0] == 1:
            conn.close()
            return jsonify({
                "status": "already_verified"
            })

        # 5. IF ALL CHECKS PASS, UPDATE VERIFICATION
        cursor.execute(
            """
            UPDATE users
            SET device_verified = 1,
                device_token = ?
            WHERE user_id = ?
            """,
            (device_token, telegram_id)
        )
        
        # 6. SAVE PERMANENT HARDWARE FINGERPRINT
        if hw_id:
            cursor.execute(
                "INSERT INTO device_fingerprints (hw_id, user_id) VALUES (?, ?)", 
                (hw_id, telegram_id)
            )

        conn.commit()
        conn.close()

        # SEND MENU TO USER
        send_telegram_menu(telegram_id)

        return jsonify({
            "status": "success",
            "message": "Verification successful"
        })

    except Exception as e:
        print(f"VERIFY ERROR: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def send_telegram_menu(telegram_id):
    try:
        if not BOT_TOKEN:
            print("BOT_TOKEN missing")
            return

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
                "resize_keyboard": True,
                "is_persistent": True
            })
        }

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(url, data=payload)

        print("Telegram Status:", response.status_code)
        print("Telegram Response:", response.text)

    except Exception as e:
        print(f"Telegram send error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
