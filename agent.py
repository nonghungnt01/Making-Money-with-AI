import json, os, sys, time, datetime, urllib.request, urllib.error

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SKEY = os.environ.get("SUPABASE_SECRET_KEY", "")
GKEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
TG = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
NKEY = os.environ.get("NVIDIA_API_KEY", "")
NMODEL = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")




def db(method, path, body=None, ret=False):
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"apikey": SKEY, "Content-Type": "application/json", "Prefer": "return=representation" if ret else "return=minimal"},
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


def ask(state):
    prompt = (
        "Bạn là một AI agent trong dự án nhật ký công khai: bắt đầu với số vốn "
        f"{state['capital']}đ và phải tự tìm cách kiếm tiền một cách hợp pháp.\n"
        "Quy tắc:\n"
        "- Bạn KHÔNG có quyền ghi thu chi và KHÔNG được bịa số liệu. Tiền chỉ do chủ dự án ghi.\n"
        "- Bạn chỉ làm được việc bằng chữ: lập kế hoạch, soạn nội dung, nghiên cứu ý tưởng. "
        "Không tự đăng bài, không spam, không giả mạo.\n"
        "- Mỗi lượt chọn đúng 1 việc đang làm, làm một phần thật (viết ra kết quả cụ thể trong entry).\n"
        "- Nội dung đầy đủ (bài đăng, trang giới thiệu, tin nhắn) đưa vào \"draft\" để chủ dự án duyệt trước khi dùng; "
        "\"entry\" chỉ tóm tắt.\n"
        "- Xem mục drafts trong trạng thái: bản bị rejected nghĩa là chủ dự án không thích, đừng lặp lại.\n"
        "- Viết trung thực, ngắn gọn, tiếng Việt, tối đa 120 từ.\n\n"
        f"Trạng thái hiện tại:\n{json.dumps(state, ensure_ascii=False)}\n\n"
        'Trả về JSON đúng dạng: {"entry": "...", "doing_id": số hoặc null, '
        '"done_ids": [số], "new_tasks": ["tối đa 2 việc mới"], '
        '"draft": null hoặc {"kind": "bai_dang|trang_gioi_thieu|tin_nhan", "title": "...", "body": "..."}}'
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
        try:
        return ask_gemini(prompt)
    except Exception as e:
        if not NKEY:
            raise
        print("Gemini lỗi, chuyển sang NVIDIA:", e)
        return ask_nvidia(prompt)


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.startswith("json") else text
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1])


def ask_gemini(prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    last = None
    for i, m in enumerate([MODEL, "gemini-flash-latest"]):
        if i:
            time.sleep(8)
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": GKEY},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)
            return parse_json(res["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as e:
            last = e
    raise last


def ask_nvidia(prompt):
    body = {
        "model": NMODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": False,
    }
    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {NKEY}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
    return parse_json(res["choices"][0]["message"]["content"])

def to_ids(values):
    out = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    return out


def main():
    if not (URL and SKEY and GKEY):
        sys.exit("Thiếu SUPABASE_URL, SUPABASE_SECRET_KEY hoặc GEMINI_API_KEY")

    meta = db("GET", "meta?select=*&id=eq.1")[0]
    tasks = db("GET", "tasks?select=*&order=id")
    ledger = db("GET", "ledger?select=*&order=id")
    recent = db("GET", "log?select=created_at,content&order=id.desc&limit=5")
    drafts = db("GET", "drafts?select=kind,title,status&order=id.desc&limit=5")
    state = {"capital": meta["capital"], "ledger": ledger, "tasks": tasks, "log": recent[::-1], "drafts": drafts}

    task_id = None
    try:
        out = ask(state)
        text = str(out.get("entry", "")).strip()[:1200] or "Lượt này tôi không có gì để ghi."
        valid = {t["id"]: t for t in tasks}
        doing = to_ids([out.get("doing_id")])
        done = [i for i in to_ids(out.get("done_ids")) if i in valid]
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        db("PATCH", "tasks?status=eq.doing", {"status": "todo"})
        if done:
            db("PATCH", f"tasks?id=in.({','.join(map(str, done))})", {"status": "done", "done_at": stamp})
            task_id = done[0]
        if doing and doing[0] in valid and doing[0] not in done:
            task_id = doing[0]
            body = {"status": "doing"}
            if not valid[task_id].get("started_at"):
                body["started_at"] = stamp
            db("PATCH", f"tasks?id=eq.{task_id}", body)
        open_count = sum(1 for t in tasks if t["status"] != "done" and t["id"] not in done)
        news = [str(t)[:140] for t in (out.get("new_tasks") or [])[:2]]
        news = news[: max(0, 10 - open_count)]
        if news:
            db("POST", "tasks", [{"title": t} for t in news])
        d = out.get("draft")
        if isinstance(d, dict) and str(d.get("body", "")).strip():
            row = db("POST", "drafts", {
                "task_id": task_id,
                "kind": str(d.get("kind", "bai_dang"))[:40],
                "title": str(d.get("title", ""))[:140],
                "body": str(d["body"])[:6000],
            }, ret=True)[0]
            if TG and CHAT:
                try:
                    msg = f"📝 Bản nháp #{row['id']} · {row['kind']}\n{row['title'] or ''}\n\n{row['body']}"[:3900]
                    tg("sendMessage", {"chat_id": int(CHAT), "text": msg, "reply_markup": {"inline_keyboard": [[
                        {"text": "✅ Duyệt", "callback_data": f"a:{row['id']}"},
                        {"text": "❌ Từ chối", "callback_data": f"r:{row['id']}"}]]}})
                except Exception as e:
                    text += f" (Chưa gửi được Telegram: {e})"
    except Exception as e:
        detail = ""
        if isinstance(e, urllib.error.HTTPError):
            try:
                detail = e.read().decode()[:250]
            except Exception:
                pass
        text = f"Lượt này bị lỗi, chưa làm được gì: {e} {detail}"[:600]

    db("POST", "log", {"content": text, "task_id": task_id})


main()
