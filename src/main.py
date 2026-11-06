
from src.config import validate_config


def main():
    print("=" * 50)
    print("  📈 FinSight AI Agent — Başlatılıyor...")
    print("=" * 50)

    validate_config()
    print("✅ Yapılandırma doğrulandı.")

    print("⏳ Agent modülleri henüz geliştirme aşamasında (M1).")


if __name__ == "__main__":
    main()
