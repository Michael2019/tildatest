import os
from datetime import timedelta

class Config:
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7)
    
    # Ссылка на лист с шаблонами постов
    SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")
    
    # Ссылка на лист с пользователями
    USERS_CSV_URL = os.environ.get("USERS_CSV_URL")

config = Config()
