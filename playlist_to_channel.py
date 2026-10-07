#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
playlist_to_channel.py — превращает tracks.txt в аудиофайлы в Telegram-канале.

Как работает:
  1. Берёт строку "Артист — Название" из tracks.txt.
  2. Отправляет её боту-поисковику @vkmusic_bot (ваш личный чат с ботом).
  3. Если бот присылает меню с кнопками выбора трека — скрипт сам нажимает
     вариант, наиболее похожий на название (или первый). Если аудио пришло
     сразу — берёт его.
  4. Публикует аудио в канал с подписью "Артист — Название".
  5. Список загружается в обратном порядке (последний трек — первым),
     чтобы в канале треки шли в правильном порядке прослушивания.
  6. Прогресс хранится в done.json — скрипт можно прерывать и перезапускать,
     он продолжит с места остановки. Треки без результата попадают в failed.txt.

Перед первым запуском:
  - Откройте @vkmusic_bot в Telegram и нажмите Start (один раз вручную).
  - Получите api_id и api_hash на https://my.telegram.org
    (Products -> API development tools). Телефон в поле числа без '+'.

Запуск:
  pip install telethon
  python playlist_to_channel.py
"""

import asyncio
import difflib
import json
import os
import re
import sys

# Настройка вывода UTF-8 для корректного отображения в консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from telethon import TelegramClient
from telethon.errors import BotResponseTimeoutError, FloodWaitError

# ------------------------- НАСТРОЙКИ -------------------------
API_ID = 35237705                   # <-- впишите ваш api_id (my.telegram.org)
API_HASH = "0dba30ff283126f3c7f3f401506e85a0"    # <-- впишите ваш api_hash
PHONE = "+12255923301"             # <-- впишите ваш номер телефона

CHANNEL = "https://t.me/YAROUTER221"   # канал-получатель (вы — владелец)
MUSIC_BOT = "vkmusic_bot"              # бот-поисковик

TRACKS_FILE = "tracks.txt"         # файл плейлиста (рядом со скриптом)
PROGRESS_FILE = "done.json"
FAILED_FILE = "failed.txt"
SESSION = "playlist_session"

WAIT_REPLY = 25       # сек — максимум ожидания ответа бота (после кнопки таймер сбрасывается)
POLL_EVERY = 1.0      # сек — как часто проверять ответ (быстрый опрос без задержек)
PAUSE_BETWEEN = 2.0   # сек — пауза между треками
MAX_CLICKS = 3        # максимум нажатий кнопок на один трек
# -------------------------------------------------------------


def load_tracks():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, TRACKS_FILE)
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    # убрать возможные дубликаты, сохранив порядок
    seen, out = set(), []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_progress(done):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f, ensure_ascii=False, indent=0)


def is_audio(msg):
    if not msg:
        return False
    if msg.audio:
        dur = getattr(msg.audio, "duration", None)
        if dur is not None and dur == 0:
            return False
        return True
    if msg.file and getattr(msg.file, "mime_type", None) and msg.file.mime_type.startswith("audio/"):
        dur = getattr(msg.file, "duration", None)
        if dur is not None and dur == 0:
            return False
        return True
    return False


def _norm(s):
    """Оставляет только буквы/цифры/пробелы в нижнем регистре."""
    return re.sub(r"[^\w\s]", " ", (s or "").lower()).strip()


def parse_metadata(raw):
    """Извлекает длительность в секундах, размер и битрейт из строки трека бота."""
    clean = (raw or "").replace("__", "").replace("**", "").replace("`", "").strip()
    dur = None
    m_dur = re.search(r"(\d+):(\d{2})", clean)
    if m_dur:
        dur = int(m_dur.group(1)) * 60 + int(m_dur.group(2))

    bitrate = None
    m_br = re.search(r"(?:^|\s)(\d+)\s*(?:k|к|kbps|кбит/с)(?:\s|$)", clean, re.IGNORECASE)
    if m_br:
        bitrate = int(m_br.group(1))

    size = None
    m_size = re.search(r"([\d\.]+\s*(?:[mMгГ][bBбБ]?|[gG][bB]?))", clean)
    if m_size:
        size = m_size.group(1)

    return dur, size, bitrate


def clean_track_title(raw):
    """Очищает строку трека от markdown и метаданных (битрейт, размер, тайминг)."""
    t = (raw or "").replace("**", "").replace("__", "").replace("`", "").strip()
    # Убираем длительность, размер файла, битрейт на конце (например: 4:41 10.7M 319k)
    t = re.sub(r"(?:_{1,2}|\s)*\d+:\d+(?:\s+[\d\.]+[mkbMKbB]+)?(?:\s+\d+[kK])?(?:_{1,2})?\s*$", "", t).strip()
    return t


SERVICE_BTN_PATTERNS = [
    r"^[⬅️➡️◀️▶️❌✖️🚫🎨❓ℹ️⚙️🔄\s]+$",
    r"^(назад|вперед|отмена|закрыть|меню|menu|cancel|close|next|prev|back)$",
    r"^(title|br[:\s*]|los|bitrate|качество|формат|по названию|по исполнителю)",
]


def is_service_button(text):
    """Проверяет, является ли кнопка служебной (пагинация, фильтры, настройки)."""
    t = (text or "").strip().lower()
    if not t:
        return True
    for pat in SERVICE_BTN_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


JUNK_MODIFIERS = {
    "remix", "ремикс", "slowed", "reverb", "speed", "speedup", "speed up",
    "cover", "кавер", "trap", "bass", "boosted", "karaoke", "караоке",
    "instrumental", "edit", "tik tok", "tiktok"
}


def score_match(query, candidate):
    """Оценивает схожесть кандидата с запросом и качество аудиофайла.
    
    1. Жестко отсекает битые треки (0:00 или 0k).
    2. Учитывает покрытие ключевых слов и схожесть строк.
    3. Штрафует ремиксы/slowed/reverb, если пользователь не просил их в запросе.
    4. Дает приоритет полноценным трекам (по длительности и битрейту).
    """
    dur, size, bitrate = parse_metadata(candidate)

    # Жесткий фильтр для пустышек и битых файлов (0:00 или 0k)
    if dur is not None and dur == 0:
        return -999.0
    if bitrate is not None and bitrate == 0:
        return -999.0

    q_norm = _norm(query)
    c_clean = clean_track_title(candidate)
    c_norm = _norm(c_clean)

    q_words = set(q_norm.split())
    c_words = set(c_norm.split())
    if not q_words or not c_words:
        return 0.0

    coverage = len(q_words & c_words) / len(q_words)
    seq = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
    score = coverage * 0.6 + seq * 0.4

    # Штраф за ремиксы/slowed/reverb, если их не было в запросе
    penalty = sum(0.15 for mod in JUNK_MODIFIERS if mod in c_words and mod not in q_words)
    score -= penalty

    # Оценка длительности:
    if dur is not None:
        if dur < 30:  # отрывок / сниппет / рингтон
            score -= 0.35
        elif 45 <= dur <= 600:  # нормальная длительность трека
            score += 0.05

    # Оценка качества (битрейт):
    if bitrate is not None:
        if bitrate >= 256:
            score += 0.05
        elif bitrate >= 192:
            score += 0.03
        elif bitrate < 128:
            score -= 0.05

    return score


def _buttons(msg):
    out = []
    if not msg or not msg.buttons:
        return out
    for row in msg.buttons:
        for b in row:
            if b is None:
                continue
            text = (getattr(b, "text", "") or "").strip()
            if text:
                out.append((b, text))
    return out


def pick_button(msg, query):
    """Выбирает кнопку-результат поиска.

    Поддерживает:
      1. @vkmusic_bot: список вариантов в тексте сообщения (**1.** Название ...),
         а кнопки — просто цифры '1', '2', ...
      2. Боты с названиями прямо на кнопках ('1. Название' или 'Название').
      3. Игнорирует битые треки (0:00, 0k) и выбирает полноценный нормальный файл.
      4. Игнорирует служебные кнопки (пагинация ⬅️ ➡️, закрытие ❌, фильтры Title, Lossless).
      5. Сравнивает варианты с запросом и выбирает наиболее подходящий качественный трек.

    Возвращает (button, description_text) или (None, "").
    """
    buttons = _buttons(msg)
    if not buttons:
        return None, ""

    digit_buttons = {}      # num -> button
    titled_buttons = []     # (button, title, num_or_None)

    for b, text in buttons:
        if is_service_button(text):
            continue
        m_digit = re.match(r"^(\d+)$", text)
        if m_digit:
            digit_buttons[int(m_digit.group(1))] = b
            continue
        m_num_title = re.match(r"^(\d+)[\.\)\-]?\s*(.+)$", text)
        if m_num_title:
            num = int(m_num_title.group(1))
            digit_buttons[num] = b
            titled_buttons.append((b, m_num_title.group(2).strip(), num))
            continue
        titled_buttons.append((b, text, None))

    # Парсим список треков из текста сообщения (формат: **1.** Артист – Трек ...)
    text_tracks = {}
    pattern = r"(?:^|\n)\s*(?:\*\*)?(\d+)[\.\)](?:\*\*)?\s*([^\n]+)"
    for m in re.finditer(pattern, msg.text or ""):
        num = int(m.group(1))
        text_tracks[num] = m.group(2).strip()

    # Добавляем названия из кнопок, если они там были
    for b, title, num in titled_buttons:
        if num and num not in text_tracks:
            text_tracks[num] = title

    # Сценарий 1: есть кнопки-цифры (как у @vkmusic_bot)
    if digit_buttons:
        best_num = None
        best_score = -999.0
        scores = {}
        for num, b in digit_buttons.items():
            raw_title = text_tracks.get(num, "")
            score = score_match(query, raw_title) if raw_title else 0.0
            scores[num] = score
            if score > best_score:
                best_score = score
                best_num = num

        # Список вариантов с нормальным качеством (не битые 0:00 / 0k)
        valid_nums = [n for n in digit_buttons if (n in text_tracks and scores.get(n, 0.0) > -900)]
        if not valid_nums:
            valid_nums = list(digit_buttons.keys())

        # Если лучший вариант оказался пустышкой (score <= -900), берем первый нормальный
        if best_num is None or best_score <= -900:
            best_num = valid_nums[0] if valid_nums else 1
        elif best_score < 0.1 and valid_nums:
            best_num = valid_nums[0]

        best_btn = digit_buttons[best_num]
        raw_best = text_tracks.get(best_num, "")
        dur, size, br = parse_metadata(raw_best)
        meta_parts = []
        if dur is not None and dur > 0:
            meta_parts.append(f"{dur // 60}:{dur % 60:02d}")
        if br is not None and br > 0:
            meta_parts.append(f"{br}k")
        meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
        title_str = clean_track_title(raw_best or f"кнопка {best_num}") + meta_str

        return best_btn, f"[{best_num}] {title_str}"

    # Сценарий 2: кнопки с текстовыми названиями треков без цифр
    if titled_buttons:
        best_btn = None
        best_score = -999.0
        best_title = ""
        for b, text, _ in titled_buttons:
            score = score_match(query, text)
            if score > best_score:
                best_score = score
                best_btn = b
                best_title = text
        if best_score >= 0.25:
            return best_btn, clean_track_title(best_title)

    return None, ""


NOT_FOUND_PATTERNS = [
    r"ничего\s+не\s+найдено",
    r"не\s+найдено",
    r"ничего\s+не\s+нашлось",
    r"не\s+удалось\s+найти",
    r"по\s+запросу\s+.*ничего",
    r"трек\s+не\s+найден",
]


async def wait_result(client, bot, query, sent_msg_id):
    """Ждёт аудио от бота, реагируя быстро и нажимая нужные кнопки.

    1. Проверяет сообщения строго ПОСЛЕ отправленного запроса (min_id=sent_msg_id).
    2. Опрашивает раз в 1 сек для мгновенной реакции (без задержек).
    3. При появлении меню нажимает подходящую кнопку и сбрасывает таймер ожидания.
    4. Если бот написал, что ничего не найдено — моментально завершает поиск.
    5. Возвращает сообщение с аудио или None.
    """
    clicked = set()
    clicks_left = MAX_CLICKS
    waited = 0

    while waited < WAIT_REPLY:
        await asyncio.sleep(POLL_EVERY)
        waited += POLL_EVERY

        msgs = await client.get_messages(bot, min_id=sent_msg_id, limit=10)
        if not msgs:
            continue

        # Сортируем от самых новых к старым
        msgs_sorted = sorted(msgs, key=lambda x: x.id, reverse=True)

        for m in msgs_sorted:
            # Аудио получено
            if is_audio(m):
                return m

            # Бот ответил текстом "ничего не найдено"
            if m.text and not m.buttons:
                t_lower = m.text.lower()
                if any(re.search(pat, t_lower) for pat in NOT_FOUND_PATTERNS):
                    print("  → бот ответил: ничего не найдено")
                    return None

            # Меню с кнопками выбора
            if m.buttons and m.id not in clicked and clicks_left > 0:
                btn, desc = pick_button(m, query)
                if btn is None:
                    clicked.add(m.id)
                    continue

                try:
                    await btn.click()
                except FloodWaitError as e:
                    print(f"  флуд-лимит: ждём {e.seconds} с")
                    await asyncio.sleep(e.seconds + 1)
                    continue
                except BotResponseTimeoutError:
                    pass  # Бот может отправить аудио без ответа на callback
                except Exception as e:
                    print(f"  (нажатие кнопки: {e})")

                clicked.add(m.id)
                clicks_left -= 1
                waited = 0  # Сбрасываем таймер — даем боту время прислать аудио
                print(f"  → выбран вариант: {desc}")
                break  # Ждем аудио в следующих итерациях

    return None


async def send_to_channel(client, channel, media, caption):
    """Публикует аудио в канал, пережидая флуд-лимиты."""
    while True:
        try:
            return await client.send_file(channel, media, caption=caption)
        except FloodWaitError as e:
            print(f"  флуд-лимит: ждём {e.seconds} с")
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            print(f"  ! ошибка отправки в канал: {e}")
            return None


async def main():
    if API_ID == 1234567 or API_HASH == "your_api_hash_here":
        sys.exit("Заполните API_ID, API_HASH и PHONE в начале скрипта.")

    tracks = load_tracks()
    done = load_progress()
    pending = [t for i, t in enumerate(tracks) if i not in done]
    print(f"Всего треков: {len(tracks)} | готово: {len(done)} | осталось: {len(pending)}")

    if not pending:
        print("Всё уже загружено. Если нужно заново — удалите done.json.")
        return

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start(phone=PHONE)

    bot = await client.get_entity(MUSIC_BOT)
    channel = await client.get_entity(CHANNEL)

    failed = []
    processed = 0
    # Загружаем список снизу вверх (инвертированный порядок):
    # в канале новые сообщения оказываются внизу, а Telegram при
    # последовательном воспроизведении идёт от последнего загруженного
    # к первому — так порядок прослушивания совпадёт с порядком плейлиста.
    for i, track in reversed(list(enumerate(tracks))):
        if i in done:
            continue
        processed += 1
        print(f"[{processed}/{len(pending)}] {track}")

        # 1. отправляем запрос боту
        try:
            sent_msg = await client.send_message(bot, track)
        except FloodWaitError as e:
            print(f"  флуд-лимит: ждём {e.seconds} с")
            await asyncio.sleep(e.seconds + 1)
            sent_msg = await client.send_message(bot, track)

        # 2. ждём аудио (сами нажимаем кнопки выбора варианта)
        try:
            audio_msg = await wait_result(client, bot, track, sent_msg.id)
        except FloodWaitError as e:
            print(f"  флуд-лимит: ждём {e.seconds} с")
            await asyncio.sleep(e.seconds + 1)
            audio_msg = None

        # 3. публикуем в канал
        if audio_msg is not None:
            res = await send_to_channel(client, channel, audio_msg, track)
            if res:
                done.add(i)
                save_progress(done)
                print("  OK")
            else:
                failed.append(track)
                print("  ОШИБКА ПУБЛИКАЦИИ")
        else:
            failed.append(track)
            print("  НЕ НАЙДЕНО (см. failed.txt)")

        await asyncio.sleep(PAUSE_BETWEEN)

    if failed:
        with open(FAILED_FILE, "a", encoding="utf-8") as f:
            for t in failed:
                f.write(t + "\n")

    print(f"\nГотово: {len(done)} из {len(tracks)} загружено, ошибок: {len(failed)}")
    if failed:
        print(f"Треки без результата записаны в {FAILED_FILE}. "
              "Удалите их из done.json и запустите скрипт снова, чтобы повторить.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
