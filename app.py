import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# Разрешаем запросы с вашей Тильды (после тестирования замените * на конкретный адрес)
CORS(app, origins="*")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ВАШ_ТОКЕН_БОТА")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route('/', methods=['POST'])
def handle_post():
    """
    Принимает POST-запрос с формой и отправляет медиа в Telegram
    """
    try:
        # 1. Получаем данные
        post_text = request.form.get('text', '')
        chat_id = request.form.get('chat_id', '')
        files = request.files.getlist('media_files')
        
        print(f"Получен запрос: chat_id={chat_id}, text_length={len(post_text)}, files_count={len(files)}")
        
        if not chat_id:
            return jsonify({"error": "Не указан ID канала", "ok": False}), 400
        
        # 2. Если есть файлы — обрабатываем их
        if files:
            media_group = []
            
            for idx, file in enumerate(files):
                # Определяем тип файла по содержимому, а не по расширению
                mime_type = file.mimetype or 'image/jpeg'  # на всякий случай
                filename = file.filename
                
                print(f"Файл {idx+1}: {filename}, MIME: {mime_type}")
                
                # Выбираем тип медиа для Telegram
                if 'image' in mime_type:
                    media_type = 'photo'
                elif 'video' in mime_type:
                    media_type = 'video'
                else:
                    print(f"Неподдерживаемый тип файла: {mime_type}")
                    continue
                
                # --- ВАЖНОЕ ИЗМЕНЕНИЕ ---
                # Отправляем файл напрямую как фото/видео, используя multipart/form-data
                # Это даст правильный file_id для медиа
                
                files_for_tg = {
                    media_type: (filename, file.stream, mime_type)
                }
                
                # Отправляем в зависимости от типа
                if media_type == 'photo':
                    tg_response = requests.post(
                        f"{TELEGRAM_API_URL}/sendPhoto",
                        data={'chat_id': chat_id},
                        files=files_for_tg
                    )
                else:  # video
                    tg_response = requests.post(
                        f"{TELEGRAM_API_URL}/sendVideo",
                        data={'chat_id': chat_id},
                        files=files_for_tg
                    )
                
                print(f"Ответ от Telegram для файла {filename}: статус {tg_response.status_code}")
                
                if tg_response.status_code == 200:
                    tg_data = tg_response.json()
                    if tg_data.get('ok'):
                        # Получаем file_id из ответа (для фото он лежит в result.photo[-1].file_id)
                        if media_type == 'photo':
                            # У фото может быть несколько размеров, берем самый большой (последний)
                            file_id = tg_data['result']['photo'][-1]['file_id']
                        else:  # video
                            file_id = tg_data['result']['video']['file_id']
                        
                        print(f"Получен file_id: {file_id}")
                        
                        # Формируем элемент для медиагруппы
                        media_item = {
                            'type': media_type,
                            'media': file_id
                        }
                        
                        # Текст добавляем только к первому элементу
                        if idx == 0 and post_text:
                            media_item['caption'] = post_text
                            media_item['parse_mode'] = 'HTML'
                        
                        media_group.append(media_item)
                    else:
                        print(f"Ошибка в ответе Telegram: {tg_data}")
                else:
                    print(f"Ошибка HTTP от Telegram: {tg_response.text}")
            
            # 3. Отправляем медиагруппу, если есть файлы
            if media_group:
                # Telegram API требует не более 10 элементов
                if len(media_group) > 10:
                    media_group = media_group[:10]
                    print("Обрезано до 10 файлов")
                
                payload = {
                    'chat_id': chat_id,
                    'media': json.dumps(media_group)  # обязательно JSON-строка!
                }
                
                print(f"Отправка медиагруппы с {len(media_group)} элементами")
                send_response = requests.post(
                    f"{TELEGRAM_API_URL}/sendMediaGroup",
                    data=payload
                )
                
                print(f"Ответ sendMediaGroup: {send_response.status_code}")
                if send_response.status_code != 200:
                    print(f"Текст ошибки: {send_response.text}")
                
                return jsonify(send_response.json()), send_response.status_code
            
            # Если файлы были, но ни один не обработался
            return jsonify({"error": "Не удалось обработать файлы", "ok": False}), 500
        
        # 4. Если файлов нет, но есть текст — отправляем текстовое сообщение
        elif post_text:
            payload = {
                'chat_id': chat_id,
                'text': post_text,
                'parse_mode': 'HTML'
            }
            send_response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", data=payload)
            return jsonify(send_response.json()), send_response.status_code
        
        else:
            return jsonify({"error": "Нет контента для публикации", "ok": False}), 400
            
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        return jsonify({"error": f"Внутренняя ошибка сервера: {str(e)}", "ok": False}), 500

@app.route('/test', methods=['GET'])
def test():
    """Простой тестовый endpoint для проверки работы сервера"""
    return jsonify({"status": "ok", "message": "Сервер работает!"})

if __name__ == '__main__':
    app.run(debug=False, port=5000)
