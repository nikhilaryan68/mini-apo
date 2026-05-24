from flask import Flask, request, jsonify, render_template
import psycopg2
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

DATABASE_URL = os.getenv('DATABASE_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS_RAW = os.getenv('ADMIN_IDS', '6197579049')

@app.route('/verify', methods=['POST'])
def verify_user():
    try:
        data = request.json
        telegram_id = data.get('telegram_id')
        device_token = data.get('device_token')
        hw_id = data.get('hw_id')

        if not telegram_id:
            return jsonify({"status": "error", "message": "Telegram ID missing"}), 400

        # CONNECT TO POSTGRES
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # 1. CHECK IF USER EXISTS
        cursor.execute("SELECT device_verified FROM users WHERE user_id = %s", (telegram_id,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            return jsonify({"status": "error", "message": "User not found. Start bot first."}), 404

        # 2. ANTI-CHEAT: Check device token
        cursor.execute("SELECT user_id FROM users WHERE device_token = %s AND user_id != %s", (device_token, telegram_id))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": "device_used", "reason": "Same device detected!"}), 200

        # 3. ANTI-CHEAT: Check hardware fingerprint
        if hw_id:
            cursor.execute("SELECT user_id FROM device_fingerprints WHERE hw_id = %s AND user_id != %s", (hw_id, telegram_id))
            if cursor.fetchone():
                conn.close()
                return jsonify({"status": "device_used", "reason": "Same device detected!"}), 200

        # 4. Check verification status
        if user[0] == 1:
            conn.close()
            return jsonify({"status": "already_verified"})

        # 5. Update user
        cursor.execute("UPDATE users SET device_verified = 1, device_token = %s WHERE user_id = %s", (device_token, telegram_id))
        
        if hw_id:
            cursor.execute("INSERT INTO device_fingerprints (hw_id, user_id) VALUES (%s, %s)", (hw_id, telegram_id))

        conn.commit()
        conn.close()

        send_telegram_menu(telegram_id)
        return jsonify({"status": "success", "message": "Verification successful"})

    except Exception as e:
        print(f"VERIFY ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
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
