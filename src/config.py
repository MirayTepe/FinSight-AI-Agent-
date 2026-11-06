
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

APP_ENV = os.getenv("APP_ENV", "development")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
LLM_MODE = os.getenv("LLM_MODE", "hybrid").lower()                                           
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "10"))


def validate_config():
    if LLM_MODE == "gemini_only" and not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY bulunamadı! "
            "Lütfen .env dosyanızı kontrol edin. "
            "Şablon: .env.example"
        )
    return True
