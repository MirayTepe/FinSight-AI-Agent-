"""
FinSight — Yapılandırma Modülü

.env dosyasından ortam değişkenlerini yükler ve
uygulama genelinde kullanılacak ayarları tanımlar.
"""

import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# --- API Anahtarları ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Uygulama Ayarları ---
APP_ENV = os.getenv("APP_ENV", "development")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

# --- Model Ayarları ---
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "10"))


def validate_config():
    """Zorunlu yapılandırma değerlerini doğrular."""
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY bulunamadı! "
            "Lütfen .env dosyanızı kontrol edin. "
            "Şablon: .env.example"
        )
    return True
