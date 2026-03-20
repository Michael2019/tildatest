import os
import json
import requests
import csv
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

# Настройка JWT
app.config['JWT_SECRET_KEY'] = config.config.JWT_SECRET_KEY or "super-secret-dev-key"
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.config.JWT_ACCESS_TOKEN_EXPIRES
jwt = JWTManager(app)

# Обработчики ошибок JWT
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
MAX_API_URL = "https://platform-api.max.ru"
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

# ============= ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ШАБЛОНОВ =============
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

# ============= ОТПРАВКА В TELEGRAM (С ПОДДЕРЖКОЙ БАЙТОВ) =============
def send_to_telegram(chat_id, text, files_data):
    """
    files_data: список кортежей (filename, content_bytes, mimetype)
    """
    try:
        print(f"📱 send_to_telegram: chat_id={chat_id}, files={len(files_data)}")
        if files_data:
            media = []
            attachments = {}
            for idx, (filename, content, mime_type) in enumerate(files_data):
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print(f"   ⚠️ файл {filename} пропущен (неподдерживаемый тип)")
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
                # Для отправки в Telegram нужен файлоподобный объект
                attachments[attach_name] = (filename, BytesIO(content), mime_type)

            if not media:
                return {"ok": False, "error": "Нет поддерживаемых файлов"}

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload, files=files_for_tg)
            print(f"   Telegram response: {response.status_code} - {response.text[:200]}")
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}

        elif text:
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            print(f"   Telegram response: {response.status_code} - {response.text[:200]}")
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        else:
            return {"ok": False, "error": "Нет контента"}
    except Exception as e:
        print(f"🔥 Ошибка в send_to_telegram: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

# ============= ОТПРАВКА В MAX (СИНХРОННО, БЕЗ ASYNCIO) =============
def send_to_max(chat_id, text, files_data):
    try:
        print(f"📱 send_to_max: начало, chat_id={chat_id}, files={len(files_data)}")
        if not MAX_BOT_TOKEN:
            print("❌ MAX_BOT_TOKEN не задан")
            return {"ok": False, "error": "MAX_BOT_TOKEN not configured", "skipped": True}

        # Если есть файлы, пробуем отправить первый как фото
        if files_data:
            filename, content, mime_type = files_data[0]
            if 'image' in mime_type:
                # Шаг 1: получаем upload_url
                print("🔼 Запрос upload_url для фото...")
                headers = {'Authorization': MAX_BOT_TOKEN}
                params = {'type': 'image'}
                upload_resp = requests.post(f"{MAX_API_URL}/uploads", headers=headers, params=params, timeout=10)
                print(f"   статус: {upload_resp.status_code}, ответ: {upload_resp.text[:200]}")

                if upload_resp.status_code == 200:
                    upload_data = upload_resp.json()
                    upload_url = upload_data.get('url')
                    if upload_url:
                        # Шаг 2: загружаем фото
                        print(f"🔼 Загрузка фото на {upload_url}...")
                        files = {'photo': (filename, content, mime_type)}
                        file_resp = requests.post(upload_url, files=files, timeout=30)
                        print(f"   статус загрузки: {file_resp.status_code}, ответ: {file_resp.text[:200]}")

                        if file_resp.status_code == 200:
                            file_data = file_resp.json()
                            file_id = file_data.get('file_id') or file_data.get('photo_id')
                            if file_id:
                                print(f"   получен file_id: {file_id}")
                                # Шаг 3: отправляем сообщение с фото
                                payload = {
                                    'chat_id': int(chat_id),  # MAX ожидает число
                                    'text': text,
                                    'attachments': [{
                                        'type': 'image',
                                        'payload': {'file_id': file_id}
                                    }]
                                }
                                send_resp = requests.post(
                                    f"{MAX_API_URL}/messages",
                                    headers={'Authorization': MAX_BOT_TOKEN},
                                    json=payload,
                                    timeout=10
                                )
                                print(f"   статус отправки: {send_resp.status_code}, ответ: {send_resp.text[:200]}")
                                if send_resp.status_code == 200:
                                    return {"ok": True, "result": send_resp.json()}
                                else:
                                    # Если фото не отправилось, пробуем просто текст
                                    print("⚠️ Не удалось отправить фото, отправляем только текст")
                                    return send_text_to_max(chat_id, text)
                            else:
                                print("❌ Нет file_id в ответе после загрузки")
                                return send_text_to_max(chat_id, text)
                        else:
                            print("❌ Ошибка загрузки фото")
                            return send_text_to_max(chat_id, text)
                    else:
                        print("❌ Нет upload_url в ответе")
                        return send_text_to_max(chat_id, text)
                else:
                    print("❌ Ошибка получения upload_url")
                    return send_text_to_max(chat_id, text)
            else:
                # Не фото, отправляем только текст
                print(f"⚠️ Тип файла {mime_type} не фото, отправляем только текст")
                return send_text_to_max(chat_id, text)
        else:
            # Нет файлов, только текст
            return send_text_to_max(chat_id, text)

    except Exception as e:
        print(f"🔥 Исключение в send_to_max: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

def send_text_to_max(chat_id, text):
    """Отправка только текста в MAX"""
    try:
        print("📝 Отправка текстового сообщения в MAX")
        payload = {
            'chat_id': int(chat_id),
            'text': text,
            'format': 'html'
        }
        response = requests.post(
            f"{MAX_API_URL}/messages",
            headers={'Authorization': MAX_BOT_TOKEN},
            json=payload,
            timeout=10
        )
        print(f"   статус: {response.status_code}, ответ: {response.text[:200]}")
        if response.status_code == 200:
            return {"ok": True, "result": response.json()}
        else:
            return {"ok": False, "error": response.text}
    except Exception as e:
        print(f"🔥 Ошибка в send_text_to_max: {e}")
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

# ============= ОСНОВНОЙ ЭНДПОИНТ =============
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
        uploaded_files = request.files.getlist('media_files')

        print(f"  Telegram chat_id: {telegram_chat_id}")
        print(f"  MAX chat_id: {max_chat_id}")
        print(f"  файлов получено: {len(uploaded_files)}")

        # === Читаем файлы в память ===
        files_data = []
        for f in uploaded_files:
            content = f.read()
            files_data.append((f.filename, content, f.mimetype))
            print(f"    файл: {f.filename}, размер: {len(content)} байт, MIME: {f.mimetype}")

        if not telegram_chat_id:
            return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)

        # === Отправка в Telegram ===
        tg_result = send_to_telegram(telegram_chat_id, post_text, files_data)

        # === Отправка в MAX ===
        max_result = {"ok": False, "skipped": True}
        if max_chat_id and MAX_BOT_TOKEN:
            max_result = send_to_max(max_chat_id, post_text, files_data)

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

# ============= СТАРЫЙ ЭНДПОИНТ (ДЛЯ СОВМЕСТИМОСТИ) =============
@app.route('/', methods=['POST'])
def handle_post_legacy():
    try:
        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        telegram_chat_id = request.form.get('chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')
        uploaded_files = request.files.getlist('media_files')

        files_data = []
        for f in uploaded_files:
            files_data.append((f.filename, f.read(), f.mimetype))

        if not telegram_chat_id:
            return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)

        tg_result = send_to_telegram(telegram_chat_id, post_text, files_data)
        max_result = {"ok": False, "skipped": True}
        if max_chat_id and MAX_BOT_TOKEN:
            max_result = send_to_max(max_chat_id, post_text, files_data)

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
    max_status = "токен присутствует" if MAX_BOT_TOKEN else "не задан"
    return jsonify({
        "status": "ok",
        "message": "Сервер работает!",
        "max_bot": max_status
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
