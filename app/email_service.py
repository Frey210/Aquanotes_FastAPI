import logging
import os
import smtplib
from html import escape
from email.message import EmailMessage
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, heading: str, body: str, action: str, url: str) -> None:
    sender = os.getenv("SMTP_EMAIL", "").strip()
    password = "".join(os.getenv("SMTP_APP_PASSWORD", "").split())
    if not sender or not password:
        raise RuntimeError("SMTP belum dikonfigurasi")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"Aquanotes <{sender}>"
    message["To"] = to_email
    message.set_content(f"{heading}\n\n{body}\n\n{action}: {url}\n\nJika bukan Anda yang meminta, abaikan email ini.")
    safe_heading, safe_body, safe_action, safe_url = map(escape, (heading, body, action, url))
    message.add_alternative(
        f"""<!doctype html><html><body style="margin:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#102033">
        <div style="max-width:560px;margin:32px auto;padding:32px;background:#fff;border:1px solid #d9e3ed;border-radius:14px">
        <p style="margin:0 0 8px;color:#147fe2;font-size:12px;font-weight:700;letter-spacing:1.4px">AQUANOTES</p>
        <h1 style="margin:0 0 16px;font-size:26px">{safe_heading}</h1><p style="line-height:1.6;color:#506176">{safe_body}</p>
        <p style="margin:28px 0"><a href="{safe_url}" style="display:inline-block;padding:13px 20px;color:#fff;background:#147fe2;border-radius:9px;text-decoration:none;font-weight:700">{safe_action}</a></p>
        <p style="margin:0;color:#718096;font-size:13px">Tautan ini hanya dapat digunakan sekali. Jika bukan Anda yang meminta, abaikan email ini.</p>
        </div></body></html>""",
        subtype="html",
    )
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)


def send_verification_email(email: str, name: str, token: str) -> None:
    base = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
    _send(
        email,
        "Verifikasi email Aquanotes",
        f"Selamat datang, {name}",
        "Verifikasi alamat email Anda untuk mengaktifkan akun Aquanotes.",
        "Verifikasi email",
        f"{base}/verify-email?token={quote(token)}",
    )


def send_password_reset_email(email: str, name: str, token: str) -> None:
    base = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
    _send(
        email,
        "Atur ulang password Aquanotes",
        f"Halo, {name}",
        "Kami menerima permintaan untuk mengganti password akun Aquanotes Anda. Tautan berlaku selama 30 menit.",
        "Buat password baru",
        f"{base}/reset-password?token={quote(token)}",
    )


def send_safely(sender, *args) -> None:
    try:
        sender(*args)
    except Exception:
        logger.exception("Email Aquanotes gagal dikirim")
