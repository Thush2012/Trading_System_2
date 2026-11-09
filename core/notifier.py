import requests

class TelegramNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage" if self.bot_token else None

    def send_alert(self, message: str):
        if not self.bot_token or not self.chat_id:
            print(f"[LOCAL NOTIFICATION]: {message}")
            return

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            if not self.base_url:
                return
            requests.post(self.base_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[NOTIFIER ERROR] Failed to send Telegram alert: {e}")