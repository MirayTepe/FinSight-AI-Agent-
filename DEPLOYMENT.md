# FinSight — Ücretsiz Canlıya Alma (Deploy) ve Docker Rehberi

FinSight platformunu **tamamen ücretsiz** olarak canlıya almak için en pratik ve popüler yöntemler aşağıda adım adım açıklanmıştır.

---

## 🚀 1. En Kolay & %100 Ücretsiz: Streamlit Community Cloud (Önerilen)

Streamlit uygulamaları için doğrudan resmi, sınırsız ve ücretsiz barındırma hizmetidir.

### Adımlar:
1. **GitHub'a Yükleyin:**
   Projeyi kendi GitHub hesabınızda (Public veya Private) bir depoya (repository) push edin.
   ```bash
   git init
   git add .
   git commit -m "FinSight initial release"
   git remote add origin https://github.com/<kullanici_adiniz>/FinSight.git
   git push -u origin main
   ```

2. **Streamlit Cloud'a Giriş Yapın:**
   - [share.streamlit.io](https://share.streamlit.io/) adresine gidin.
   - GitHub hesabınızla giriş yapın.

3. **Uygulamayı Dağıtın (Deploy):**
   - **New app** butonuna tıklayın.
   - **Repository:** `FinSight` seçin.
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **Advanced Settings (Gizli Değişkenler / Secrets):**
     Secrets alanına API anahtarlarınızı yapıştırın:
     ```toml
     GEMINI_API_KEY = "AIzaSy..."
     SEC_USER_AGENT = "Ad Soyad ad.soyad@email.com"
     LLM_MODE = "gemini_only"
     ```
   - **Deploy!** butonuna basın. 1-2 dakika içinde `https://finsight-xxx.streamlit.app` şeklinde kalıcı ve ücretsiz canlı bağlantınız hazır olur!

---

## 🐳 2. Docker ile Çalıştırma (Konteynerleştirme)

Proje için tam donanımlı `Dockerfile`, `docker-compose.yml` ve `entrypoint.sh` oluşturulmuştur. Bu yapı hem **Streamlit UI (8501)** hem de **FastAPI Backend (8000)** servislerini tek konteynerde çalıştırır.

### Yerel Olarak Docker ile Başlatma:
```bash
# 1. Ortam dosyanızı hazırlayın
cp .env.example .env
# .env içine GEMINI_API_KEY anahtarınızı girin

# 2. Docker Compose ile inşa edin ve başlatın
docker compose up -d --build

# 3. Tarayıcıda açın
# Streamlit Arayüzü: http://localhost:8501
# FastAPI Swagger API: http://localhost:8000/docs
```

### Tek Komutla Docker Build & Run:
```bash
docker build -t finsight:latest .
docker run -p 8501:8501 -p 8000:8000 -e GEMINI_API_KEY="anahtariniz" finsight:latest
```

---

## ☁️ 3. Alternatif Ücretsiz Bulut Barındırıcılar (Docker Destekli)

| Platform | Ücretsiz Paket Limiti | Neden Tercih Edilir? | Canlıya Alma Şekli |
| :--- | :--- | :--- | :--- |
| **Streamlit Cloud** | Sınırsız süre, ücretsiz | Kurulum gerektirmez, en hızlısı | GitHub bağlayıp `app.py` seçin |
| **Hugging Face Spaces** | 16 GB RAM, 2 vCPU ücretsiz | Streamlit ve Docker doğrudan desteklenir | Space oluşturup `Streamlit` veya `Docker` seçin |
| **Render.com** | 750 saat/ay ücretsiz | Otomatik SSL, Dockerfile desteği | Web Service -> GitHub -> Dockerfile |
| **Koyeb** | Ayda 1 ücretsiz Nano mikro VM | Docker konteynerlerini doğrudan çalıştırır | GitHub repo bağlayın, Dockerfile ile deploy edin |

---

## 🔑 Önemli Not (Canlı Ortam Yapılandırması)
Canlıya alırken (Streamlit Cloud veya Bulut Docker sunucularında) yerel makinenizdeki `Ollama` sunucusu bulunmayacağı için ortam değişkenini şu şekilde ayarlayın:
- `LLM_MODE=gemini_only`
- `GEMINI_API_KEY=<Google AI Studio'dan aldığınız ücretsiz Gemini API anahtarı>`
- `SEC_USER_AGENT=<Adınız ve e-posta adresiniz>`

