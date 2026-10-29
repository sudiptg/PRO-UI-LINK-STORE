"""
☁️ TGBACKUP - database ki copy tumhare PRIVATE Telegram channel me (yahi tumhara "database channel").

Render free par disk restart / deploy par mit jati hai. Isliye:
  - Zaroori badlav (channel add, setting, admin...) ~10 sec me channel me save.
  - Chhote badlav (naye users, clicks) har BACKUP_EVERY sec me.
  - DB ki compressed file channel me EK hi message me update hoti hai (naya message nahi banta) aur PIN rehta hai.
  - Bot start hote hi pinned backup dekhta hai aur local se naya ho to restore karta hai.
  - Band hone (deploy / restart) se pehle aakhri backup bhi leta hai.
"""
import asyncio
import re
import time

import config
import ui
from database.database import db, local_last_write, restore_file
from ui import TgError

STATE = {"msg_id": 0, "last": 0, "ok": None, "err": "", "size": 0, "verified": False}
MAX_BYTES = 19 * 1024 * 1024          # Bot API 20 MB se badi file download nahi karne deta
MIN_GAP = 8                           # do backup ke beech kam se kam itne second
_lock = None
NAME = "linkstore.db.gz"


def _ts_of(caption):
    m = re.search(r"ts=(\d+)", caption or "")
    return int(m.group(1)) if m else 0


async def _caption(ts):
    tot, act, _ = await db.count_users()
    return f"link-store backup | ts={ts} | users={tot} | channels={len(db.channels)} | do not delete (pinned)"


async def _find_remote():
    """Channel ka pinned backup. -> (message_id, file_id, ts) ya None"""
    chat = await ui.api("getChat", chat_id=config.BACKUP_CHANNEL, _retries=2)
    pm = chat.get("pinned_message") or {}
    doc = pm.get("document")
    if not doc:
        return None
    return pm["message_id"], doc["file_id"], _ts_of(pm.get("caption"))


async def restore_if_needed():
    """db.init se PEHLE bulao. Text me result lautata hai (log ke liye).
    STATE["verified"]=True tabhi hota hai jab channel ka backup sahi se check ho gaya
    (warna galti se purana achha backup khali DB se overwrite ho sakta tha)."""
    if not config.BACKUP_CHANNEL:
        return "backup channel not set - skipping restore"
    try:
        remote = await _find_remote()
    except TgError as e:
        return f"backup channel unreachable ({e}) - bot ko channel me admin banao"
    if not remote:
        STATE["verified"] = True
        return "no backup found in channel (first run?)"
    msg_id, file_id, rts = remote
    STATE["msg_id"] = msg_id
    lts = local_last_write()
    if lts and lts >= rts:
        STATE["verified"] = True
        return f"local db is up to date (local {lts} >= backup {rts})"
    try:
        data = await ui.download_file(file_id)
        ok = restore_file(data)
    except Exception as e:      # noqa
        return f"restore failed: {type(e).__name__}: {e}"
    if not ok:
        return "backup file was corrupt - not restored"
    STATE["last"] = rts
    STATE["verified"] = True
    return f"restored from channel backup (ts={rts})"


async def restore_now():
    """Panel ke 'Restore' button se: channel ke backup se abhi ka data badal do. -> (ok, text)"""
    if not config.BACKUP_CHANNEL:
        return False, "BACKUP_CHANNEL set nahi hai"
    try:
        remote = await _find_remote()
        if not remote:
            return False, "channel me koi backup nahi mila"
        msg_id, file_id, rts = remote
        data = await ui.download_file(file_id)
    except Exception as e:      # noqa
        return False, f"download fail: {e}"
    # pehle jaanch lo (galat file se live DB kharab na ho)
    import gzip
    import os
    import sqlite3
    import tempfile
    try:
        raw = gzip.decompress(data)
        tmp = os.path.join(tempfile.gettempdir(), "restore_check.db")
        with open(tmp, "wb") as f:
            f.write(raw)
        cn = sqlite3.connect(tmp)
        good = cn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        cn.close()
        os.remove(tmp)
        if not good:
            return False, "backup file kharab hai - restore nahi kiya"
    except Exception as e:      # noqa
        return False, f"backup file padh nahi paya: {e}"
    async with _get_lock():
        await db.close()
        ok = restore_file(data)
        await db.reopen()
        if not ok:
            return False, "restore fail (purana data wapas chalu)"
    STATE.update(msg_id=msg_id, last=rts, verified=True)
    return True, f"restore ho gaya (backup ts={rts})"


def _get_lock():
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def backup_now(force=False):
    """True = backup ho gaya (ya zaroorat nahi thi). False = fail."""
    if not config.BACKUP_CHANNEL:
        return False
    if not STATE["verified"]:
        # channel ka purana backup check nahi hua - overwrite nahi karenge (data bachane ke liye)
        STATE.update(ok=False, err="channel ka backup verify nahi hua (bot admin hai?)")
        return False
    async with _get_lock():
        if not force and not db.dirty and STATE["msg_id"]:
            return True
        db.clear_dirty()                       # snapshot ke dauran naya badlav fir se dirty karega
        try:
            data = await db.snapshot_gz()
            if len(data) > MAX_BYTES:
                raise RuntimeError(f"backup too big ({len(data) // 1024} KB)")
            ts = int(await db.get_meta("last_write", 0))
            cap = await _caption(ts)
            done = False
            if STATE["msg_id"]:
                try:
                    await ui.edit_document(config.BACKUP_CHANNEL, STATE["msg_id"], NAME, data, cap)
                    done = True
                except TgError as e:
                    if e.not_modified:
                        done = True
                    else:
                        print(f"backup edit failed, sending new: {e}")
            if not done:
                m = await ui.send_document(config.BACKUP_CHANNEL, NAME, data, cap)
                old = STATE["msg_id"]
                STATE["msg_id"] = m["message_id"]
                try:
                    await ui.api("pinChatMessage", chat_id=config.BACKUP_CHANNEL,
                                 message_id=m["message_id"], disable_notification=True, _retries=1)
                except TgError as e:
                    print(f"pin failed (bot ko Pin/Edit right do): {e}")
                if old:
                    await ui.delete(config.BACKUP_CHANNEL, old)
            STATE.update(last=int(time.time()), ok=True, err="", size=len(data) // 1024)
            return True
        except Exception as e:        # noqa
            db.touch(True)
            STATE.update(ok=False, err=f"{type(e).__name__}: {e}"[:200])
            print(f"backup error: {STATE['err']}")
            return False


async def send_copy_to(chat_id):
    """Backup file ki ek copy kisi ko (owner ke DM me) bhejo."""
    data = await db.snapshot_gz()
    return await ui.send_document(chat_id, NAME, data, "💾 link-store backup copy (safe jagah rakho)")


def status():
    if not config.BACKUP_CHANNEL:
        return "❌ not set"
    if STATE["ok"] is False:
        return f"❌ failed ({STATE['err'][:50]})"
    if not STATE["last"]:
        return "⏳ pending"
    ago = int(time.time() - STATE["last"])
    when = f"{ago}s ago" if ago < 120 else f"{ago // 60}m ago"
    return f"✅ {when} ({STATE['size']} KB)"


async def loop():
    """Har 5 sec dekho: zaroori badlav 8 sec purana ho gaya? ya chhota badlav BACKUP_EVERY se purana?"""
    first = True
    await asyncio.sleep(15)
    while True:
        try:
            if config.BACKUP_CHANNEL and not STATE["verified"]:
                # shuru me channel nahi mila tha - dobara koshish
                try:
                    remote = await _find_remote()
                    if not remote:
                        STATE["verified"] = True
                    else:
                        ok, msg = await restore_now()
                        print(f"late restore: {msg}")
                        await ui.notify_owner(f"♻️ <b>Backup channel ab mila</b>: {ui.esc(msg)}")
                except Exception as e:      # noqa
                    print(f"backup verify retry: {e}")
                    await asyncio.sleep(55)
            now = time.time()
            since = now - (STATE["last"] or 0)
            due = False
            if first and not STATE["msg_id"]:
                due = True
            elif db.dirty_hi and now - db.dirty_hi >= MIN_GAP and since >= MIN_GAP:
                due = True
            elif db.dirty_lo and since >= config.BACKUP_EVERY:
                due = True
            if due:
                await backup_now(force=first and not STATE["msg_id"])
            first = False
        except Exception as e:      # noqa
            print(f"backup loop: {e}")
        await asyncio.sleep(5)
