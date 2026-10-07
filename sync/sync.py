"""Watch a public Yandex Music playlist and mirror it to a Telegram channel.

Each channel post is the artist, the title, and the official track link.
Audio files are not downloaded or uploaded.
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOCK_PATH = ROOT / "sync.lock"
LOG_PATH = ROOT / "sync.log"
API_BASE = "https://api.music.yandex.net"
PAGE_SIZE = 100
TRACK_BATCH = 40
SEND_PAUSE_SECONDS = 1.1

log = logging.getLogger("ya-synch")


class SyncError(RuntimeError):
    pass


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config = json.load(handle)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("telegram_bot_token") or ""
    config["telegram_bot_token"] = token.strip()
    config["telegram_channel"] = str(config.get("telegram_channel") or "").strip()
    config["playlist_url"] = str(config.get("playlist_url") or "").strip()
    config["poll_minutes"] = max(1, int(config.get("poll_minutes") or 10))
    if not config["playlist_url"] or not config["telegram_channel"]:
        raise SyncError("В config.json нужны playlist_url и telegram_channel.")
    return config


def playlist_uuid(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2 or parts[0] != "playlists" or not parts[1]:
        raise SyncError("Не удалось прочитать UUID плейлиста из ссылки.")
    return parts[1]


def http_json(url: str, payload: dict | None = None, attempts: int = 4) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": "ya-synch"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            last_error = SyncError(f"HTTP {error.code}: {body[:500]}")
            if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                raise last_error from error
        except urllib.error.URLError as error:
            last_error = SyncError(str(error))
            if attempt + 1 == attempts:
                raise last_error from error
        time.sleep(2**attempt)
    raise last_error or SyncError("request failed")


def fetch_stubs(uuid: str) -> list[dict]:
    seen: dict[str, dict] = {}
    page = 0
    total = None
    while page < 100:
        query = urllib.parse.urlencode(
            {"page": page, "page-size": PAGE_SIZE, "rich-tracks": "false"}
        )
        payload = http_json(f"{API_BASE}/playlist/{urllib.parse.quote(uuid)}?{query}")
        result = payload.get("result") or {}
        pager = result.get("pager") or {}
        total = int(pager.get("total") or 0)
        items = result.get("tracks") or []
        if not items:
            break
        for item in items:
            track_id = item.get("id")
            album_id = item.get("albumId")
            if track_id is None or album_id is None:
                continue
            key = f"{track_id}:{album_id}"
            seen.setdefault(key, item)
        page += 1
        if page * PAGE_SIZE >= total:
            break
    if total is None:
        raise SyncError("Яндекс Музыка не вернула плейлист.")
    log.info("playlist %s: %s tracks in response, %s listed", uuid, len(seen), total)
    return list(seen.values())


def fetch_metadata(stubs: list[dict]) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    ids = [f"{item['id']}:{item['albumId']}" for item in stubs]
    for offset in range(0, len(ids), TRACK_BATCH):
        batch = ids[offset : offset + TRACK_BATCH]
        query = urllib.parse.urlencode(
            {"track-ids": ",".join(batch), "with-positions": "false"}
        )
        payload = http_json(f"{API_BASE}/tracks?{query}")
        for track in payload.get("result") or []:
            if track and track.get("id") is not None:
                meta[str(track["id"])] = track
    return meta


def track_record(stub: dict, meta: dict | None) -> dict:
    track_id = stub["id"]
    album_id = stub["albumId"]
    artists = []
    title = f"Трек {track_id}"
    if meta:
        artists = [artist.get("name", "") for artist in meta.get("artists") or [] if artist.get("name")]
        if meta.get("title"):
            title = meta["title"]
    artist = ", ".join(artists)
    url = f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
    text = f"{artist} — {title}\n{url}" if artist else f"{title}\n{url}"
    return {
        "key": f"{track_id}:{album_id}",
        "timestamp": stub.get("timestamp") or "",
        "text": text,
    }


def load_tracks(playlist_url: str) -> list[dict]:
    stubs = fetch_stubs(playlist_uuid(playlist_url))
    metadata = fetch_metadata(stubs)
    records = [
        track_record(stub, metadata.get(str(stub["id"])))
        for stub in stubs
    ]
    records.sort(key=lambda item: (item["timestamp"], item["key"]))
    return records


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    with STATE_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    temporary = STATE_PATH.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    temporary.replace(STATE_PATH)


class Telegram:
    def __init__(self, token: str, channel: str) -> None:
        self.token = token
        self.channel = channel

    def call(self, method: str, payload: dict, attempts: int = 5) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        last_description = ""
        for attempt in range(attempts):
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {"ok": False, "error_code": error.code, "description": body[:500]}
            if data.get("ok"):
                return data["result"]
            description = str(data.get("description") or data)
            last_description = description
            error_code = int(data.get("error_code") or 0)
            if error_code == 401:
                raise SyncError("Токен бота недействителен. Проверьте его в @BotFather.")
            if error_code == 429:
                retry_after = int((data.get("parameters") or {}).get("retry_after") or 5)
                time.sleep(retry_after + 1)
                continue
            if error_code >= 500 and attempt + 1 < attempts:
                time.sleep(2**attempt)
                continue
            raise SyncError(description)
        raise SyncError(last_description or "Telegram не ответил.")

    def check(self) -> None:
        me = self.call("getMe", {})
        log.info("bot @%s", me.get("username"))
        self.call("getChat", {"chat_id": self.channel})

    def send(self, text: str) -> int:
        result = self.call(
            "sendMessage",
            {
                "chat_id": self.channel,
                "text": text,
                "disable_web_page_preview": False,
            },
        )
        return int(result["message_id"])

    def edit(self, message_id: int, text: str) -> None:
        self.call(
            "editMessageText",
            {
                "chat_id": self.channel,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": False,
            },
        )

    def delete(self, message_id: int) -> None:
        self.call("deleteMessage", {"chat_id": self.channel, "message_id": message_id})


def missing_message(error: SyncError) -> bool:
    text = str(error).lower()
    return "message to delete not found" in text or "message to edit not found" in text or "message_id_invalid" in text


def sync_once(config: dict, telegram: Telegram | None) -> tuple[int, int, int]:
    tracks = load_tracks(config["playlist_url"])
    current = {track["key"]: track for track in tracks}
    state = load_state()
    added = 0
    removed = 0
    updated = 0

    if telegram is None:
        return len(tracks), 0, 0

    for key in list(state):
        if key in current:
            continue
        message_id = int(state[key]["message_id"])
        try:
            telegram.delete(message_id)
        except SyncError as error:
            if not missing_message(error):
                raise
        del state[key]
        save_state(state)
        removed += 1
        time.sleep(SEND_PAUSE_SECONDS)

    for track in tracks:
        saved = state.get(track["key"])
        if saved is None:
            message_id = telegram.send(track["text"])
            state[track["key"]] = {"message_id": message_id, "text": track["text"]}
            save_state(state)
            added += 1
            if added == 1 or added % 25 == 0:
                log.info("posted %s", added)
            time.sleep(SEND_PAUSE_SECONDS)
            continue
        if saved.get("text") == track["text"]:
            continue
        try:
            telegram.edit(int(saved["message_id"]), track["text"])
        except SyncError as error:
            if not missing_message(error):
                raise
            message_id = telegram.send(track["text"])
            saved["message_id"] = message_id
        saved["text"] = track["text"]
        save_state(state)
        updated += 1
        time.sleep(SEND_PAUSE_SECONDS)

    log.info("sync done: %s in playlist, added %s, removed %s, updated %s", len(tracks), added, removed, updated)
    return added, removed, updated


def acquire_lock() -> None:
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
        except (OSError, ValueError):
            LOCK_PATH.unlink(missing_ok=True)
        else:
            raise SystemExit(f"Синхронизация уже запущена, процесс {pid}.")
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")

    def release() -> None:
        try:
            if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
                LOCK_PATH.unlink()
        except OSError:
            pass

    atexit.register(release)


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    log.handlers.clear()
    log.addHandler(file_handler)
    log.addHandler(stream_handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Синхронизация плейлиста Яндекс Музыки в Telegram-канал")
    parser.add_argument("--once", action="store_true", help="Один проход вместо постоянного ожидания")
    parser.add_argument("--dry-run", action="store_true", help="Только прочитать плейлист, ничего не публиковать")
    args = parser.parse_args()
    setup_logging()
    config = load_config()
    if args.dry_run:
        tracks = load_tracks(config["playlist_url"])
        summary = {
            "count": len(tracks),
            "oldest": [track["text"].split("\n", 1)[0] for track in tracks[:3]],
            "newest": [track["text"].split("\n", 1)[0] for track in tracks[-3:]],
        }
        (ROOT / "dry-run.txt").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("dry-run tracks: %s", len(tracks))
        return

    token = config["telegram_bot_token"]
    if not token:
        raise SystemExit(
            "Нет токена бота. Создайте бота в @BotFather, добавьте его администратором "
            f"канала {config['telegram_channel']} с правом публиковать сообщения "
            "и впишите токен в sync/config.json, поле telegram_bot_token."
        )

    acquire_lock()
    telegram = Telegram(token, config["telegram_channel"])
    try:
        telegram.check()
    except SyncError as error:
        text = str(error).lower()
        if any(part in text for part in ("forbidden", "not a member", "administrator", "chat not found", "have no rights")):
            raise SystemExit(
                "Бот не может писать в канал. Добавьте его администратором "
                f"{config['telegram_channel']} с правом публиковать сообщения."
            ) from error
        raise
    while True:
        try:
            sync_once(config, telegram)
        except SyncError as error:
            log.error("%s", error)
            if "токен" in str(error).lower():
                raise SystemExit(1) from error
        except Exception:
            log.exception("sync failed")
        if args.once:
            break
        time.sleep(config["poll_minutes"] * 60)


if __name__ == "__main__":
    main()
