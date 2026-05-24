import subprocess

print("Starting Flask App...")
subprocess.Popen(["python", "app.py"])

print("Starting Telegram Bot...")
subprocess.run(["python", "bot.py"])
