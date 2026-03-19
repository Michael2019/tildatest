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
