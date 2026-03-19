import hashlib
import requests
import csv
from io import StringIO
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
import config

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_users_from_sheets():
    try:
        if not config.config.USERS_CSV_URL:
            print("❌ USERS_CSV_URL не задан")
            return []
        
        print(f"🔍 Загружаем пользователей из: {config.config.USERS_CSV_URL[:50]}...")
        response = requests.get(config.config.USERS_CSV_URL, timeout=10)
        response.raise_for_status()
        
        csv_data = response.content.decode('utf-8')
        print("📄 Первые 300 символов CSV:")
        print(repr(csv_data[:300]))
        
        reader = csv.DictReader(StringIO(csv_data))
        rows = list(reader)
        print(f"📊 Всего строк: {len(rows)}")
        
        users = []
        for i, row in enumerate(rows):
            print(f"  строка {i+1}: {row}")
            if 'username' in row and 'password_hash' in row and 'role' in row:
                users.append({
                    'username': row['username'].strip(),
                    'password_hash': row['password_hash'].strip(),
                    'role': row['role'].strip()
                })
            else:
                print(f"  ⚠️ строка {i+1} пропущена (ключи: {list(row.keys())})")
        
        print(f"✅ Найдено пользователей: {len(users)}")
        return users
    except Exception as e:
        print(f"🔥 Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return []

def authenticate_user(username, password):
    print(f"🔐 authenticate_user: username='{username}'")
    users = get_users_from_sheets()
    password_hash = hash_password(password)
    print(f"   вычисленный хеш: {password_hash}")
    
    for user in users:
        print(f"   сравниваем с: username='{user['username']}', хеш='{user['password_hash']}'")
        if user['username'] == username and user['password_hash'] == password_hash:
            print("   ✅ НАЙДЕН!")
            return user
    
    print("   ❌ совпадений нет")
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            verify_jwt_in_request()
            return f(*args, **kwargs)
        except Exception as e:
            print(f"🔒 Ошибка авторизации: {e}")
            return jsonify({"error": "Требуется авторизация", "ok": False}), 401
    return decorated_function
