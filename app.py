import os
import json
import requests
import csv
import time
import traceback
from io import BytesIO, StringIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity
)

import config
import auth

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Authorization", "Content-Type"])

# ================= JWT =================
app.config['JWT_SECRET_KEY'] = config.config.JWT_SECRET_KEY or "dev-key"
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.config.JWT_ACCESS_TOKEN_EXPIRES
jwt = JWTManager(app)

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_API_URL = "https://platform-api.max.ru"
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

print("\n========== ENV CHECK ==========")
print("BOT_TOKEN:", "OK" if BOT_TOKEN else "❌ NONE")
print("MAX_BOT_TOKEN:", MAX_BOT_TOKEN[:20] + "..." if MAX_BOT_TOKEN else "❌ NONE")
print("================================\n")


# ================= TEMPLATE =================
def get_post_template(category, module, lesson):
    try:
        response = requests.get(SHEETS_CSV_URL, timeout=10)
        reader = csv.DictReader(StringIO(response.text))

        for row in reader:
            if (
                row.get('category') == category and
                row.get('module') == module and
                row.get('lesson') == lesson
            ):
                return row.get('post_text')

        return f"{category}, модуль {module}, занятие {lesson}"
    except:
        return f"{category}, модуль {module}, занятие {lesson}"


# ================= TELEGRAM =================
def send_to_telegram(chat_id, text, files_data):
    try:
        print(f"📱 TELEGRAM → {chat_id}")

        if files_data:
            media = []
            attachments = {}

            for i, (name, content, mime) in enumerate(files_data):
                t = "photo" if "image" in mime else "video"
                attach = f"file{i}"

                item = {"type": t, "media": f"attach://{attach}"}
                if i == 0:
                    item["caption"] = text

                media.append(item)
                attachments[attach] = (name, BytesIO(content), mime)

            res = requests.post(
                f"{TELEGRAM_API_URL}/sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files=list(attachments.items())
            )

        else:
            res = requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                data={"chat_id": chat_id, "text": text}
            )

        print("TG:", res.status_code, res.text[:200])
        return res.json()

    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# ================= MAX HELPERS =================

def max_headers_variants():
    """Пробуем все варианты авторизации"""
    return [
        {"Authorization": f"Bearer {MAX_BOT_TOKEN}"},
        {"Authorization": MAX_BOT_TOKEN},
        {"X-Auth-Token": MAX_BOT_TOKEN}
    ]


def max_request(method, url, **kwargs):
    """Пробует разные заголовки"""
    for i, headers in enumerate(max_headers_variants()):
        try:
            print(f"🔑 MAX auth try #{i+1}: {list(headers.keys())[0]}")

            res = requests.request(
                method,
                url,
                headers=headers,
                timeout=10,
                **kwargs
            )

            print(f"   status: {res.status_code}, body: {res.text[:200]}")

            if res.status_code != 401:
                return res

        except Exception as e:
            print("   error:", e)

    return res  # последний ответ


# ================= MAX =================

def upload_file_to_max(file_bytes, file_type):
    try:
        print(f"⬆️ upload {file_type}, size={len(file_bytes)}")

        # шаг 1
        res = max_request("POST", f"{MAX_API_URL}/uploads?type={file_type}")
        data = res.json()

        upload_url = data.get("url")
        if not upload_url:
            raise Exception("нет upload_url")

        # шаг 2
        res = requests.post(upload_url, files={"data": file_bytes})
        print("   upload result:", res.status_code, res.text[:200])

        token = res.json().get("token")
        if not token:
            raise Exception("нет token")

        return token

    except Exception as e:
        print("🔥 UPLOAD ERROR:", e)
        traceback.print_exc()
        return None


def send_to_max(chat_id, text):
    try:
        print(f"📱 MAX TEXT → {chat_id}")

        payload = {"chat_id": int(chat_id), "text": text}

        res = max_request(
            "POST",
            f"{MAX_API_URL}/messages",
            json=payload
        )

        return res.json()

    except Exception as e:
        traceback.print_exc()
        return {"ok": False}


def send_to_max_with_media(chat_id, text, files_data):
    try:
        print(f"📱 MAX MEDIA → {chat_id}")

        attachments = []

        for name, content, mime in files_data:
            if "image" in mime:
                t = "image"
            elif "video" in mime:
                t = "video"
            else:
                continue

            token = upload_file_to_max(content, t)
            if token:
                attachments.append({
                    "type": t,
                    "payload": {"token": token}
                })

        print("attachments:", len(attachments))

        time.sleep(2)

        payload = {
            "chat_id": int(chat_id),
            "text": text,
            "attachments": attachments
        }

        res = max_request(
            "POST",
            f"{MAX_API_URL}/messages",
            json=payload
        )

        return res.json()

    except Exception as e:
        traceback.print_exc()
        return {"ok": False}


# ================= AUTH =================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    user = auth.authenticate_user(data.get('username'), data.get('password'))

    if user:
        token = create_access_token(identity=user['username'])
        return jsonify({"ok": True, "access_token": token, "user": user})

    return jsonify({"ok": False}), 401


# ================= MAIN =================
@app.route('/post', methods=['POST'])
@jwt_required()
def create_post():
    try:
        print("\n🚀 NEW POST")

        category = request.form.get('category')
        module = request.form.get('module')
        lesson = request.form.get('lesson')
        tg = request.form.get('chat_id')
        mx = request.form.get('max_chat_id')

        files = request.files.getlist('media_files')
        files_data = [(f.filename, f.read(), f.mimetype) for f in files]

        text = get_post_template(category, module, lesson)

        tg_res = send_to_telegram(tg, text, files_data)

        if mx and MAX_BOT_TOKEN:
            if files_data:
                mx_res = send_to_max_with_media(mx, text, files_data)
            else:
                mx_res = send_to_max(mx, text)
        else:
            mx_res = {"skipped": True}

        return jsonify({
            "ok": True,
            "telegram": tg_res,
            "max": mx_res
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)})


@app.route('/test')
def test():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
