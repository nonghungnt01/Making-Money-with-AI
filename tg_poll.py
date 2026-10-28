import json, os, sys, datetime, urllib.request

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SKEY = os.environ.get("SUPABASE_SECRET_KEY", "")
TG = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def db(method, path, body=None):
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"apikey": SKEY, "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def tg(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    if not (URL and SKEY and TG and CHAT):
        sys.exit("Thiếu SUPABASE_URL, SUPABASE_SECRET_KEY, TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID")
    offset = db("GET", "meta?select=tg_offset&id=eq.1")[0]["tg_offset"]
    res = tg("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["callback_query"]})
    last = None
    for u in res.get("result", []):
        last = u["update_id"]
        cq = u.get("callback_query")
        # Chỉ nhận lệnh từ đúng tài khoản của chủ dự án
        if not cq or str(cq["from"]["id"]) != str(CHAT):
            continue
        try:
            act, did = cq["data"].split(":")
            did = int(did)
        except Exception:
            continue
        status = "approved" if act == "a" else "rejected"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        db("PATCH", f"drafts?id=eq.{did}&status=eq.pending", {"status": status, "decided_at": now})
        label = "✅ ĐÃ DUYỆT" if status == "approved" else "❌ ĐÃ TỪ CHỐI"
        try:
            tg("answerCallbackQuery", {"callback_query_id": cq["id"], "text": label})
        except Exception:
            pass
        msg = cq.get("message")
        if msg:
            try:
                tg("editMessageText", {
                    "chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                    "text": (msg.get("text", "") + f"\n\n{label}")[:4096],
                    "reply_markup": {"inline_keyboard": []},
                })
            except Exception:
                pass
    if last is not None:
        db("PATCH", "meta?id=eq.1", {"tg_offset": last + 1})


main()
