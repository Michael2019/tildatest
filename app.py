import os
import json
import requests
import csv
import time
from io import BytesIO, StringIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
    get_jwt
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

# ============= ОТПРАВКА В TELEGRAM =============
def send_to_telegram(chat_id, text, files_data):
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
                    print(f" ⚠️ файл {filename} пропущен (неподдерживаемый тип)")
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

            if not media:
                return {"ok": False, "error": "Нет поддерживаемых файлов"}

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload, files=files_for_tg)
            print(f" Telegram response: {response.status_code} - {response.text[:200]}")
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        elif text:
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            print(f" Telegram response: {response.status_code} - {response.text[:200]}")
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        else:
            return {"ok": False, "error": "Нет контента"}
    except Exception as e:
        print(f"🔥 Ошибка в send_to_telegram: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

# ============= ОТПРАВКА В MAX (С ПОДДЕРЖКОЙ ФАЙЛОВ) =============
def send_to_max(chat_id, text, files_data=None):
    print(f"📱 send_to_max: chat_id={chat_id}, files={len(files_data) if files_data else 0}")

    if not MAX_BOT_TOKEN:
        print("❌ MAX_BOT_TOKEN не задан")
        return {"ok": False, "error": "MAX_BOT_TOKEN not configured", "skipped": True}

    token_preview = MAX_BOT_TOKEN[:5] + "..." if len(MAX_BOT_TOKEN) > 5 else MAX_BOT_TOKEN
    print(f"🔑 Токен MAX (первые 5 символов): {token_preview}")

    # Проверяем токен
    test_headers = {'Authorization': MAX_BOT_TOKEN, 'Content-Type': 'application/json'}
    test_payload = {"text": "🔄 Проверка соединения с MAX"}
    try:
        test_resp = requests.post(
            f"https://platform-api.max.ru/messages?chat_id={chat_id}",
            headers=test_headers,
            json=test_payload,
            timeout=10
        )
        if test_resp.status_code == 401:
            print("❌ Токен MAX недействителен (401 при тестовой отправке текста)")
            return {"ok": False, "error": "Invalid MAX token", "skipped": False}
        elif test_resp.status_code != 200:
            print(f"⚠️ Тестовая отправка текста вернула {test_resp.status_code}: {test_resp.text[:100]}")
        else:
            print("✅ Токен MAX рабочий")
    except Exception as e:
        print(f"⚠️ Не удалось выполнить тестовую отправку: {e}")

    message_attachments = []

    if files_data:
        for filename, content, mime_type in files_data:
            if 'image' in mime_type:
                file_type = 'image'
            elif 'video' in mime_type:
                file_type = 'video'
            else:
                print(f" ⚠️ Файл {filename} пропущен (неподдерживаемый тип {mime_type})")
                continue

            try:
                # Шаг 1: Получить URL для загрузки
                print(f"   → Запрашиваем URL для {filename} (тип {file_type})")
                upload_req = requests.post(
                    "https://platform-api.max.ru/uploads",
                    params={'type': file_type},
                    headers={'Authorization': MAX_BOT_TOKEN},
                    timeout=30
                )
                if upload_req.status_code != 200:
                    print(f"   ❌ Не удалось получить URL: {upload_req.status_code} - {upload_req.text[:100]}")
                    continue
                upload_data = upload_req.json()
                if 'url' not in upload_data:
                    print(f"   ❌ Ответ /uploads не содержит url: {upload_data}")
                    continue
                upload_url = upload_data['url']
                print(f"   ✅ URL получен: {upload_url[:80]}...")

                # Шаг 2: Загрузить файл методом POST с multipart/form-data
                print(f"   → Загружаем файл {filename} ({len(content)} байт) через POST")
                files = {'data': (filename, content, mime_type)}
                headers_upload = {'Authorization': MAX_BOT_TOKEN}
                upload_file_resp = requests.post(
                    upload_url,
                    files=files,
                    headers=headers_upload,
                    timeout=60
                )
                if upload_file_resp.status_code != 200:
                    print(f"   ❌ Ошибка загрузки: {upload_file_resp.status_code} - {upload_file_resp.text[:200]}")
                    continue

                upload_result = upload_file_resp.json()
                print(f"   ✅ Ответ загрузки: {upload_result}")
                # Извлекаем token из структуры {'photos': {'key': {'token': ...}}}
                photos = upload_result.get('photos')
                if not photos:
                    print(f"   ❌ В ответе загрузки нет поля 'photos'")
                    continue
                first_photo_key = next(iter(photos))
                token_info = photos[first_photo_key]
                file_token = token_info.get('token')
                if not file_token:
                    print(f"   ❌ В ответе загрузки нет token в photos")
                    continue

                print(f"   ✅ Файл загружен, token={file_token[:10]}...")
                time.sleep(1.0)

                message_attachments.append({
                    'type': file_type,
                    'payload': {
                        'token': file_token,
                        'name': filename
                    }
                })
                print(f"   ✅ Вложение добавлено для {filename}")

            except Exception as e:
                print(f"🔥 Ошибка при обработке {filename}: {e}")
                import traceback
                traceback.print_exc()

    # Формируем тело сообщения
    message_body = {}
    if text:
        message_body['text'] = text
        message_body['format'] = 'html'
    if message_attachments:
        message_body['attachments'] = message_attachments

    if not message_body:
        return {"ok": False, "error": "Нет контента для отправки", "skipped": True}

    # Отправляем сообщение
    try:
        print(f"   → Отправляем сообщение в MAX (текст={bool(text)}, вложений={len(message_attachments)})")
        send_msg_resp = requests.post(
            f"https://platform-api.max.ru/messages?chat_id={chat_id}",
            headers={'Authorization': MAX_BOT_TOKEN, 'Content-Type': 'application/json'},
            json=message_body,
            timeout=30
        )
        if send_msg_resp.status_code == 200:
            print("   ✅ Сообщение в MAX отправлено")
            return {"ok": True, "result": send_msg_resp.json()}
        else:
            print(f"   ❌ Ошибка отправки сообщения: {send_msg_resp.status_code} - {send_msg_resp.text[:200]}")
            return {"ok": False, "error": send_msg_resp.text}
    except Exception as e:
        print(f"🔥 Ошибка при отправке сообщения: {e}")
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
        weekday = request.form.get('weekday', '')
        time_val = request.form.get('time', '')
        telegram_chat_id = request.form.get('chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')
        uploaded_files = request.files.getlist('media_files')

        print(f" Telegram chat_id: {telegram_chat_id}")
        print(f" MAX chat_id: {max_chat_id}")
        print(f" файлов получено: {len(uploaded_files)}")

        files_data = []
        for f in uploaded_files:
            content = f.read()
            files_data.append((f.filename, content, f.mimetype))
            print(f" файл: {f.filename}, размер: {len(content)} байт, MIME: {f.mimetype}")

        if not telegram_chat_id:
            return jsonify({"error": "Не указан ID канала Telegram", "ok": False}), 400

        # Формируем текст поста: сначала добавляем день и время, затем шаблон
        post_text = get_post_template(category, module, lesson)
        if weekday and time_val:
            # Преобразуем: "воскресенье" и "10:15" → "(#воскресенье_10_15)"
            weekday_lower = weekday.lower()
            time_clean = time_val.replace(':', '_')
            prefix = f"(#{weekday_lower}_{time_clean})\n\n"
            post_text = prefix + post_text

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
        print(f"🔥 /post error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "ok": False}), 500

# ============= СТАРЫЙ ЭНДПОИНТ (ДЛЯ СОВМЕСТИМОСТИ) =============
# @app.route('/', methods=['POST'])
# def handle_post_legacy():
#     # закомментирован для безопасности
#     pass

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
    print(f"🚀 Запуск сервера на порту {port}, хост 0.0.0.0")
    app.run(host='0.0.0.0', port=port, debug=False)
