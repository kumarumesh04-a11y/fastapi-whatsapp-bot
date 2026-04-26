import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class WhatsAppActions:
    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN")
        self.phone_number_id = os.getenv("PHONE_NUMBER_ID")
        
        if not self.token:
            raise RuntimeError("WHATSAPP_TOKEN is missing")
        if not self.phone_number_id:
            raise RuntimeError("PHONE_NUMBER_ID is missing")
        
        self.url = f"https://graph.facebook.com/v24.0/{self.phone_number_id}/messages"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        logger.info("WhatsAppActions initialized")

    async def _send(self, to: str, payload: dict):
        payload["messaging_product"] = "whatsapp"
        payload["to"] = to
        
        # Log what we're sending
        logger.info(f"📤 Sending to {to}: {payload}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(self.url, json=payload, headers=self.headers)
            if response.status_code >= 400:
                logger.error(f"❌ API Error {response.status_code}: {response.text}")
            else:
                logger.info(f"✅ API Success {response.status_code}: {response.text[:200]}")
            return response

    async def send_text(self, to: str, text: str):
        logger.info(f"📤 TEXT to {to}: {text[:100]}")
        payload = {
            "type": "text",
            "text": {"body": text}
        }
        return await self._send(to, payload)

    async def send_interactive_buttons(self, to: str, body_text: str, buttons: list):
        """Send interactive buttons (max 3)"""
        if len(buttons) > 3:
            buttons = buttons[:3]
            logger.warning("Truncated to 3 buttons (WhatsApp limit)")
        
        logger.info(f"📤 BUTTONS to {to}: {body_text}")
        
        payload = {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": btn["id"],
                                "title": btn["title"]
                            }
                        } for btn in buttons
                    ]
                }
            }
        }
        return await self._send(to, payload)