#!/usr/bin/env python3
"""
MPPE Diário Oficial — send report PDF via Gmail.

Usage:
    python3 send_email.py report.pdf [--to you@gmail.com] [--subject "..."] [--body body.txt]

Requires the Google OAuth token at /Users/chlima/.hermes/google_token.json (the
gmail.send scope is sufficient). macOS Python 3.9 needs the venv shim — the
script adds it automatically.

Always post-verifies that the message landed in SENT and that the attachment
is a valid PDF (magic bytes %PDF-). Verified 2026-06-20.
"""
import sys, base64, json, argparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

# macOS Python 3.9 venv shim — googleapiclient lives here, system python3 doesn't have it
_VENV_SITE = "/Users/chlima/.hermes/home/Library/Python/3.9/lib/python/site-packages"
if Path(_VENV_SITE).exists():
    sys.path.insert(0, _VENV_SITE)

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = "/Users/chlima/.hermes/google_token.json"
DEFAULT_TO = "charles.santos.lima@gmail.com"
DEFAULT_FROM = "charles.santos.lima@gmail.com"


def _build_service():
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _build_message(to, subject, body_text, pdf_path: Path):
    msg = MIMEMultipart()
    msg["to"] = to
    msg["from"] = DEFAULT_FROM
    msg["subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    with pdf_path.open("rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
        msg.attach(part)
    return msg


def _verify_sent(service, msg_id: str, expected_filename: str) -> dict:
    """Re-fetch the message and confirm SENT label + valid PDF attachment."""
    got = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    label_ids = got.get("labelIds", [])
    in_sent = "SENT" in label_ids

    def find_pdf_part(parts):
        for p in parts:
            if p.get("filename") == expected_filename:
                return p
            inner = p.get("parts", [])
            if inner:
                r = find_pdf_part(inner)
                if r:
                    return r
        return None

    pdf_part = find_pdf_part(got.get("payload", {}).get("parts", []))
    pdf_ok = False
    pdf_size = 0
    if pdf_part:
        att_id = pdf_part["body"].get("attachmentId")
        if att_id:
            att = service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=att_id
            ).execute()
            raw = base64.urlsafe_b64decode(att["data"])
            pdf_size = len(raw)
            pdf_ok = raw[:5] == b"%PDF-"
    return {
        "label_ids": label_ids,
        "in_sent": in_sent,
        "attachment": {
            "filename": expected_filename,
            "size": pdf_size,
            "is_valid_pdf": pdf_ok,
        } if pdf_part else None,
    }


def main():
    p = argparse.ArgumentParser(description="Send MPPE report PDF via Gmail.")
    p.add_argument("pdf", help="Path to the report PDF")
    p.add_argument("--to", default=DEFAULT_TO)
    p.add_argument("--from", dest="from_addr", default=DEFAULT_FROM)
    p.add_argument("--subject", default="Diário Oficial MPPE — relatório de menções")
    p.add_argument("--body", help="Path to a text file with the body (or use default)")
    args = p.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF não encontrado: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if args.body:
        body_text = Path(args.body).read_text(encoding="utf-8")
    else:
        body_text = (
            "Segue em anexo o relatório consolidado de menções no Diário Oficial do MPPE.\n\n"
            f"PDF anexo: {pdf_path.name}\n\nGerado por Hermes Agent.\n"
        )

    service = _build_service()
    msg = _build_message(args.to, args.subject, body_text, pdf_path)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    # Post-verify (the API can succeed and the message can be silently dropped)
    verify = _verify_sent(service, sent["id"], pdf_path.name)

    print(json.dumps({
        "status": "sent",
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "to": args.to,
        "subject": args.subject,
        "verification": verify,
    }, indent=2, ensure_ascii=False))

    if not verify["in_sent"] or not verify["attachment"] or not verify["attachment"]["is_valid_pdf"]:
        print("⚠️ verificação falhou — verifique manualmente no Gmail", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()