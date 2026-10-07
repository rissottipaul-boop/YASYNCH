# Развёртывание Turntable в облаке (Cloud Live)

Репозиторий Turntable успешно интегрирован в ваш проект. Для запуска live-версии в облаке выберите наиболее удобный бесплатный вариант:

---

## Вариант 1: Render.com (Рекомендуется)
> **Плюсы:** Официально поддерживается проектом, нативный Docker, автоматический HTTPS, бесплатно.

1. Загрузите проект в свой GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial Turntable commit"
   git remote add origin https://github.com/ВАШ_АККАУНТ/ВАШ_РЕПОЗИТОРИЙ.git
   git push -u origin main
   ```
2. Откройте [render.com](https://render.com) и войдите через GitHub.
3. Нажмите **New +** → **Web Service** → подключите ваш репозиторий.
4. Render автоматически увидит `Dockerfile` и `render.yaml`:
   - **Environment:** Docker
   - **Region:** Frankfurt (или любой близкий)
   - **Plan:** Free
5. В разделе **Environment Variables** укажите:
   - `TELEGRAM_API_ID`: `35237705`
   - `TELEGRAM_API_HASH`: `0dba30ff283126f3c7f3f401506e85a0`
   - `MUSICBRAINZ_CONTACT`: `rissottipaul@gmail.com`
   - `BIND_HOST`: `0.0.0.0`
6. Нажмите **Create Web Service**. Через 2–3 минуты плеер будет доступен по ссылке `https://ваш-проект.onrender.com`.

---

## Вариант 2: Koyeb.com
> **Плюсы:** Быстрый запуск Docker, не уходит в спящий режим на бесплатном тарифе, бесплатный HTTPS.

1. Перейдите на [koyeb.com](https://koyeb.com) и войдите через GitHub.
2. Нажмите **Create Service** → **GitHub**.
3. Выберите репозиторий проекта, тип сборки **Dockerfile**.
4. Порт: `8000`.
5. В разделе **Environment variables** добавьте:
   - `TELEGRAM_API_ID`: `35237705`
   - `TELEGRAM_API_HASH`: `0dba30ff283126f3c7f3f401506e85a0`
   - `MUSICBRAINZ_CONTACT`: `rissottipaul@gmail.com`
   - `BIND_HOST`: `0.0.0.0`
6. Нажмите **Deploy** — получите рабочий URL `https://ваш-сервис.koyeb.app`.

---

## Вариант 3: Hugging Face Spaces (Без привязки карт, 16 ГБ RAM)
> **Плюсы:** Полностью бесплатно, мощные серверы, постоянное хранилище.

1. Откройте [huggingface.co/spaces](https://huggingface.co/spaces) и нажмите **Create new Space**.
2. Введите имя (например, `telegram-turntable`) и выберите **Space SDK: Docker** (Blank).
3. Склонируйте созданный Space и скопируйте в него файлы проекта (или загрузите через Git).
4. Во вкладке **Settings** → **Variables and Secrets** задайте `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `MUSICBRAINZ_CONTACT`.
5. Hugging Face соберет Dockerfile и запустит плеер прямо внутри веб-интерфейса Space.

---

## Авторизация в плеере после запуска:
1. Откройте ссылку на ваше облачное приложение.
2. В веб-интерфейсе нажмите **Link Telegram**.
3. Отсканируйте появившийся QR-код камерой приложения Telegram:
   *Telegram → Настройки → Устройства → Подключить устройство*.
4. Выберите канал `@YAROUTER221` или нужные чаты — Turntable проиндексирует все треки, и вы сможете слушать музыку через браузер или мобильный телефон с плеером, обложками и текстами песен!

