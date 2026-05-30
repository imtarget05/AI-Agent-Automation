"""
Email Tool - handles SMTP transmission of incident reports and approval requests.
Provides developer-friendly local file writing for easy draft inspection without SMTP servers.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Dict, Any, Optional

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class EmailTool:
    """Tool class for drafting and sending system emails"""

    def __init__(self):
        self.settings = get_settings()
        self.drafts_path = Path(self.settings.email_drafts_path)
        self.drafts_path.mkdir(parents=True, exist_ok=True)

    def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
        is_html: bool = False,
        smtp_server: Optional[str] = None,
        smtp_port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via SMTP. Falls back to writing a local file draft.
        """
        # Read default configs from environment
        server = smtp_server or getattr(self.settings, "smtp_server", "")
        port = smtp_port or getattr(self.settings, "smtp_port", 587)
        user = username or getattr(self.settings, "smtp_user", "")
        pwd = password or getattr(self.settings, "smtp_password", "")
        from_addr = user or "aiops-alert@internal.platform"

        # Check if SMTP is configured
        if server and user and pwd:
            try:
                msg = MIMEMultipart()
                msg['From'] = from_addr
                msg['To'] = to_address
                msg['Subject'] = subject

                part = MIMEText(body, 'html' if is_html else 'plain', 'utf-8')
                msg.attach(part)

                with smtplib.SMTP(server, port) as smtp:
                    smtp.starttls()
                    smtp.login(user, pwd)
                    smtp.send_message(msg)
                
                logger.info(f"Email successfully sent to {to_address} via SMTP.")
                return {
                    "success": True,
                    "method": "smtp",
                    "recipient": to_address,
                    "subject": subject
                }
            except Exception as e:
                logger.error(f"Failed to send email via SMTP: {e}. Falling back to local draft writer.")

        # Local fallback - write the email as a draft file
        draft_file = self.drafts_path / "last_email_draft.txt"
        try:
            draft_content = (
                f"==================================================\n"
                f"📧 AI-GENERATED EMAIL DRAFT\n"
                f"==================================================\n"
                f"To: {to_address}\n"
                f"From: {from_addr} (AI Agent)\n"
                f"Subject: {subject}\n"
                f"Format: {'HTML' if is_html else 'Plain Text'}\n"
                f"--------------------------------------------------\n"
                f"{body}\n"
                f"==================================================\n"
            )
            draft_file.write_text(draft_content, encoding="utf-8")
            logger.info(f"Email draft written to local workspace: {draft_file.absolute()}")
            
            return {
                "success": True,
                "method": "local_file_draft",
                "draft_path": str(draft_file.absolute()),
                "recipient": to_address,
                "subject": subject
            }
        except Exception as e:
            logger.error(f"Failed to write local email draft: {e}")
            return {
                "success": False,
                "error": str(e)
            }
