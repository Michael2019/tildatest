import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
CORS(app, origins="*")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Google Sheets настройки
SERVICE_ACCOUNT_FILE = 'credentials.json'  # путь к файлу на сервере
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")  # ID вашей таблицы

def get_post_template(category, module, lesson):
    """
    Получает текст шаблона из Google Sheets по категории, модулю и занятию
    """
    print(f"get_post_template: category={category}, module={module}, lesson={lesson}")  # отладка
    try:
        # Авторизация
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        
        # Открываем таблицу по ID
        sheet = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sheet.worksheet('Templates')  # убедитесь, что лист называется Templates
        
        # Получаем все данные (первая строка считается заголовками)
        data = worksheet.get_all_records()
        print(f"Данные из Sheets: {data[:2]}")  # покажем первые две записи для проверки
        
        if not data:
            print("Таблица пуста")
            return f"{category}, модуль {module}, занятие {lesson}"
        
        # Преобразуем в DataFrame
        df = pd.DataFrame(data)
        print(f"Колонки DataFrame: {df.columns.tolist()}")
        
        # Приводим значения к строке для безопасного сравнения
        df['category'] = df['category'].astype(str)
        df['module'] = df['module'].astype(str)
        df['lesson'] = df['lesson'].astype(str)
        
        # Ищем строку с совпадением
        mask = (df['category'] == str(category)) & (df['module'] == str(module)) & (df['lesson'] == str(lesson))
        match = df[mask]
        print(f"Найдено совпадений: {len(match)}")
        
        if not match.empty:
            result = match.iloc[0]['post_text']
            print(f"Найден текст: {result[:50]}...")
            return result
        else:
            print("Совпадений не найдено, возвращаю базовый текст")
            return f"{category}, модуль {module}, занятие {lesson}"
            
    except Exception as e:
        print(f"ОШИБКА в get_post_template: {e}")
        import traceback
        traceback.print_exc()
        return f"{category}, модуль {module}, занятие {lesson}"

@app.route('/', methods=['POST'])
def handle_post():
    try:
        # Получаем данные из формы
        category = request.form.get('category', '')
        module = request.form.get('module', '')
        lesson = request.form.get('lesson', '')
        chat_id = request.form.get('chat_id', '')
        files = request.files.getlist('media_files')
        
        print(f"Запрос: category={category}, module={module}, lesson={lesson}, chat_id={chat_id}, файлов={len(files)}")
        
        if not chat_id:
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400
        
        # Получаем текст шаблона
        post_text = get_post_template(category, module, lesson)
        
        # Отправка в Telegram (как и раньше)
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
    app.run(debug=False, port=5000)
