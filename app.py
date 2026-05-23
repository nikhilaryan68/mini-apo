from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Temporary databases (resets if Railway server restarts)
used_devices = {}
used_ips = {}

@app.route('/')
def home():
    return render_template('index.html') 

@app.route('/verify', methods=['POST'])
def verify_user():
    data = request.json
    telegram_id = data.get('telegram_id')
    device_token = data.get('device_token')
    
    # Capture IP Address securely
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if user_ip and ',' in user_ip:
        user_ip = user_ip.split(',')[0].strip()

    # 1. Check if this exact user + device is ALREADY verified
    if device_token in used_devices and used_devices[device_token] == telegram_id:
        return jsonify({
            "status": "already_verified", 
            "message": "Your account is already verified on this device."
        })

    # 2. Check if the device is registered to SOMEONE ELSE
    if device_token in used_devices and used_devices[device_token] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: This device is linked to another account."
        })

    # 3. Check if the IP is registered to SOMEONE ELSE
    if user_ip in used_ips and used_ips[user_ip] != telegram_id:
        return jsonify({
            "status": "blocked", 
            "reason": "Access Denied: This network is linked to another account."
        })

    # 4. If completely new, register them
    used_devices[device_token] = telegram_id
    used_ips[user_ip] = telegram_id

    return jsonify({"status": "success", "message": "Device successfully verified."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
