from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Temporary databases (will reset if the server restarts)
used_devices = {}
used_ips = {}

# 1. This route serves your Frontend to Telegram
@app.route('/')
def home():
    # This looks inside the "templates" folder for index.html
    return render_template('index.html') 

# 2. This route handles the background verification
@app.route('/verify', methods=['POST'])
def verify_user():
    data = request.json
    telegram_id = data.get('telegram_id')
    device_token = data.get('device_token')
    
    # Capture the User's IP Address
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    # Device Token Check
    if device_token in used_devices and used_devices[device_token] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: This device is already registered to another account."
        })

    # IP Address Check
    if user_ip in used_ips and used_ips[user_ip] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: This IP network is already registered to another account."
        })

    # Register the user
    used_devices[device_token] = telegram_id
    used_ips[user_ip] = telegram_id

    return jsonify({"status": "success", "message": "Verified"})

if __name__ == '__main__':
    app.run(port=5000)
