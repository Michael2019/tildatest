import os
import json
import requests
import csv
from io import StringIO
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins="*")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Публичная ссылка на CSV (добавьте в переменные окружения)
SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")

def get_post_template(category, module, lesson):
    """Получает текст шаблона из публичного CSV Google Sheets"""
    print(f"get_post_template: category={category}, module={module}, lesson={lesson}")
    try:
        if not SHEETS_CSV_URL:
            print("SHEETS_CSV_URL не задан, возвращаю базовый текст")
            return f"{category}, модуль {module}, занятие {lesson}"
        
        # Загружаем CSV
        response = requests.get(SHEETS_CSV_URL, timeout=10)
        response.raise_for_status()
        
        # Парсим CSV
        csv_data = response.text
        reader = csv.DictReader(StringIO(csv_data))
        rows = list(reader)
        print(f"Загружено {len(rows)} строк из CSV")
        
        if not rows:
            return f"{category}, модуль {module}, занятие {lesson}"
        
        # Ищем строку с совпадением (названия колонок должны быть: category, module, lesson, post_text)
        for row in rows:
            if (row.get('category') == str(category) and 
                row.get('module') == str(module) and 
                row.get('lesson') == str(lesson)):
                print(f"Найден шаблон: {row.get('post_text', '')[:50]}...")
                return row.get('post_text', '')
        
        print("Совпадений не найдено, возвращаю базовый текст")
        return f"{category}, модуль {module}, занятие {lesson}"
        
    except Exception as e:
        print(f"ОШИБКА при чтении CSV: {e}")
        import traceback
        traceback.print_exc()
        return f"{category}, модуль {module}, занятие {lesson}"

@app.route('/', methods=['POST'])
def handle_post():
    try:
        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        chat_id = request.form.get('chat_id', '')
        files = request.files.getlist('media_files')
        
        print(f"Запрос: category={category}, module={module}, lesson={lesson}, chat_id={chat_id}, файлов={len(files)}")
        
        if not chat_id:
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400
        
        post_text = get_post_template(category, module, lesson)
        
        # Отправка в Telegram (с фото/видео)
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
            
            payload = {
                'chat_id': chat_id,
                'media': json.dumps(media[:10])
            }
            
            files_for_tg = []
            for name, (fname, stream, mime) in attachments.items():
                files_for_tg.append((name, (fname, stream, mime)))
            
            response = requests.post(
                f"{TELEGRAM_API_URL}/sendMediaGroup",
                data=payload,
                files=files_for_tg
            )
            return jsonify(response.json()), response.status_code
        
        elif post_text:
            payload = {
                'chat_id': chat_id,
                'text': post_text,
                'parse_mode': 'HTML'
            }
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return jsonify(response.json()), response.status_code
        
        else:
            return jsonify({"error": "Нет контента для публикации", "ok": False}), 400
            
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        return jsonify({"error": str(e), "ok": False}), 500

@app.route('/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    # Берем порт из переменной окружения PORT, если нет - используем 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
