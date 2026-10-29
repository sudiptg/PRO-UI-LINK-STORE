"""
👑 PANEL - Admin Panel ka hub: home, help, settings, backup, cancel.
Pehle jo bhi command the (addch, fsub, reqtime, broadcast...) ab sab yahin ke buttons me hain.
"""
import config
import helper_func as hf
import ui
from bot import route, clear_state
from database.database import db
from database import tgbackup
from ui import B, lbl, esc

EXPIRY_CHOICES = [60, 180, 300, 600, 900, 1800, 3600]


def home_rows():
    return [
        [B(lbl("channels", "📺"), cb="a:ch:L:0"), B(lbl("links", "🔗"), cb="a:lk:H")],
        [B(lbl("force-sub", "📢"), cb="a:fs:V"), B(lbl("approve", "✅"), cb="a:ap:G")],
        [B(lbl("broadcast", "📣"), cb="a:bc:P"), B(lbl("stats", "📊"), cb="a:st:V")],
        [B(lbl("admins", "👑"), cb="a:ad:V"), B(lbl("brand", "🏷️"), cb="a:br:V")],
        [B(lbl("ban", "🚫"), cb="a:bn:V"), B(lbl("settings", "⚙️"), cb="a:se:V")],
        [B(lbl("backup", "💾"), cb="a:bk:V"), B(lbl("health", "❤️"), cb="a:st:H")],
        [B(lbl("help", "📖"), cb="a:hp"), ui.back_btn("home")],
    ]


async def home_text():
    tot, act, _ = await db.count_users()
    chs = len(db.channels)
    return ("<b>›› 👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n\n"
            "<blockquote>"
            f"• <b>👥 ᴜsᴇʀs:</b> <code>{tot}</code>\n"
            f"• <b>📺 ᴄʜᴀɴɴᴇʟs:</b> <code>{chs}</code>   <b>📢 ꜰsᴜʙ:</b> <code>{len(db.fsub)}</code>\n"
            f"• <b>💾 ʙᴀᴄᴋᴜᴘ:</b> {esc(tgbackup.status())}"
            "</blockquote>" + db.get_brand_footer())


@route("a:home")
async def cb_home(cb, parts):
    clear_state(cb["from"]["id"])
    await ui.show(cb["message"], await home_text(), home_rows())


@route("a:cx")
async def cb_cancel(cb, parts):
    clear_state(cb["from"]["id"])
    await ui.show(cb["message"], await home_text(), home_rows())


@route("a:hp")
async def cb_help(cb, parts):
    await ui.show(cb["message"], config.HELP + db.get_brand_footer(), [[ui.back_btn("a:home"), ui.close_btn()]])


# ================================================================ settings
def settings_view():
    cur = db.get_setting("link_expiry", 300)
    rows, row = [], []
    for s in EXPIRY_CHOICES:
        mark = "✅ " if s == cur else ""
        row.append(B(f"• {mark}{ui.sc(ui.human(s))} •", cb=f"a:se:E:{s}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    wd = db.get_setting("welcome_dm", config.APPROVED == "on")
    sm = db.get_setting("daily_summary", True)
    rows.append([B(lbl(f"welcome dm: {'on' if wd else 'off'}", "💌"), cb="a:se:W")])
    rows.append([B(lbl(f"daily summary: {'on' if sm else 'off'}", "🗞️"), cb="a:se:S")])
    rows.append([ui.back_btn("a:home")])
    text = ("<b>›› ⚙️ sᴇᴛᴛɪɴɢs</b>\n\n"
            "<blockquote>"
            f"• <b>⏱️ ʟɪɴᴋ ᴇxᴘɪʀʏ (ᴀʟʟ ᴄʜᴀɴɴᴇʟs):</b> <code>{ui.human(cur)}</code>\n"
            "  ᴘᴇʀ-ᴄʜᴀɴɴᴇʟ ᴇxᴘɪʀʏ ᴄʜᴀɴɴᴇʟs → ᴄʜᴀɴɴᴇʟ ᴅᴇᴛᴀɪʟ ᴍᴇ.\n"
            f"• <b>💌 ᴡᴇʟᴄᴏᴍᴇ ᴅᴍ ᴀғᴛᴇʀ ᴀᴘᴘʀᴏᴠᴇ:</b> <code>{'ON' if wd else 'OFF'}</code>\n"
            f"• <b>🗞️ ᴅᴀɪʟʏ sᴜᴍᴍᴀʀʏ ᴛᴏ ᴏᴡɴᴇʀ:</b> <code>{'ON' if sm else 'OFF'}</code>"
            "</blockquote>")
    return text, rows


@route("a:se")
async def cb_settings(cb, parts):
    act = parts[2] if len(parts) > 2 else "V"
    if act == "E":
        await db.set_setting("link_expiry", int(parts[3]))
    elif act == "W":
        await db.set_setting("welcome_dm", not db.get_setting("welcome_dm", config.APPROVED == "on"))
    elif act == "S":
        await db.set_setting("daily_summary", not db.get_setting("daily_summary", True))
    text, rows = settings_view()
    await ui.show(cb["message"], text, rows)


# ================================================================ backup
def backup_view(note=""):
    text = ("<b>›› 💾 ʙᴀᴄᴋᴜᴘ (ᴛᴇʟᴇɢʀᴀᴍ ᴄʜᴀɴɴᴇʟ)</b>\n\n"
            "<blockquote>"
            f"• <b>ᴄʜᴀɴɴᴇʟ:</b> <code>{config.BACKUP_CHANNEL or 'NOT SET'}</code>\n"
            f"• <b>sᴛᴀᴛᴜs:</b> {esc(tgbackup.status())}\n"
            f"• <b>ʟᴏᴄᴀʟ ᴅʙ:</b> <code>{db.size_kb()} KB</code>"
            "</blockquote>\n"
            "<i>ɪᴍᴘᴏʀᴛᴀɴᴛ ᴄʜᴀɴɢᴇs ᴀʀᴇ sᴀᴠᴇᴅ ɪɴ ~10 sᴇᴄ, ᴍɪɴᴏʀ ᴏɴᴇs (ᴜsᴇʀs, ᴄʟɪᴄᴋs) ᴇᴠᴇʀʏ ~4 ᴍɪɴ.</i>")
    if note:
        text += f"\n\n<blockquote>{note}</blockquote>"
    rows = [[B(lbl("backup now", "💾"), cb="a:bk:N")],
            [B(lbl("download copy", "📥"), cb="a:bk:C")],
            [B(lbl("restore", "♻️"), cb="a:bk:R")]]
    if config.DB_URI or config.EXTRA_DB_URIS:
        rows.append([B(lbl("import mongo", "🚚"), cb="a:bk:M")])
    rows.append([ui.back_btn("a:home")])
    return text, rows


@route("a:bk", owner=True, late=True)
async def cb_backup(cb, parts):
    msg = cb["message"]
    act = parts[2] if len(parts) > 2 else "V"
    note = ""
    if act == "V":
        await ui.answer(cb["id"])
    elif act == "N":
        await ui.answer(cb["id"], "⏳ Backup le raha hoon...")
        ok = await tgbackup.backup_now(force=True)
        note = "✅ ʙᴀᴄᴋᴜᴘ ᴅᴏɴᴇ" if ok else f"❌ ʙᴀᴄᴋᴜᴘ ꜰᴀɪʟ: {esc(tgbackup.STATE['err'][:120])}"
    elif act == "C":
        await ui.answer(cb["id"], "📥 File bhej raha hoon...")
        try:
            await tgbackup.send_copy_to(msg["chat"]["id"])
            note = "📥 ꜰɪʟᴇ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴅᴍ"
        except Exception as e:      # noqa
            note = f"❌ {esc(str(e)[:120])}"
    elif act == "R":
        await ui.answer(cb["id"])
        return await ui.show(msg, "<b>›› ♻️ ʀᴇsᴛᴏʀᴇ</b>\n\n<blockquote>ᴛʜᴇ ᴄᴜʀʀᴇɴᴛ ᴅᴀᴛᴀ ᴡɪʟʟ ʙᴇ ʀᴇᴘʟᴀᴄᴇᴅ ʙʏ ᴛʜᴇ ʟᴀᴛᴇsᴛ ʙᴀᴄᴋᴜᴘ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ. "
                                  "ᴀɴʏᴛʜɪɴɢ ᴀᴅᴅᴇᴅ ᴀғᴛᴇʀ ᴛʜᴀᴛ ʙᴀᴄᴋᴜᴘ ᴄᴀɴ ʙᴇ ʟᴏsᴛ. ᴀʀᴇ ʏᴏᴜ sᴜʀᴇ?</blockquote>",
                             ui.confirm_rows("a:bk:RY", "a:bk:V", "yes, restore"))
    elif act == "RY":
        await ui.answer(cb["id"], "⏳ Restore ho raha hai...")
        ok, info = await tgbackup.restore_now()
        note = ("✅ " if ok else "❌ ") + esc(info)
    elif act == "M":
        await ui.answer(cb["id"], "⏳ Mongo se copy ho raha hai...")
        from database import migrate_mongo
        note = esc(await migrate_mongo.run(force=True) or "Mongo set nahi hai")
    text, rows = backup_view(note)
    await ui.show(msg, text, rows)
