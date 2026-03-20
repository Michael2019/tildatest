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
    get_jwt_identity, get_jwt
)

import config
import auth

app = Flask(__name__)
CORS(app, origins="*", allow_headers=["Authorization", "Content-Type"])

# ================= JWT =================
app.config['JWT_SECRET_KEY'] = config.config.JWT_SECRET_KEY or "super-secret-dev-key"
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.config.JWT_ACCESS_TOKEN_EXPIRES
jwt = JWTManager(app)

@jwt.unauthorized_loader
def unauthorized_callback(reason):
    print(f"🚫 JWT unauthorized: {reason}")
    return jsonify({"error": "Missing or invalid token", "ok": False}), 401

@jwt.invalid_token_loader
def invalid_token_callback(reason):
    print(f"🚫 JWT invalid: {reason}")
    return jsonify({"error": "Invalid token", "ok": False}), 422

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    print("🚫 JWT expired")
    return jsonify({"error": "Token expired", "ok": False}), 401


# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_API_URL = "https://platform-api.max.ru"
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")


# ================= TEMPLATE =================
def get_post_template(category, module, lesson):
    try:
        print(f"📄 Получаем шаблон: {category} | {module} | {lesson}")

        if not SHEETS_CSV_URL:
            print("⚠️ SHEETS_CSV_URL не задан")
            return f"{category}, модуль {module}, занятие {lesson}"

        response = requests.get(SHEETS_CSV_URL, timeout=10)
        print(f"   статус: {response.status_code}")

        csv_data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))

        for row in reader:
            if (
                row.get('category', '').strip() == str(category)
                and row.get('module', '').strip() == str(module)
                and row.get('lesson', '').strip() == str(lesson)
            ):
                print("   ✅ найден шаблон")
                return row.get('post_text', '').strip()

        print("   ⚠️ шаблон не найден")
        return f"{category}, модуль {module}, занятие {lesson}"

    except Exception as e:
        print(f"🔥 TEMPLATE ERROR: {e}")
        traceback.print_exc()
        return f"{category}, модуль {module}, занятие {lesson}"


# ================= TELEGRAM =================
def send_to_telegram(chat_id, text, files_data):
    try:
        print(f"📱 TELEGRAM → chat_id={chat_id}, files={len(files_data)}")

        if files_data:
            media = []
            attachments = {}

            for idx, (filename, content, mime_type) in enumerate(files_data):
                print(f"   файл {idx}: {filename}, {mime_type}, {len(content)} bytes")

                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print("   ⚠️ пропущен")
                    continue

                attach_name = f"file{idx}"

                media_item = {
                    'type': media_type,
                    'media': f'attach://{attach_name}'
                }

                if idx == 0 and text:
                    media_item['caption'] = text
                    media_item['parse_mode'] = 'HTML'

                media.append(media_item)
                attachments[attach_name] = (filename, BytesIO(content), mime_type)

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, val) for name, val in attachments.items()]

            res = requests.post(
                f"{TELEGRAM_API_URL}/sendMediaGroup",
                data=payload,
                files=files_for_tg
            )

            print(f"   ответ: {res.status_code} {res.text[:300]}")
            return res.json()

        else:
            res = requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                data={'chat_id': chat_id, 'text': text}
            )

            print(f"   ответ: {res.status_code} {res.text[:300]}")
            return res.json()

    except Exception as e:
        print(f"🔥 TELEGRAM ERROR: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# ================= MAX =================

def upload_file_to_max(file_bytes, file_type):
    try:
        print(f"⬆️ MAX upload start (type={file_type}, size={len(file_bytes)} bytes)")

        # 1. получить URL
        res = requests.post(
            f"{MAX_API_URL}/uploads?type={file_type}",
            headers={"Authorization": f"Bearer {MAX_BOT_TOKEN}"}
        )

        print(f"   step1 status: {res.status_code}, body: {res.text[:200]}")
        upload_url = res.json().get("url")

        if not upload_url:
            raise Exception("Нет upload_url")

        # 2. загрузить файл
        res = requests.post(
            upload_url,
            files={"data": file_bytes}
        )

        print(f"   step2 status: {res.status_code}, body: {res.text[:200]}")
        token = res.json().get("token")

        if not token:
            raise Exception("Нет token")

        print(f"   ✅ token получен: {token[:10]}...")
        return token

    except Exception as e:
        print(f"🔥 MAX UPLOAD ERROR: {e}")
        traceback.print_exc()
        return None


def send_to_max(chat_id, text):
    try:
        print(f"📱 MAX TEXT → chat_id={chat_id}")

        payload = {
            "chat_id": int(chat_id),
            "text": text
        }

        res = requests.post(
            f"{MAX_API_URL}/messages",
            headers={"Authorization": f"Bearer {MAX_BOT_TOKEN}"},
            json=payload
        )

        print(f"   ответ: {res.status_code} {res.text[:300]}")
        return res.json()

    except Exception as e:
        print(f"🔥 MAX TEXT ERROR: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def send_to_max_with_media(chat_id, text, files_data):
    try:
        print(f"📱 MAX MEDIA → chat_id={chat_id}, files={len(files_data)}")

        attachments = []

        for idx, (filename, content, mime) in enumerate(files_data):
            print(f"   файл {idx}: {filename}, {mime}, {len(content)} bytes")

            if 'image' in mime:
                file_type = "image"
            elif 'video' in mime:
                file_type = "video"
            else:
                print("   ⚠️ пропущен")
                continue

            token = upload_file_to_max(content, file_type)

            if token:
                attachments.append({
                    "type": file_type,
                    "payload": {"token": token}
                })

        print(f"   attachments: {len(attachments)}")

        print("⏳ ждём 2 секунды перед отправкой...")
        time.sleep(2)

        payload = {
            "chat_id": int(chat_id),
            "text": text,
            "attachments": attachments
        }

        print("📤 отправка сообщения в MAX...")
        res = requests.post(
            f"{MAX_API_URL}/messages",
            headers={"Authorization": f"Bearer {MAX_BOT_TOKEN}"},
            json=payload
        )

        print(f"   ответ: {res.status_code} {res.text[:500]}")
        return res.json()

    except Exception as e:
        print(f"🔥 MAX MEDIA ERROR: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# ================= AUTH =================
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        print(f"🔐 LOGIN: {data}")

        user = auth.authenticate_user(data.get('username'), data.get('password'))

        if user:
            token = create_access_token(identity=user['username'])
            print("   ✅ успех")
            return jsonify({"ok": True, "access_token": token, "user": user})

        print("   ❌ неверные данные")
        return jsonify({"ok": False, "error": "Invalid credentials"}), 401

    except Exception as e:
        print(f"🔥 LOGIN ERROR: {e}")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ================= MAIN =================
@app.route('/post', methods=['POST'])
@jwt_required()
def create_post():
    try:
        user = get_jwt_identity()
        print(f"\n🚀 НОВЫЙ POST от {user}")

        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        telegram_chat_id = request.form.get('chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')

        print(f"   category={category}, module={module}, lesson={lesson}")
        print(f"   tg={telegram_chat_id}, max={max_chat_id}")

        uploaded_files = request.files.getlist('media_files')
        print(f"   файлов: {len(uploaded_files)}")

        files_data = [
            (f.filename, f.read(), f.mimetype)
            for f in uploaded_files
        ]

        post_text = get_post_template(category, module, lesson)

        tg_result = send_to_telegram(telegram_chat_id, post_text, files_data)

        if max_chat_id and MAX_BOT_TOKEN:
            if files_data:
                max_result = send_to_max_with_media(max_chat_id, post_text, files_data)
            else:
                max_result = send_to_max(max_chat_id, post_text)
        else:
            print("⚠️ MAX пропущен")
            max_result = {"ok": False, "skipped": True}

        return jsonify({
            "ok": True,
            "telegram": tg_result,
            "max": max_result
        })

    except Exception as e:
        print(f"🔥 POST ERROR: {e}")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/test')
def test():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
