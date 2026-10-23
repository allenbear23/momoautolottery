import http.server
import socketserver
import webbrowser
import os
import json

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

def update_data():
    db_path = os.path.join(DIRECTORY, "quiz_db.json")
    js_path = os.path.join(DIRECTORY, "quiz_data.js")
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        with open(js_path, "w", encoding="utf-8") as f:
            f.write("window.QUIZ_DATA = " + json.dumps(db, ensure_ascii=False, indent=2) + ";")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

if __name__ == "__main__":
    update_data()
    url = f"http://localhost:{PORT}/index.html"
    print(f"啟動題庫網頁伺服器：{url}")
    webbrowser.open(url)
    
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止伺服器")
