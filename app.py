import os
import json
import requests
import csv
from io import StringIO
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

import config
import auth

app = Flask(__name__)
CORS(app, origins="*")

# Настройка JWT
app.config['JWT_SECRET_KEY'] = config.config.JWT_SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.config.JWT_ACCESS_TOKEN_EXPIRES
jwt = JWTManager(app)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

# ============= АВТОРИЗАЦИЯ =============
@app.route('/api/login', methods=['POST'])
def login():
    """Вход, получение JWT токена"""
    try:
        data = request.get_json()
        print(f"🔑 /api/login: получены данные: {data}")
        
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            print("   ❌ нет логина или пароля")
            return jsonify({"error": "Логин и пароль обязательны", "ok": False}), 400

        user = auth.authenticate_user(username, password)
        if user:
            access_token = create_access_token(identity={
                'username': user['username'],
                'role': user['role']
            })
            print(f"   ✅ успешный вход для {username}")
            return jsonify({
                "ok": True,
                "access_token": access_token,
                "user": user
            }), 200
        else:
            print(f"   ❌ неверные данные для {username}")
            return jsonify({"error": "Неверный логин или пароль", "ok": False}), 401
    except Exception as e:
        print(f"🔥 /api/login: ошибка {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "ok": False}), 500
@app.route('/api/me', methods=['GET'])
@jwt_required()
def me():
    """Информация о текущем пользователе"""
    try:
        current_user = get_jwt_identity()
        return jsonify({"ok": True, "user": current_user}), 200
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500

# ============= ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ =============
def get_post_template(category, module, lesson):
    """Получает текст шаблона из CSV Google Sheets"""
    try:
        if not SHEETS_CSV_URL:
            return f"{category}, модуль {module}, занятие {lesson}"
        response = requests.get(SHEETS_CSV_URL, timeout=10)
        response.raise_for_status()
        csv_data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))
        rows = list(reader)
        for row in rows:
            if (row.get('category', '').strip() == str(category) and 
                row.get('module', '').strip() == str(module) and 
                row.get('lesson', '').strip() == str(lesson)):
                return row.get('post_text', '').strip()
        return f"{category}, модуль {module}, занятие {lesson}"
    except Exception as e:
        print(f"Ошибка шаблона: {e}")
        return f"{category}, модуль {module}, занятие {lesson}"

# ============= СТАРЫЙ ЭНДПОИНТ (БЕЗ АВТОРИЗАЦИИ) =============
# Пока оставляем как есть, чтобы текущая форма продолжала работать
@app.route('/', methods=['POST'])
def handle_post_legacy():
    """Старая версия – без проверки токена (для совместимости)"""
    try:
        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        chat_id = request.form.get('chat_id', '')
        files = request.files.getlist('media_files')

        if not chat_id:
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)

        # --- Отправка в Telegram (копия твоего кода) ---
        if files:
            media = []
            attachments = {}
            for idx, file in enumerate(files):
                mime_type = file.mimetype or 'image/jpeg'
                filename = file.filename or f"file_{idx}"
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
                if idx == 0 and post_text:
                    media_item['caption'] = post_text
                    media_item['parse_mode'] = 'HTML'
                media.append(media_item)
                attachments[attach_name] = (filename, file.stream, mime_type)

            if not media:
                return jsonify({"error": "Нет поддерживаемых файлов", "ok": False}), 400

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload, files=files_for_tg)
            return jsonify(response.json()), response.status_code

        elif post_text:
            payload = {'chat_id': chat_id, 'text': post_text, 'parse_mode': 'HTML'}
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return jsonify(response.json()), response.status_code
        else:
            return jsonify({"error": "Нет контента", "ok": False}), 400

    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500

# ============= НОВЫЙ ЗАЩИЩЁННЫЙ ЭНДПОИНТ =============
@app.route('/post', methods=['POST'])
@jwt_required()
def create_post():
    """Создание поста (требуется JWT токен)"""
    try:
        current_user = get_jwt_identity()
        print(f"👤 Пользователь {current_user['username']} создаёт пост")

        # Логируем все полученные form-данные (кроме файлов)
        print(f"  category: {request.form.get('category')}")
        print(f"  module: {request.form.get('module')}")
        print(f"  lesson: {request.form.get('lesson')}")
        print(f"  chat_id: {request.form.get('chat_id')}")
        
        files = request.files.getlist('media_files')
        print(f"  файлов получено: {len(files)}")
        for idx, f in enumerate(files):
            print(f"    файл {idx+1}: {f.filename}, MIME: {f.mimetype}")

        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        chat_id = request.form.get('chat_id', '')

        if not chat_id:
            print("  ❌ нет chat_id")
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400

        post_text = get_post_template(category, module, lesson)
        print(f"  сформированный текст: {post_text[:100]}...")

        # --- Отправка в Telegram (точно такой же код, как выше) ---
        if files:
            media = []
            attachments = {}
            for idx, file in enumerate(files):
                mime_type = file.mimetype or 'image/jpeg'
                filename = file.filename or f"file_{idx}"
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print(f"    ⚠️ файл {filename} пропущен (неподдерживаемый тип)")
                    continue
                attach_name = f"file{idx}"
                media_item = {
                    'type': media_type,
                    'media': f'attach://{attach_name}'
                }
                if idx == 0 and post_text:
                    media_item['caption'] = post_text
                    media_item['parse_mode'] = 'HTML'
                media.append(media_item)
                attachments[attach_name] = (filename, file.stream, mime_type)

            if not media:
                print("  ❌ нет поддерживаемых файлов")
                return jsonify({"error": "Нет поддерживаемых файлов", "ok": False}), 400

            payload = {'chat_id': chat_id, 'media': json.dumps(media[:10])}
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            
            print(f"  отправляем в Telegram: {TELEGRAM_API_URL}/sendMediaGroup")
            print(f"  payload: {payload}")
            
            response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload, files=files_for_tg)
            
            print(f"  ответ Telegram: статус {response.status_code}")
            print(f"  тело ответа: {response.text[:500]}")
            
            return jsonify(response.json()), response.status_code

        elif post_text:
            payload = {'chat_id': chat_id, 'text': post_text, 'parse_mode': 'HTML'}
            print(f"  отправляем текст: {payload}")
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            print(f"  ответ Telegram: статус {response.status_code}")
            print(f"  тело ответа: {response.text[:500]}")
            return jsonify(response.json()), response.status_code
        else:
            print("  ❌ нет контента")
            return jsonify({"error": "Нет контента", "ok": False}), 400

    except Exception as e:
        print(f"🔥 КРИТИЧЕСКАЯ ОШИБКА в /post: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "ok": False}), 500
@app.route('/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
