import psycopg2
from flask import Flask, request, jsonify, render_template
import requests
import os
import json

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
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

        if not telegram_id:
            return jsonify({
                "status": "error",
                "message": "Telegram ID missing"
            }), 400

        # CONNECT TO POSTGRESQL
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # CREATE TABLES IF NOT EXISTS (Postgres syntax)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance FLOAT DEFAULT 0.0,
                referred_by BIGINT,
                upi_id TEXT,
                is_banned INT DEFAULT 0,
                device_verified INT DEFAULT 0,
                device_token TEXT
            )
        ''')

        # 1. CHECK IF USER EXISTS AND GET STATUS
        cursor.execute("SELECT device_verified FROM users WHERE user_id = %s", (telegram_id,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({
                "status": "error",
                "message": "User not found. Start bot first."
            }), 404

        # 2. ANTI-CHEAT: Check standard device token (Ignores if token is empty)
        if device_token and device_token not in ["", "null", "undefined"]:
            cursor.execute("SELECT user_id FROM users WHERE device_token = %s AND user_id != %s", (device_token, telegram_id))
            other_user = cursor.fetchone()

            if other_user:
                conn.close()
                return jsonify({
                    "status": "device_used",
                    "reason": "Same device detected! Multiple accounts are not allowed on one device."
                }), 200

        # 3. CHECK IF THIS USER IS ALREADY VERIFIED
        if user[0] == 1:
            conn.close()
            return jsonify({
                "status": "already_verified"
            })

        # 4. IF ALL CHECKS PASS, UPDATE VERIFICATION
        cursor.execute(
            """
            UPDATE users
            SET device_verified = 1,
                device_token = %s
            WHERE user_id = %s
            """,
            (device_token, telegram_id)
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

    except Exception as e:
        print(f"Telegram send error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
