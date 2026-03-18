import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# Разрешаем запросы с любого сайта (вашей Тильды). Для продакшена лучше указать конкретный адрес вашей страницы.
CORS(app, origins="*")

# Токен вашего бота, который мы сохранили на шаге 1.
# НАСТОЯТЕЛЬНО РЕКОМЕНДУЕТСЯ использовать переменную окружения в продакшене.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8629058805:AAGaYO1WjDEo9Pq4AADEir4yPiWajM8RPkI")
# Базовый URL для запросов к Telegram API
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route('/', methods=['POST'])
def handle_post():
    """
    Этот адрес будет принимать POST-запросы с вашей формы в Тильде.
    """
    try:
        # 1. Получаем данные из запроса
        # Текст поста
        post_text = request.form.get('text', '')
        # ID канала, куда публиковать
        chat_id = request.form.get('chat_id', '')
        # Список загруженных файлов (до 10 шт.)
        files = request.files.getlist('media_files')

        if not chat_id:
            return jsonify({"error": "Не указан ID канала"}), 400

        if not files and not post_text:
            return jsonify({"error": "Нет контента для публикации (текст или фото/видео)"}), 400

        # 2. Подготовка и отправка медиа-группы в Telegram
        media_group = []
        file_ids = [] # Сюда будем складывать file_id из Telegram после загрузки каждого файла

        # Сначала загружаем каждый файл на сервера Telegram и получаем его file_id
        for file in files:
            # Определяем тип файла по MIME-типу
            mime_type = file.mimetype
            if mime_type and 'image' in mime_type:
                media_type = 'photo'
            elif mime_type and 'video' in mime_type:
                media_type = 'video'
            else:
                # Пропускаем неподдерживаемые типы файлов
                continue

            # Отправляем файл в Telegram как документ, чтобы получить file_id
            files_for_tg = {media_type: (file.filename, file.stream, file.mimetype)}
            tg_response = requests.post(f"{TELEGRAM_API_URL}/sendDocument", data={'chat_id': chat_id}, files=files_for_tg)

            if tg_response.status_code == 200:
                tg_data = tg_response.json()
                if tg_data['ok']:
                    # Получаем file_id отправленного файла
                    file_id = tg_data['result']['document']['file_id']
                    # Формируем элемент медиа-группы
                    media_item = {
                        'type': media_type,
                        'media': file_id,
                    }
                    # Текст добавляем только к первому элементу, чтобы он был подписью ко всему альбому
                    if not media_group and post_text:
                        media_item['caption'] = post_text
                        media_item['parse_mode'] = 'HTML'

                    media_group.append(media_item)
            else:
                print(f"Ошибка загрузки файла {file.filename}: {tg_response.text}")

        # 3. Если нет ни одного файла, но есть текст, отправляем просто текстовое сообщение
        if not media_group and post_text:
            payload = {
                'chat_id': chat_id,
                'text': post_text,
                'parse_mode': 'HTML'
            }
            send_response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return jsonify(send_response.json()), send_response.status_code

        # 4. Если есть файлы, отправляем их как альбом (медиа-группу)
        if media_group:
            # Telegram API требует, чтобы медиа-группа содержала не более 10 элементов
            # и отправлялась как JSON-строка
            payload = {
                'chat_id': chat_id,
                'media': media_group
            }
            # Важно! Параметр 'media' должен быть JSON-строкой
            import json
            payload['media'] = json.dumps(media_group)

            send_response = requests.post(f"{TELEGRAM_API_URL}/sendMediaGroup", data=payload)
            return jsonify(send_response.json()), send_response.status_code

        return jsonify({"error": "Не удалось обработать запрос"}), 500

    except Exception as e:
        print(f"Ошибка на сервере: {e}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

if __name__ == '__main__':
    app.run(debug=False, port=5000)