import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins="*")

# Токены из переменных окружения (добавьте их в настройках Render)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")

# URL для API
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
MAX_API_URL = "https://botapi.max.ru"  # Базовый URL для MAX API (уточните в документации)

@app.route('/', methods=['POST'])
def handle_post():
    try:
        # Получаем данные из формы
        post_text = request.form.get('text', '')
        telegram_chat_id = request.form.get('telegram_chat_id', '')
        max_chat_id = request.form.get('max_chat_id', '')
        files = request.files.getlist('media_files')
        
        print(f"Запрос: telegram_chat_id={telegram_chat_id}, max_chat_id={max_chat_id}, файлов={len(files)}")
        
        # Результаты отправки
        results = {}
        
        # Отправка в Telegram (если указан chat_id)
        if telegram_chat_id:
            tg_result = send_to_telegram(post_text, telegram_chat_id, files)
            results['telegram'] = tg_result
        else:
            results['telegram'] = {"status": "skipped", "reason": "no chat_id"}
        
        # Отправка в MAX (если указан chat_id)
        if max_chat_id:
            # В MAX пока только текст (медиа не поддерживаются)
            max_result = send_to_max(post_text, max_chat_id)
            results['max'] = max_result
        else:
            results['max'] = {"status": "skipped", "reason": "no chat_id"}
        
        # Формируем общий ответ
        overall_ok = all(r.get('ok', False) for r in results.values() if isinstance(r, dict) and 'ok' in r)
        return jsonify({"ok": overall_ok, "results": results}), 200
        
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        return jsonify({"error": str(e), "ok": False}), 500

def send_to_telegram(text, chat_id, files):
    """Отправка в Telegram (с поддержкой медиа)"""
    try:
        # Если есть файлы — отправляем медиагруппой
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
                if idx == 0 and text:
                    media_item['caption'] = text
                    media_item['parse_mode'] = 'HTML'
                
                media.append(media_item)
                attachments[attach_name] = (filename, file.stream, mime_type)
            
            if not media:
                return {"ok": False, "error": "Нет поддерживаемых файлов"}
            
            payload = {
                'chat_id': chat_id,
                'media': json.dumps(media[:10])
            }
            
            files_for_tg = [(name, (fname, stream, mime)) for name, (fname, stream, mime) in attachments.items()]
            
            response = requests.post(
                f"{TELEGRAM_API_URL}/sendMediaGroup",
                data=payload,
                files=files_for_tg
            )
            
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        
        # Если только текст
        elif text:
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return response.json() if response.status_code == 200 else {"ok": False, "error": response.text}
        
        else:
            return {"ok": False, "error": "Нет контента для публикации"}
            
    except Exception as e:
        print(f"Ошибка в send_to_telegram: {e}")
        return {"ok": False, "error": str(e)}

def send_to_max(text, chat_id):
    """Отправка текстового сообщения в MAX (медиа пока не поддерживаются)"""
    try:
        if not text:
            return {"ok": False, "error": "Нет текста для публикации"}
        
        # Предупреждение о медиа (если нужно)
        # Здесь можно добавить логику, если MAX научится принимать файлы
        
        headers = {
            'Authorization': MAX_BOT_TOKEN,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'chat_id': chat_id,
            'text': text
        }
        
        # Уточните эндпоинт в документации MAX
        response = requests.post(
            f"{MAX_API_URL}/messages/send",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"ok": False, "error": f"MAX API error: {response.text}"}
            
    except Exception as e:
        print(f"Ошибка в send_to_max: {e}")
        return {"ok": False, "error": str(e)}

@app.route('/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    app.run(debug=False, port=5000)
