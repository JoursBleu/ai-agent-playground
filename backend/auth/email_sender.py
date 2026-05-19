"""SMTP sender (Aliyun DirectMail / smtpdm). Env-configured.

Env (set in /etc/ai-agent-playground.env via systemd EnvironmentFile):
  SMTP_HOST       (default smtpdm.aliyun.com)
  SMTP_PORT       (default 465)
  SMTP_USER       (e.g. noreply@mail.agent-playground.space)
  SMTP_PASS
  SMTP_FROM       (default = SMTP_USER)
  SMTP_FROM_NAME  (default = "AgentPlayground")
  SMTP_USE_SSL    (default "1")
"""
from __future__ import annotations
import os, smtplib, ssl, logging
from email.message import EmailMessage
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def _cfg():
    user = os.environ.get("SMTP_USER", "").strip()
    pwd  = os.environ.get("SMTP_PASS", "").strip()
    if not user or not pwd:
        return None
    return {
        "host": os.environ.get("SMTP_HOST", "smtpdm.aliyun.com").strip(),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": user, "pass": pwd,
        "from_addr": (os.environ.get("SMTP_FROM") or user).strip(),
        "from_name": (os.environ.get("SMTP_FROM_NAME") or "AgentPlayground").strip(),
        "use_ssl": (os.environ.get("SMTP_USE_SSL", "1").strip().lower() not in ("0", "false", "no", "")),
    }


def smtp_configured() -> bool:
    return _cfg() is not None


def send_mail(to_addr: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
    cfg = _cfg()
    if cfg is None:
        raise RuntimeError("SMTP not configured (set SMTP_USER / SMTP_PASS)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_addr"]}>'
    msg["To"] = to_addr
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    if cfg["use_ssl"]:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=20) as srv:
            srv.login(cfg["user"], cfg["pass"])
            srv.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as srv:
            srv.ehlo()
            try:
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
            except Exception:
                pass
            srv.login(cfg["user"], cfg["pass"])
            srv.send_message(msg)


def render_code_mail(purpose: str, code: str) -> Tuple[str, str, str]:
    """Return (subject, text_body, html_body)."""
    purpose_label = {"register": "注册账号", "reset": "重置密码"}.get(purpose, purpose)
    subject = f"【AgentPlayground】您的{purpose_label}验证码"
    text = (
        f"您好，\n\n"
        f"您正在 AgentPlayground 进行【{purpose_label}】操作，验证码：\n\n"
        f"    {code}\n\n"
        f"该验证码 10 分钟内有效，请勿泄露给他人。\n"
        f"如非本人操作，请忽略此邮件。\n\n"
        f"-- AgentPlayground (https://agent-playground.space)\n"
    )
    html = (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2937;line-height:1.6">'
        '<p>您好，</p>'
        f'<p>您正在 AgentPlayground 进行 <b>{purpose_label}</b> 操作，验证码：</p>'
        f'<p style="font-size:28px;font-weight:700;letter-spacing:6px;color:#6d28d9;background:#ede9fe;padding:14px 22px;border-radius:8px;display:inline-block;font-family:Menlo,Consolas,monospace">{code}</p>'
        '<p style="color:#6b7280;font-size:13px">该验证码 10 分钟内有效，请勿泄露给他人。如非本人操作，请忽略此邮件。</p>'
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:18px 0">'
        '<p style="color:#9ca3af;font-size:12px">AgentPlayground · <a href="https://agent-playground.space" style="color:#6d28d9">agent-playground.space</a></p>'
        '</body></html>'
    )
    return subject, text, html


def render_account_list_mail(email: str, usernames: list) -> Tuple[str, str, str]:
    """Return (subject, text, html) for the 'find my usernames' mail."""
    subject = "【AgentPlayground】您注册的账号清单"
    items_text = "\n".join(f"  - {u}" for u in usernames)
    items_html = "".join(f'<li style="margin:4px 0;font-family:Menlo,Consolas,monospace">{u}</li>' for u in usernames)
    text = (
        f"您好，\n\n"
        f"以下是当前邮箱 {email} 在 AgentPlayground 关联的账号：\n\n"
        f"{items_text}\n\n"
        f"如需登录，请使用以上任一用户名 + 您设置的密码。\n"
        f"如非本人操作，请忽略此邮件。\n\n"
        f"-- AgentPlayground (https://agent-playground.space)\n"
    )
    html = (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2937;line-height:1.6">'
        '<p>您好，</p>'
        f'<p>以下是当前邮箱 <b>{email}</b> 在 AgentPlayground 关联的账号：</p>'
        f'<ul style="background:#f3f4f6;padding:14px 28px;border-radius:8px;display:inline-block">{items_html}</ul>'
        '<p>如需登录，请使用以上任一用户名 + 您设置的密码。如非本人操作，请忽略此邮件。</p>'
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:18px 0">'
        '<p style="color:#9ca3af;font-size:12px">AgentPlayground · <a href="https://agent-playground.space" style="color:#6d28d9">agent-playground.space</a></p>'
        '</body></html>'
    )
    return subject, text, html
