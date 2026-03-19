import hashlib
import requests
import csv
from io import StringIO
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
import config

class AuthError(Exception):
    pass

def hash_password(password):
    """Хеширует пароль с помощью SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_users_from_sheets():
    """Загружает пользователей из Google Sheets"""
    try:
        if not config.config.SHEETS_CSV_URL:
            print("SHEETS_CSV_URL не задан")
            return []
        
        response = requests.get(config.config.SHEETS_CSV_URL, timeout=10)
        response.raise_for_status()
        
        # Принудительно декодируем как UTF-8
        csv_data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))
        
        users = []
        for row in reader:
            # Проверяем, что это лист Users (по наличию нужных колонок)
            if 'username' in row and 'password_hash' in row and 'role' in row:
                users.append({
                    'username': row['username'].strip(),
                    'password_hash': row['password_hash'].strip(),
                    'role': row['role'].strip()
                })
        
        return users
    except Exception as e:
        print(f"Ошибка загрузки пользователей: {e}")
        return []

def authenticate_user(username, password):
    """Проверяет логин и пароль"""
    users = get_users_from_sheets()
    password_hash = hash_password(password)
    
    for user in users:
        if user['username'] == username and user['password_hash'] == password_hash:
            return {
                'username': user['username'],
                'role': user['role']
            }
    return None

def role_required(required_role):
    """Декоратор для проверки роли пользователя"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                verify_jwt_in_request()
                current_user = get_jwt_identity()
                
                # Проверяем роль (в JWT мы сохраняем и username и role)
                if current_user.get('role') != required_role:
                    return jsonify({"error": "Недостаточно прав", "ok": False}), 403
                
                return f(*args, **kwargs)
            except Exception as e:
                return jsonify({"error": "Ошибка авторизации", "ok": False}), 401
        return decorated_function
    return decorator

def login_required(f):
    """Декоратор для проверки наличия токена (любая роль)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            verify_jwt_in_request()
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({"error": "Требуется авторизация", "ok": False}), 401
    return decorated_function