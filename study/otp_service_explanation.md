# 📧 Deep Dive: `src/otp_service.py` (Security)

This file manages the "Identity Verification" part of the app. It prevents random people from booking with your phone number.

## 1. Security Basics
```python
11: def hash_otp(otp: str):
12:     return hashlib.sha256(otp.encode()).hexdigest()
```
-   **Hashing**: We NEVER store the actual OTP in the FSM state. We store the "Hash".
-   **Why?**: Even if someone dumps the memory opacity, they can't reverse-engineer the 6-digit code easily (though for 6 digits it's trivial, it's still best practice).

## 2. Sending Email (`send_otp_email`)
```python
14: def send_otp_email(email: str, otp: str):
15:     smtp_host = os.getenv("SMTP_HOST")
```
-   It loads SMTP credentials from `.env.local`.

**Mock Mode (Dev Friendly)**
```python
21:     if not all([smtp_host, ...]):
22:         print(f"\n[MOCK EMAIL] To: {email} | OTP: {otp}...")
23:         return
```
-   **Exam Tip**: If you run this project without a real email server, this `print` statement is how you get the code to test it!

**Real Sending**
```python
26:         msg = EmailMessage()
39:         with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
40:             server.starttls()
```
-   Standard Python email logic. `starttls()` ensures the connection is encrypted.

## 3. Configuration & Constants
```python
52: OTP_EXPIRY_MINUTES = 5
53: OTP_RESEND_COOLDOWN_SECONDS = 30
54: OTP_MAX_RESENDS = 3
```
-   **Rate Limiting**: These rules prevent spam.
    -   Code dies in 5 mins.
    -   You click "Resend" too fast? It waits 30s.
    -   You clicked it 100 times? It stops after 3.

## 4. Confirmation Email
```python
56: def send_booking_confirmation_email(..., service, date, time):
```
-   This sends a nicely formatted HTML email after booking success.
    ```python
    74:         html_content = f"""
    75:         <html>
    ```
-   It uses a multi-part email (Plain text + HTML) so it looks professional on phones.

---

## Summary
-   **`otp_service.py`** is the **Gatekeeper**.
-   It handles **Secrets** (Hashing).
-   It handles **Communication** (Email).
-   It includes **Dev-Tools** (Mock Mode) to make testing easy.
