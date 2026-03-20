import os
import json
import requests
import csv
from io import StringIO
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

# Настройка JWT (с резервным значением, чтобы сервер запускался даже без переменной)
app.config['JWT_SECRET_KEY'] = config.config.JWT_SECRET_KEY or "super-secret-dev-key"
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.config.JWT_ACCESS_TOKEN_EXPIRES
jwt = JWTManager(app)

# Обработчики ошибок JWT (для отладки)
@jwt.unauthorized_loader
def unauthorized_callback(reason):
    print(f"🚫 JWT unauthorized: {reason}")
    return jsonify({"error": "Missing or invalid token", "ok": False}), 401

@jwt.invalid_token_loader
def invalid_token_callback(reason):
    print(f"🚫 JWT invalid token: {reason}")
    return jsonify({"error": "Invalid token", "ok": False}), 422

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    print("🚫 JWT expired token")
    return jsonify({"error": "Token expired", "ok": False}), 401

# Токены и URL
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
# Базовый URL для MAX API (проверено в документации)
MAX_API_URL = "https://platform-api.max.ru"
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

# ============= ФУНКЦИИ ОТПРАВКИ =============
def send_to_telegram(chat_id, text, files):
    """Отправка в Telegram (поддерживает медиагруппы)"""
    try:
        if files:
            media, attachments = [], {}
            for idx, file in enumerate(files):
                mime_type = file.mimetype or 'image/jpeg'
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
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
                attachments[attach_name] = (file.filename or f"file_{idx}", file.stream, mime_type)

            if not media:
                return {"ok": False, "error": "Нет поддерживаемых файлов"}

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload, files=files_for_tg)
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}

        elif text:
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        else:
            return {"ok": False, "error": "Нет контента"}
    except Exception as e:
        print(f"🔥 Ошибка в send_to_telegram: {e}")
        return {"ok": False, "error": str(e)}

def send_to_max(chat_id, text, files):
    """Отправка в MAX Messenger (поддерживает фото и видео)"""
    try:
        print(f"📱 send_to_max: начало, chat_id={chat_id}, text='{text[:50]}...', files={len(files)}")
        if not MAX_BOT_TOKEN:
            print("❌ MAX_BOT_TOKEN не задан, пропускаем MAX")
            return {"ok": False, "error": "MAX_BOT_TOKEN not configured", "skipped": True}

        # Если есть файлы, отправляем первый как медиа
        if files and len(files) > 0:
            file = files[0]
            mime_type = file.mimetype or 'image/jpeg'
            filename = file.filename or "unknown"

            if 'image' in mime_type:
                media_type = 'image'
            elif 'video' in mime_type:
                media_type = 'video'
            else:
                media_type = 'file'

            # Шаг 1: Получаем upload URL с указанием типа
            print(f"🔼 Запрос upload_url с type={media_type}...")
            upload_resp = requests.post(
                f"{MAX_API_URL}/uploads?type={media_type}",
                headers={'Authorization': MAX_BOT_TOKEN},
                timeout=10
            )
            print(f"   статус: {upload_resp.status_code}, ответ: {upload_resp.text[:200]}")

            if upload_resp.status_code == 200:
                upload_data = upload_resp.json()
                upload_url = upload_data.get('upload_url')
                file_token = upload_data.get('token') or upload_data.get('file_id')

                # Если есть прямой file_id без загрузки
                if file_token and not upload_url:
                    payload = {
                        'chat_id': chat_id,
                        'text': text,
                        'attachments': [{
                            'type': media_type,
                            'payload': {'file_id': file_token}
                        }]
                    }
                elif upload_url:
                    # Шаг 2: загружаем файл
                    print(f"🔼 Загрузка файла на {upload_url}...")
                    file_resp = requests.post(
                        upload_url,
                        files={'file': (filename, file.stream, mime_type)},
                        timeout=30
                    )
                    print(f"   статус загрузки: {file_resp.status_code}, ответ: {file_resp.text[:200]}")

                    if file_resp.status_code == 200:
                        file_data = file_resp.json()
                        file_id = file_data.get('file_id')
                        if file_id:
                            payload = {
                                'chat_id': chat_id,
                                'text': text,
                                'attachments': [{
                                    'type': media_type,
                                    'payload': {'file_id': file_id}
                                }]
                            }
                        else:
                            print("❌ Не получен file_id после загрузки")
                            payload = {'chat_id': chat_id, 'text': text, 'format': 'html'}
                    else:
                        payload = {'chat_id': chat_id, 'text': text, 'format': 'html'}
                else:
                    print("❌ Не получен upload_url или file_id")
                    payload = {'chat_id': chat_id, 'text': text, 'format': 'html'}
            else:
                payload = {'chat_id': chat_id, 'text': text, 'format': 'html'}
        else:
            payload = {'chat_id': chat_id, 'text': text, 'format': 'html'}

        # Отправляем сообщение в MAX
        print("📤 Отправка сообщения в MAX...")
        response = requests.post(
            f"{MAX_API_URL}/messages",
            headers={'Authorization': MAX_BOT_TOKEN},
            json=payload,
            timeout=10
        )
        print(f"   статус: {response.status_code}, ответ: {response.text[:200]}")
        return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}

    except Exception as e:
        print(f"🔥 Исключение в send_to_max: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

# ============= АВТОРИЗАЦИЯ =============
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({"error": "Логин и пароль обязательны", "ok": False}), 400

        user = auth.authenticate_user(username, password)
        if user:
            additional_claims = {
                'username': user['username'],
                'role': user['role']
            }
            access_token = create_access_token(
                identity=user['username'],
                additional_claims=additional_claims
            )
            return jsonify({"ok": True, "access_token": access_token, "user": user}), 200
        else:
            return jsonify({"error": "Неверный логин или пароль", "ok": False}), 401
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500

@app.route('/api/me', methods=['GET'])
@jwt_required()
def me():
    try:
        current_username = get_jwt_identity()
        claims = get_jwt()
        return jsonify({
            "ok": True,
            "user": {
                "username": current_username,
                "role": claims.get('role', '')
            }
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500

# ============= ПОЛУЧЕНИЕ ШАБЛОНА =============
def get_post_template(category, module, lesson):
    try:
        if not SHEETS_CSV_URL:
            return f"{category}, модуль {module}, занятие {lesson}"
        response = requests.get(SHEETS_CSV_URL, timeout=10)
        response.raise_for_status()
        csv_data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))
        for row in reader:
            if (row.get('category', '').strip() == str(category) and
                row.get('module', '').strip() == str(module) and
                row.get('lesson', '').strip() == str(lesson)):
                return row.get('post_text', '').strip()
        return f"{category}, модуль {module}, занятие {lesson}"
    except Exception as e:
        print(f"Ошибка шаблона: {e}")
        return f"{category}, модуль {module}, занятие {lesson}"

# ============= ЗАЩИЩЁННЫЙ ЭНДПОИНТ =============
@app.route('/post', methods=['POST'])
@jwt_required()
def create_post():
    try:
        current_username = get_jwt_identity()
        claims = get_jwt()
        print(f"👤 {current_username} (роль: {claims.get('role')}) создаёт пост")

        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        telegram_chat_id = request.form.get('chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')
        files = request.files.getlist('media_files')

        if not telegram_chat_id:
            return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)

        tg_result = send_to_telegram(telegram_chat_id, post_text, files)

        max_result = {"ok": False, "skipped": True}
        if max_chat_id and MAX_BOT_TOKEN:
            max_result = send_to_max(max_chat_id, post_text, files)

        all_ok = (tg_result.get('ok', False) or tg_result.get('skipped', False)) and \
                 (max_result.get('ok', False) or max_result.get('skipped', False))

        return jsonify({
            "ok": all_ok,
            "telegram": tg_result,
            "max": max_result
        }), 200

    except Exception as e:
        print(f"🔥 /post error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "ok": False}), 500

# ============= СТАРЫЙ ЭНДПОИНТ (без авторизации) =============
@app.route('/', methods=['POST'])
def handle_post_legacy():
    try:
        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        telegram_chat_id = request.form.get('chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')
        files = request.files.getlist('media_files')

        if not telegram_chat_id:
            return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)

        tg_result = send_to_telegram(telegram_chat_id, post_text, files)
        max_result = {"ok": False, "skipped": True}
        if max_chat_id and MAX_BOT_TOKEN:
            max_result = send_to_max(max_chat_id, post_text, files)

        all_ok = (tg_result.get('ok', False) or tg_result.get('skipped', False)) and \
                 (max_result.get('ok', False) or max_result.get('skipped', False))

        return jsonify({
            "ok": all_ok,
            "telegram": tg_result,
            "max": max_result
        }), 200

    except Exception as e:
        print(f"🔥 / legacy error: {e}")
        return jsonify({"error": str(e), "ok": False}), 500

@app.route('/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
