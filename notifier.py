#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bark App 推播通知模組
"""

import os
import json
import urllib.request
import urllib.error

def get_bark_key() -> str:
    # 1. 環境變數
    key = os.environ.get("BARK_KEY") or os.environ.get("BARK_URL")
    if key:
        return key.strip()

    # 2. 本地檔案 bark_key.txt
    file_path = os.path.join(os.path.dirname(__file__), "bark_key.txt")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    return ""

def send_bark(title: str, body: str, group: str = "momo", key: str = None) -> bool:
    bark_key = key or get_bark_key()
    if not bark_key:
        return False

    # 若傳入為完整 URL
    if bark_key.startswith("http://") or bark_key.startswith("https://"):
        url = bark_key.rstrip("/")
        if not url.endswith("/push"):
            # 形式可能是 https://api.day.app/KEY 或自架伺服器
            payload = {
                "title": title,
                "body": body,
                "group": group,
                "icon": "https://img.momoshop.com.tw/ecm/img/xiaoi/momoco_mobile3.png"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST"
            )
        else:
            return False
    else:
        # 標準 Bark Key
        url = "https://api.day.app/push"
        payload = {
            "device_key": bark_key,
            "title": title,
            "body": body,
            "group": group,
            "icon": "https://img.momoshop.com.tw/ecm/img/xiaoi/momoco_mobile3.png"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST"
        )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("code") == 200:
                print(f"[推播成功] Bark 通知已送出: {title}")
                return True
            else:
                print(f"[推播回應] {res_data}")
                return False
    except Exception as e:
        print(f"[推播失敗] Bark 發送失敗: {e}")
        return False

if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else None
    success = send_bark("測試通知", "這是一則來自 momo 自動化腳本的測試推播", key=key)
    if not success and not get_bark_key():
        print("未設定 BARK_KEY，請在環境變數設定 BARK_KEY 或建立 bark_key.txt")
