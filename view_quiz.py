import http.server
import socketserver
import webbrowser
import os
import json
import base64
import time
from datetime import datetime

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIRECTORY, "quiz_db.json")
JS_PATH = os.path.join(DIRECTORY, "quiz_data.js")
ANSWER_DIR = os.path.join(DIRECTORY, "momo answer")


def update_data():
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                db = json.load(f)
            with open(JS_PATH, "w", encoding="utf-8") as f:
                f.write("window.QUIZ_DATA = " + json.dumps(db, ensure_ascii=False, indent=2) + ";")
            return db
        except Exception as e:
            print(f"更新 quiz_data.js 異常: {e}")
    return {"questions": {}}


class QuizAppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/questions":
            db = update_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(db, ensure_ascii=False).encode("utf-8"))
            return
        super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len)

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            body = {}

        if self.path == "/api/report_answer":
            # 社群回報正確答案或標記錯誤選項
            q_key = body.get("question_key") or body.get("text")
            correct = body.get("correct")
            wrong = body.get("wrong")
            unmark = body.get("unmark", False)

            if not q_key:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Missing question_key"}')
                return

            db = {"questions": {}}
            if os.path.exists(DB_PATH):
                with open(DB_PATH, "r", encoding="utf-8") as f:
                    db = json.load(f)

            q_dict = db.setdefault("questions", {})
            rec = q_dict.setdefault(q_key, {})
            rec["text"] = rec.get("text") or q_key
            rec["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if unmark:
                if "correct" in rec:
                    del rec["correct"]
            elif correct:
                rec["correct"] = correct
                # 從錯題列表移除
                if "wrong" in rec:
                    c_txt = correct.get("text") if isinstance(correct, dict) else correct
                    rec["wrong"] = [w for w in rec["wrong"] if (w.get("text") if isinstance(w, dict) else w) != c_txt]

            if wrong:
                wrongs = rec.setdefault("wrong", [])
                w_txt = wrong.get("text") if isinstance(wrong, dict) else wrong
                if not any((w.get("text") if isinstance(w, dict) else w) == w_txt for w in wrongs):
                    wrongs.append(wrong if isinstance(wrong, dict) else {"text": w_txt})

            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            update_data()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "record": rec}, ensure_ascii=False).encode("utf-8"))
            return

        elif self.path == "/api/upload_question":
            # 社群上傳新題目或新截圖
            q_text = (body.get("text") or "").strip()
            sc_b64 = body.get("screenshot_b64")
            sc_name = (body.get("screenshot_name") or f"upload_{int(time.time())}.jpg").strip()
            choices = body.get("choices") or []
            correct = body.get("correct")

            sc_rel_path = ""
            if sc_b64:
                try:
                    if not os.path.exists(ANSWER_DIR):
                        os.makedirs(ANSWER_DIR, exist_ok=True)
                    if "," in sc_b64:
                        sc_b64 = sc_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(sc_b64)
                    save_path = os.path.join(ANSWER_DIR, sc_name)
                    with open(save_path, "wb") as f:
                        f.write(img_bytes)
                    sc_rel_path = f"momo answer/{sc_name}"
                except Exception as e:
                    print(f"儲存上傳截圖異常: {e}")

            if not q_text and sc_rel_path:
                q_text = f"待解題目_{int(time.time())}"

            db = {"questions": {}}
            if os.path.exists(DB_PATH):
                with open(DB_PATH, "r", encoding="utf-8") as f:
                    db = json.load(f)

            q_dict = db.setdefault("questions", {})
            rec = q_dict.setdefault(q_text, {})
            rec["text"] = q_text
            if sc_rel_path:
                rec["screenshot"] = sc_rel_path
            if choices:
                rec["choices"] = choices
            if correct:
                rec["correct"] = correct if isinstance(correct, dict) else {"text": correct}
            rec["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            update_data()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "key": q_text, "record": rec}, ensure_ascii=False).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    update_data()
    url = f"http://localhost:{PORT}/index.html"
    print(f"啟動 momo 知識王社群訓練與題庫伺服器：{url}")
    webbrowser.open(url)

    with socketserver.TCPServer(("", PORT), QuizAppHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止伺服器")
