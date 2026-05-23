from flask import Flask, request, jsonify, render_template
import sqlite3
import requests
import os
import json

app = Flask(__name__)

# Shared database path
DB_PATH = os.getenv("DB_PATH", "/data/task_bot.db")

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

# Basic storage
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

        # CONNECT DATABASE
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # CHECK USER EXISTS
        user = cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (telegram_id,)
        ).fetchone()

        if not user:
            conn.close()

            return jsonify({
                "status": "error",
                "message": "User not found in bot database"
            }), 404

        # SAVE DEVICE TOKEN + VERIFY USER
        cursor.execute(
            """
            UPDATE users
            SET device_verified = 1,
                device_token = ?
            WHERE user_id = ?
            """,
            (device_token, telegram_id)
        )

        conn.commit()
        conn.close()

        # SEND TELEGRAM MENU
        send_telegram_menu_debug(telegram_id)

        return jsonify({
            "status": "success",
            "message": "Device verified successfully"
        })

    except Exception as e:
        print(f"VERIFY ERROR: {e}")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def send_telegram_menu_debug(telegram_id):
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
                "resize_keyboard": True
            })
        }

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(url, data=payload)

        print("Telegram Response:", response.status_code)
        print("Telegram Body:", response.text)

    except Exception as e:
        print(f"Telegram send error: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
