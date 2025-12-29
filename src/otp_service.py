import smtplib
import random
import hashlib
from datetime import datetime, timedelta
from email.message import EmailMessage
import os

def generate_otp():
    return str(random.randint(100000, 999999))

def hash_otp(otp: str):
    return hashlib.sha256(otp.encode()).hexdigest()

def send_otp_email(email: str, otp: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    # Mock mode for local dev if credentials are missing
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        print(f"\n[MOCK EMAIL] To: {email} | OTP: {otp}\nTo enable real emails, set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env.local\n")
        return

    try:
        msg = EmailMessage()
        msg["Subject"] = "Your Salon Verification Code"
        msg["From"] = smtp_user
        msg["To"] = email
        msg.set_content(
            f"""
Your verification code is: {otp}

This code is valid for 5 minutes.
If you didn’t request this, please ignore.
"""
        )

        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            print(f"OTP email sent to {email}")

    except Exception as e:
        print(f"Failed to send email: {e}")
        # Allow flow to continue, or re-raise if we want the agent to know failure
        # For now, let's treat it as a critical failure if we tried and failed.
        raise e


OTP_EXPIRY_MINUTES = 5
OTP_RESEND_COOLDOWN_SECONDS = 30     # user must wait 30s
OTP_MAX_RESENDS = 3                  # max 3 resends
