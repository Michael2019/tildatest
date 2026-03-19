import os
from datetime import timedelta

class Config:
    # Секретный ключ для JWT (обязательно поменяй на свой!)
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    
    # Время жизни токена (например, 7 дней)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7)
    
    # Настройки Google Sheets
    SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")
    
    # ID листа с пользователями (должен называться 'Users')
    USERS_SHEET_NAME = "Users"
    
    # ID листа с шаблонами постов
    TEMPLATES_SHEET_NAME = "Templates"

config = Config()