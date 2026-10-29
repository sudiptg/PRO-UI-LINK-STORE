"""
👤 START - /start, link delivery (normal / request / genlink), force-sub check, about, channels.
Public user ka poora kaam yahin. Bahut tez: RAM lookups + ek hi message.
"""
import asyncio
import time
from collections import defaultdict

import config
import helper_func as hf
import ui
from bot import route
from database.database import db
from ui import B, TgError, lbl, sc, esc

_locks = defaultdict(asyncio.Lock)          # (channel, is_req) -> lock
_warn_ts = {}


def home_rows(uid):
    rows = [[B(lbl("about", "ℹ️"), cb="about"), B(lbl("channels", "📢"), cb="channels")]]
    if hf.is_admin(uid):
        rows.append([B(lbl("admin panel", "👑"), cb="a:home")])
    rows.append([ui.close_btn()])
    return rows


def home_text():
    return config.START_MSG + db.get_brand_footer()


async def send_home(chat_id, uid):
    await ui.send(chat_id, home_text(), home_rows(uid), photo=config.START_PIC or None)


# ================================================================ /start
async def start(m, payload):
    u = m["from"]
    uid = u["id"]
    chat_id = m["chat"]["id"]

    if db.is_banned(uid) and not hf.is_admin(uid):
        return await _safe(ui.send, chat_id, "<b><blockquote>🚫 ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ.</blockquote></b>")

    spam = hf.spam_check(uid) if not hf.is_admin(uid) else 0
    if spam:
        if spam == 1:
            await _safe(ui.send, chat_id, "<b><blockquote>⏳ ʏᴏᴜ ᴀʀᴇ ᴛᴇᴍᴘᴏʀᴀʀɪʟʏ ʀᴇsᴛʀɪᴄᴛᴇᴅ ᴅᴜᴇ ᴛᴏ sᴘᴀᴍᴍɪɴɢ. "
                                           "ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.</blockquote></b>")
        return

    try:
        await db.add_user(uid)
    except Exception as e:      # noqa
        print(f"add_user: {e}")

    fsub = db.get_fsub_channels()
    if fsub and not hf.is_admin(uid):
        ok, _, rows = await hf.check_subscription_status(uid, fsub, payload=payload)
        if not ok:
            try:
                text = config.FORCE_MSG.format(first=u.get("first_name", ""), last=u.get("last_name", ""),
                                               username=("@" + u["username"]) if u.get("username") else None,
                                               mention=hf.mention(u), id=uid)
            except Exception:       # noqa
                text = config.FORCE_MSG
            return await _safe(ui.send, chat_id, text + db.get_brand_footer(), rows, photo=config.FORCE_PIC or None)

    if not payload:
        return await _safe(send_home, chat_id, uid)

    await deliver(chat_id, payload)


async def _safe(fn, *a, **kw):
    try:
        return await fn(*a, **kw)
    except TgError as e:
        if not e.user_gone:
            print(f"send error: {e}")
    except Exception as e:      # noqa
        print(f"send error: {type(e).__name__}: {e}")


# ================================================================ link delivery
def _mins(secs):
    if secs % 60 == 0:
        n = secs // 60
        return f"{n} minute" + ("s" if n != 1 else "")
    return f"{secs} seconds"


async def _revoke(cid, link):
    try:
        await ui.api("revokeChatInviteLink", chat_id=cid, invite_link=link, _retries=1)
    except TgError:
        pass


ui.HANDLERS["revoke"] = _revoke


async def get_invite(cid, is_req):
    """Channel ka invite link: 4 min tak sab ko wahi (FloodWait se bachne ke liye). -> (link, expiry_secs)"""
    expiry = db.get_link_expiry(cid)
    reuse = max(15, min(240, expiry - 60))
    async with _locks[(cid, is_req)]:
        cached = db.get_current_invite_link(cid, is_req)
        if cached and time.time() - cached[1] < reuse:
            return cached[0], expiry
        params = {"chat_id": cid, "expire_date": int(time.time()) + expiry}
        if is_req:
            params["creates_join_request"] = True
        inv = await ui.api("createChatInviteLink", **params)
        link = inv["invite_link"]
        db.save_invite_link(cid, link, is_req)
        ui.schedule(expiry + 5, "revoke", cid, link)           # telegram ki list saaf rakhne ke liye
        return link, expiry


async def deliver(chat_id, payload):
    is_req = payload.startswith("req_")
    token = payload[4:] if is_req else payload
    bad = "<b><blockquote>⚠️ ɪɴᴠᴀʟɪᴅ ᴏʀ ᴇxᴘɪʀᴇᴅ ɪɴᴠɪᴛᴇ ʟɪɴᴋ.</blockquote></b>"
    try:
        cid = await db.resolve_token(token, is_req)
        if not cid:
            return await _safe(ui.send, chat_id, bad)

        original = await db.get_original_link(cid)
        if original:                                  # /genlink wala link
            db.bump_click(cid)
            text = "<b><blockquote>ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ:</blockquote></b>" + db.get_brand_footer()
            try:
                return await ui.send(chat_id, text, [[B(lbl("proceed to link"), url=original)]])
            except TgError as e:
                if e.code == 400 and not e.user_gone:   # button ke liye link theek nahi: text me bhejo
                    return await ui.send(chat_id, text + f"\n\n{esc(original)}")
                raise

        link, expiry = await get_invite(cid, is_req)
        db.bump_click(cid)
        btn = lbl("request to join") if is_req else lbl("join channel")
        text = ("<b><blockquote>ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ:</blockquote></b>\n"
                f"<b><blockquote><u>ɴᴏᴛᴇ: ᴛʜɪs ʟɪɴᴋ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴇxᴘɪʀᴇ ɪɴ {sc(_mins(expiry))}.</u></blockquote></b>"
                + db.get_brand_footer())
        sent = await ui.send(chat_id, text, [[B(btn, url=link)]])
        ui.schedule_delete(chat_id, sent["message_id"], expiry)     # link expire ke saath message bhi hat jaye
    except TgError as e:
        if e.user_gone:
            return
        print(f"deliver error: {e}")
        if e.chat_gone or e.no_rights or e.code == 400:
            cid_ = locals().get("cid")
            if cid_ and time.time() - _warn_ts.get(cid_, 0) > 900:
                _warn_ts[cid_] = time.time()
                await ui.notify_owner(f"⚠️ <b>Link nahi ban pa raha</b>\n<blockquote>{esc(hf.chat_title(cid_))} "
                                      f"(<code>{cid_}</code>)\n{esc(e.desc[:120])}</blockquote>\n"
                                      "Bot ko channel me admin banao (Invite Users via Link right).")
        await _safe(ui.send, chat_id, bad)
    except Exception as e:      # noqa
        print(f"deliver error: {type(e).__name__}: {e}")
        await _safe(ui.send, chat_id, bad)


# ================================================================ buttons (public)
def _back_close(cb="home"):
    return [[B(lbl("back", "⬅️"), cb=cb), ui.close_btn()]]


@route("home")
@route("start")
async def cb_home(cb, parts):
    await ui.show(cb["message"], home_text(), home_rows(cb["from"]["id"]), photo=config.START_PIC or None)


@route("about")
async def cb_about(cb, parts):
    await ui.show(cb["message"], config.ABOUT_TXT + db.get_brand_footer(), _back_close(), photo=config.START_PIC or None)


@route("channels")
async def cb_channels(cb, parts):
    await ui.show(cb["message"], config.CHANNELS_TXT + db.get_brand_footer(), _back_close(), photo=config.START_PIC or None)


@route("close")
async def cb_close(cb, parts):
    msg = cb["message"]
    await ui.delete(msg["chat"]["id"], msg["message_id"])


@route("check_sub", late=True)
async def cb_check_sub(cb, parts):
    uid = cb["from"]["id"]
    msg = cb["message"]
    fsub = db.get_fsub_channels()
    if not fsub:
        await ui.answer(cb["id"])
        return await ui.show(msg, "<b>✅ ɴᴏ ғᴏʀᴄᴇ-sᴜʙ ᴄʜᴀɴɴᴇʟs ᴄᴏɴғɪɢᴜʀᴇᴅ! ᴜsᴇ /start ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ.</b>", [[ui.close_btn()]])
    ok, _, rows = await hf.check_subscription_status(uid, fsub)
    if ok:
        await ui.answer(cb["id"], "✅ Verified!")
        return await ui.show(msg, "<b>✅ ʏᴏᴜ ʜᴀᴠᴇ ᴊᴏɪɴᴇᴅ ᴀʟʟ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟs! ᴄʟɪᴄᴋ ᴛʜᴇ ᴘᴏsᴛ ʟɪɴᴋ ᴏʀ ᴜsᴇ /start ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ.</b>",
                             [[ui.close_btn()]])
    await ui.answer(cb["id"], "⚠️ Please join all required channels first!", True)
    try:
        try:
            text = config.FORCE_MSG.format(first="", last="", username=None, mention=hf.mention(cb["from"]), id=uid)
        except Exception:       # noqa
            text = config.FORCE_MSG
        await ui.show(msg, text + db.get_brand_footer(), rows, photo=config.FORCE_PIC if ui.has_media(msg) else None)
    except Exception:       # noqa
        pass
