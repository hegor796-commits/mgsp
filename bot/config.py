import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    EXCEL_DB_PATH: str = os.getenv("EXCEL_DB_PATH", "data/database.xlsx")
    STORAGE_PATH: str = os.getenv("STORAGE_PATH", "storage/")

    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не задан в переменных окружения")
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY не задан в переменных окружения")


settings = Settings()
