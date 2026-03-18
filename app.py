import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# Разрешаем запросы с вашей Тильды (можно заменить * на конкретный адрес)
CORS(app, origins="*")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route('/', methods=['POST'])
def handle_post():
    """
    Принимает форму с текстом и файлами, отправляет всё одним альбомом в Telegram
    """
    try:
        # 1. Получаем данные из формы
        post_text = request.form.get('text', '')
        chat_id = request.form.get('chat_id', '')
        files = request.files.getlist('media_files')
        
        print(f"Запрос: chat_id={chat_id}, файлов={len(files)}")
        
        if not chat_id:
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400
        
        # 2. Если есть файлы — готовим медиагруппу
        if files:
            media = []          # список элементов альбома
            attachments = {}     # словарь файлов для прикрепления к запросу
            
            for idx, file in enumerate(files):
                # Определяем тип по MIME
                mime_type = file.mimetype or 'image/jpeg'
                filename = file.filename or f"file_{idx}"
                
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print(f"Пропущен неподдерживаемый файл: {filename} ({mime_type})")
                    continue
                
                # Уникальное имя для attach (должно быть допустимым в multipart)
                attach_name = f"file{idx}"
                
                # Элемент альбома
                media_item = {
                    'type': media_type,
                    'media': f'attach://{attach_name}'
                }
                # Добавляем подпись только к первому элементу
                if idx == 0 and post_text:
                    media_item['caption'] = post_text
                    media_item['parse_mode'] = 'HTML'
                
                media.append(media_item)
                # Сохраняем файл для отправки
                attachments[attach_name] = (filename, file.stream, mime_type)
            
            if not media:
                return jsonify({"error": "Нет поддерживаемых файлов", "ok": False}), 400
            
            # Ограничение Telegram: не более 10 элементов в альбоме
            if len(media) > 10:
                media = media[:10]
                print("Обрезано до 10 файлов")
            
            # 3. Формируем запрос к Telegram API
            payload = {
                'chat_id': chat_id,
                'media': json.dumps(media)   # обязательная JSON-строка
            }
            
            # Подготавливаем файлы для multipart-запроса
            files_for_tg = []
            for name, (fname, stream, mime) in attachments.items():
                files_for_tg.append((name, (fname, stream, mime)))
            
            # Отправляем один запрос sendMediaGroup
            response = requests.post(
                f"{TELEGRAM_API_URL}/sendMediaGroup",
                data=payload,
                files=files_for_tg
            )
            
            print(f"Ответ Telegram: {response.status_code}")
            if response.status_code != 200:
                print(f"Текст ошибки: {response.text}")
            
            return jsonify(response.json()), response.status_code
        
        # 4. Если файлов нет, но есть текст — просто отправляем сообщение
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
    """Проверка, что сервер жив"""
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    app.run(debug=False, port=5000)
