import json, os, sys, urllib.request, urllib.error

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SKEY = os.environ.get("SUPABASE_SECRET_KEY", "")
GKEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")


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


def ask(state):
    prompt = (
        "Bạn là một AI agent trong dự án nhật ký công khai: bắt đầu với số vốn "
        f"{state['capital']}đ và phải tự tìm cách kiếm tiền một cách hợp pháp.\n"
        "Quy tắc:\n"
        "- Bạn KHÔNG có quyền ghi thu chi và KHÔNG được bịa số liệu. Tiền chỉ do chủ dự án ghi.\n"
        "- Bạn chỉ làm được việc bằng chữ: lập kế hoạch, soạn nội dung, nghiên cứu ý tưởng. "
        "Không tự đăng bài, không spam, không giả mạo.\n"
        "- Mỗi lượt chọn đúng 1 việc đang làm, làm một phần thật (viết ra kết quả cụ thể trong entry).\n"
        "- Viết trung thực, ngắn gọn, tiếng Việt, tối đa 120 từ.\n\n"
        f"Trạng thái hiện tại:\n{json.dumps(state, ensure_ascii=False)}\n\n"
        'Trả về JSON đúng dạng: {"entry": "...", "doing_id": số hoặc null, '
        '"done_ids": [số], "new_tasks": ["tối đa 2 việc mới"]}'
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": GKEY},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        res = json.load(r)
    return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])


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
    state = {"capital": meta["capital"], "ledger": ledger, "tasks": tasks, "log": recent[::-1]}

    try:
        out = ask(state)
        text = str(out.get("entry", "")).strip()[:1200] or "Lượt này tôi không có gì để ghi."
        valid = {t["id"] for t in tasks}
        doing = to_ids([out.get("doing_id")])
        done = [i for i in to_ids(out.get("done_ids")) if i in valid]
        db("PATCH", "tasks?status=eq.doing", {"status": "todo"})
        if done:
            db("PATCH", f"tasks?id=in.({','.join(map(str, done))})", {"status": "done"})
        if doing and doing[0] in valid and doing[0] not in done:
            db("PATCH", f"tasks?id=eq.{doing[0]}", {"status": "doing"})
        open_count = sum(1 for t in tasks if t["status"] != "done" and t["id"] not in done)
        news = [str(t)[:140] for t in (out.get("new_tasks") or [])[:2]]
        news = news[: max(0, 10 - open_count)]
        if news:
            db("POST", "tasks", [{"title": t} for t in news])
    except Exception as e:
        detail = ""
        if isinstance(e, urllib.error.HTTPError):
            try:
                detail = e.read().decode()[:250]
            except Exception:
                pass
        text = f"Lượt này bị lỗi, chưa làm được gì: {e} {detail}"[:600]

    db("POST", "log", {"content": text})


main()
