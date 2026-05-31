import logging
import os
import httpx

logger = logging.getLogger(__name__)


class SlackTool:
    def __init__(self):
        self.token = os.getenv("SLACK_BOT_TOKEN")
        self.base_url = "https://slack.com/api"
        self.headers = (
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            if self.token
            else {}
        )

    async def post_message(self, channel: str, text: str):
        if not self.token:
            logger.warning("SLACK_BOT_TOKEN not found. Using mock implementation.")
            return {"success": True, "status": "mocked"}

        logger.info(f"Posting real message to Slack channel {channel}")
        url = f"{self.base_url}/chat.postMessage"
        payload = {"channel": channel, "text": text}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers)
            data = response.json()
            if data.get("ok"):
                return {"success": True, "status": "sent", "ts": data.get("ts")}
            else:
                logger.error(f"Slack API Error: {data.get('error')}")
                return {"success": False, "error": data.get("error")}
