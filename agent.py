import json, os, sys, urllib.request, datetime

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
KEY = os.environ.get("GEMINI_API_KEY", "")
PATH = "data.json"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")


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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        res = json.load(r)
    return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])


def main():
    if not KEY:
        sys.exit("Thiếu GEMINI_API_KEY")
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Agent chỉ thấy tình hình, không được sửa ledger/capital.
    view = {k: data[k] for k in ("capital", "ledger", "tasks")}
    view["log"] = data["log"][-5:]

    try:
        out = ask(view)
        text = str(out.get("entry", "")).strip()[:1200] or "Lượt này tôi không có gì để ghi."
        ids = {t["id"] for t in data["tasks"]}
        for t in data["tasks"]:
            if t["status"] == "doing":
                t["status"] = "todo"
            if t["id"] == out.get("doing_id") and t["status"] != "done":
                t["status"] = "doing"
            if t["id"] in (out.get("done_ids") or []):
                t["status"] = "done"
        open_count = sum(1 for t in data["tasks"] if t["status"] != "done")
        nid = max(ids, default=0)
        for title in (out.get("new_tasks") or [])[:2]:
            if open_count >= 10:
                break
            nid += 1
            open_count += 1
            data["tasks"].append({"id": nid, "title": str(title)[:140], "status": "todo"})
    except Exception as e:
        text = f"Lượt này bị lỗi, chưa làm được gì: {str(e)[:150]}"

    data["log"].append({"time": now(), "text": text})
    data["log"] = data["log"][-100:]
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


main()
