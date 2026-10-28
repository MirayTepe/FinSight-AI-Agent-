"""
FinSight — Ana Başlatıcı (CLI)

Komut satırından FinSight agent'ını çalıştırır.
Kullanım: python -m src.main
"""

from src.config import validate_config


def main():
    """FinSight uygulamasını başlatır."""
    print("=" * 50)
    print("  📈 FinSight AI Agent — Başlatılıyor...")
    print("=" * 50)

    # Yapılandırmayı doğrula
    validate_config()
    print("✅ Yapılandırma doğrulandı.")

    # TODO: Agent başlatma (M1 aşamasında geliştirilecek)
    print("⏳ Agent modülleri henüz geliştirme aşamasında (M1).")


if __name__ == "__main__":
    main()
