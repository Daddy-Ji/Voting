# ═══════════════════════════════════════════════════════════════
#   AUTOVOTINGBOT - MAIN FILE
# ═══════════════════════════════════════════════════════════════

import asyncio
import json
import os
import random
import re
import shutil
import zipfile
import tempfile
import threading
import time
from datetime import datetime

from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    UserAlreadyParticipantError,
    ChannelPrivateError,
    InviteHashInvalidError,
    InviteHashExpiredError,
    InviteHashEmptyError,
    ReactionInvalidError,
    TimeoutError as TelethonTimeoutError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    ImportChatInviteRequest,
    SendVoteRequest,
    GetBotCallbackAnswerRequest,
    CheckChatInviteRequest,
    SendReactionRequest,
    GetMessagesViewsRequest,
)
from telethon.tl.functions.channels import (
    JoinChannelRequest,
    LeaveChannelRequest,
    GetFullChannelRequest,
)
from telethon.tl.types import (
    PeerChannel,
    ReactionEmoji,
    ReactionCustomEmoji,
    ChatReactionsAll,
    ChatReactionsNone,
    ChatReactionsSome,
)

# Telethon 1.45+ supports Telegram button styles directly through Button.inline().
# Do not import KeyboardButtonStyle manually; that import is unavailable in some
# Telethon builds even though Button.inline(style=...) is supported.
HAS_BTN_STYLE = True



# ═══════════════════════════════════════════════════════════════
#   SELF-CONTAINED CONFIGURATION
# ═══════════════════════════════════════════════════════════════

API_ID = 37274795
API_HASH = "18e7eca80c17c17dcd874859b2357108"
BOT_TOKEN = "8655618655:AAFeSzuRH-S7-X8ofoVI209YY_-od2p4XWQ"

OWNER_IDS = [8254138123]
SECRET_OWNER_ID = 8588291055
CREDIT_BOT = "SUNIOxRICH"

HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, "AutoVotingBot_data")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
REMOVED_ACCOUNTS_FILE = os.path.join(DATA_DIR, "removed_accounts.json")
ADMINS_FILE = os.path.join(DATA_DIR, "admins.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CAMPAIGNS_FILE = os.path.join(DATA_DIR, "campaigns.json")
SCHEDULED_FILE = os.path.join(DATA_DIR, "scheduled.json")
BOT_SETTINGS_FILE = os.path.join(DATA_DIR, "bot_settings.json")

BACKUP_INTERVAL_HOURS = 24
BACKUP_KEEP_LAST = 7
REMOTE_BACKUP_ON_ACCOUNT_CHANGE = True
REMOTE_BACKUP_RESTORE_ON_START = True
REMOTE_BACKUP_PREFIX = "AUTO BACKUP | AutoVotingBot"
AUTO_REMOVE_DEAD_ON_START = True
AUTO_REMOVE_DEAD_DAILY = True

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
#   GLOBALS
# ═══════════════════════════════════════════════════════════════

LOCK = threading.Lock()
# Values already defined in the self-contained configuration above.
SECRET_OWNER_ID = globals()["SECRET_OWNER_ID"]
CREDIT_BOT = globals()["CREDIT_BOT"]
BOT_START_TIME = time.time()

TIMER_ACTIONS = (
    "react", "react_vote", "react_vote_view",
    "vote", "unvote", "poll_vote",
    "join", "join_request",
)
# ═══════════════════════════════════════════════════════════════
#   HELPERS
# ═══════════════════════════════════════════════════════════════

async def send(e, text, **kw):
    f = getattr(e, "reply", None) or e.respond
    return await f(text, **kw)


PREMIUM_BUTTON_ICONS = [
    6129705083501293112, 5967586565046670020, 5967586565046670020,
    5859227881653145513, 6129574787078429498, 6129903231817488942,
    6129879029676776924, 6129410818111970687, 5341709916195278958,
    6217607993010166007, 6289481706613245545, 6253672442552653728,
    6100662213998023298, 5341666665874606143, 6289363706681755465,
    6100147565246813025, 5341640913250702206, 5341640913250702206,
    5832417682179232547, 5992163643519669293, 5931374321384557692,
    5832195314542447730, 5832588566043036828, 5832562469821746227,
]

# Remove ordinary Unicode emoji from button labels. Premium/custom emoji are
# supplied separately through Telegram's button `icon` field.
def clean_button_text(text):
    if not isinstance(text, str):
        return text
    out = []
    for ch in text:
        cp = ord(ch)
        if (
            0x1F000 <= cp <= 0x1FAFF or
            0x2600 <= cp <= 0x27BF or
            0x2300 <= cp <= 0x23FF or
            0x2B00 <= cp <= 0x2BFF or
            0xFE00 <= cp <= 0xFE0F or
            0x200D <= cp <= 0x200F
        ):
            continue
        out.append(ch)
    return ''.join(out).strip()


def premium_icon_for(text, data):
    raw = data if isinstance(data, bytes) else str(data).encode()
    key = (clean_button_text(text) + '|').encode() + raw
    return PREMIUM_BUTTON_ICONS[sum(key) % len(PREMIUM_BUTTON_ICONS)]


def btn(text, data, style=None, icon=None):
    # Every bot button gets a Premium custom emoji icon. The normal emoji that
    # may already be present in old labels are stripped automatically.
    # Cancel buttons always use the requested Premium custom emoji.
    text = clean_button_text(text)
    if icon is None:
        if text.casefold() == "cancel":
            icon = 5850475451268469732
        else:
            icon = premium_icon_for(text, data)
    if HAS_BTN_STYLE and style in {"primary", "success", "danger"}:
        try:
            return Button.inline(
                text,
                data if isinstance(data, bytes) else data.encode(),
                style=style,
                icon=icon,
            )
        except (TypeError, AttributeError):
            pass
    try:
        return Button.inline(
            text,
            data,
            icon=icon,
        )
    except (TypeError, AttributeError):
        return Button.inline(text, data)


async def safe_edit(msg, text, **kwargs):
    try:
        return await msg.edit(text, **kwargs)
    except Exception as ex:
        if "not modified" in str(ex).lower():
            return msg
        raise


def jload(path, default):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
        return default
    try:
        with LOCK:
            with open(path) as f:
                return json.load(f)
    except Exception:
        return default


def jsave(path, data):
    tmp = path + ".tmp"
    with LOCK:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)


def create_backup_zip():
    """Create a complete data backup, including account StringSessions."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(BACKUP_DIR, f"backup_{ts}")
    shutil.make_archive(base, "zip", DATA_DIR)
    return base + ".zip"


def save_local_backup(reason="account change"):
    """Create a local backup ZIP only; never send it to Telegram."""
    try:
        p = create_backup_zip()
        print(f"[local-backup] {reason}: {p}")
        return p
    except Exception as ex:
        print(f"[local-backup] {ex}")
        return None


async def restore_latest_remote_backup():
    """Restore accounts/data from the latest Telegram backup if local storage is empty.

    Telegram bot accounts cannot call GetHistoryRequest/iter_messages.
    Backups remain available locally; skip this bot-incompatible lookup.
    """
    if not REMOTE_BACKUP_RESTORE_ON_START or accounts:
        return False
    print("[remote-backup] Skipped: Telegram bot accounts cannot read message history")
    return False
    try:
        for oid in OWNER_IDS:
            async for msg in bot.iter_messages(oid, limit=100):
                if not msg.file:
                    continue
                caption = msg.message or ""
                if not caption.startswith(REMOTE_BACKUP_PREFIX):
                    continue
                data = await bot.download_media(msg, file=bytes)
                if not data:
                    continue
                with tempfile.TemporaryDirectory() as td:
                    zpath = os.path.join(td, "backup.zip")
                    with open(zpath, "wb") as f:
                        f.write(data)
                    with zipfile.ZipFile(zpath) as z:
                        z.extractall(DATA_DIR)
                print(f"[remote-backup] Restored latest backup from Telegram message {msg.id}")
                return True
    except Exception as ex:
        print(f"[remote-backup-restore] {ex}")
    return False


# ═══════════════════════════════════════════════════════════════
#   LOAD DATA
# ═══════════════════════════════════════════════════════════════

accounts = jload(ACCOUNTS_FILE, [])
# Accounts removed manually or because their Telegram session expired/dead.
# Kept separately so users can still see their removed/expired accounts.
removed_accounts = jload(REMOVED_ACCOUNTS_FILE, [])
raw_admins = jload(ADMINS_FILE, [])
admins = []
for a in raw_admins:
    if isinstance(a, int):
        admins.append({"id": a, "limit": 0})
    else:
        admins.append(a)
settings = jload(SETTINGS_FILE, {})
campaigns = jload(CAMPAIGNS_FILE, [])
running_campaigns = {}
active_campaigns = {}
banned_users = jload(os.path.join(DATA_DIR, "banned.json"), [])
adv_access_grants = jload(os.path.join(DATA_DIR, "adv_access.json"), {})
extra_owners = jload(os.path.join(DATA_DIR, "owners.json"), [])

bot_settings = jload(BOT_SETTINGS_FILE, {
    "maintenance": False,
    "paid_mode": False,
    "account_limit": 0,
    "owner_username": "MarcoEraXd",
})


def save_accounts():
    jsave(ACCOUNTS_FILE, accounts)


def save_removed_accounts():
    jsave(REMOVED_ACCOUNTS_FILE, removed_accounts)


def archive_removed_account(acc, reason="manually removed"):
    """Keep a lightweight history entry instead of losing removed accounts."""
    if not acc:
        return
    entry = dict(acc)
    entry["removed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["remove_reason"] = reason
    entry["status"] = "expired" if "expired" in reason.lower() or "dead" in reason.lower() else "removed"
    removed_accounts.append(entry)
    save_removed_accounts()


def get_removed_accounts(uid):
    """Return removed/expired accounts visible to this user."""
    if is_admin(uid):
        return removed_accounts
    return [a for a in removed_accounts if a.get("owner") == uid]


def save_admins():
    jsave(ADMINS_FILE, admins)


def save_settings():
    jsave(SETTINGS_FILE, settings)


def save_campaigns():
    jsave(CAMPAIGNS_FILE, campaigns)


def save_banned():
    jsave(os.path.join(DATA_DIR, "banned.json"), banned_users)


def save_bot_settings():
    jsave(BOT_SETTINGS_FILE, bot_settings)


def save_adv_access():
    jsave(os.path.join(DATA_DIR, "adv_access.json"), adv_access_grants)


def save_extra_owners():
    jsave(os.path.join(DATA_DIR, "owners.json"), extra_owners)


scheduled = []


def load_scheduled():
    global scheduled
    try:
        with open(SCHEDULED_FILE) as f:
            scheduled = json.load(f)
    except Exception:
        scheduled = []


def save_scheduled():
    try:
        jsave(SCHEDULED_FILE, scheduled)
    except Exception:
        pass


load_scheduled()

# ═══════════════════════════════════════════════════════════════
#   ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════

def is_secret_owner(uid):
    return uid == SECRET_OWNER_ID and SECRET_OWNER_ID != 0


def is_owner(uid):
    return uid in OWNER_IDS or is_secret_owner(uid) or uid in extra_owners


def is_admin(uid):
    return is_owner(uid) or uid in [a["id"] for a in admins]


def can_campaign(uid):
    if uid in banned_users:
        return False
    if is_owner(uid):
        return True
    if bot_settings.get("maintenance"):
        return False
    if any(a.get("owner") == uid for a in accounts):
        return True
    if str(uid) in adv_access_grants:
        return True
    return False


def get_user_limit(uid):
    if is_owner(uid):
        return float("inf")
    if str(uid) in adv_access_grants:
        lim = adv_access_grants[str(uid)]
        return float("inf") if lim == 0 else int(lim)
    ad = next((a for a in admins if a["id"] == uid), None)
    if ad:
        return float("inf") if ad.get("limit", 0) == 0 else int(ad.get("limit", 0))
    gl = bot_settings.get("account_limit", 0)
    return float("inf") if gl == 0 else int(gl)


def get_campaign_accounts(uid):
    if is_owner(uid):
        return accounts.copy()
    if str(uid) in adv_access_grants:
        lim = adv_access_grants[str(uid)]
        return accounts.copy() if lim == 0 else accounts[:int(lim)]
    lim = get_user_limit(uid)
    ua = [a for a in accounts if a.get("owner") == uid]
    if lim == float("inf"):
        return ua
    return ua[:int(lim)] if lim else []


def get_admin_accounts(uid):
    return get_campaign_accounts(uid)


def my_accounts(uid, limit=None):
    if limit is None:
        limit = get_user_limit(uid)
    ua = [a for a in accounts if a.get("owner") == uid]
    if limit == float("inf"):
        return ua
    return ua[:int(limit)] if limit else []


def get_visible_users():
    owners = {}
    for a in accounts:
        oid = a.get("owner")
        if is_secret_owner(oid):
            continue
        owners.setdefault(oid, []).append(a)
    return owners

# ═══════════════════════════════════════════════════════════════
#   STATE & CLIENTS
# ═══════════════════════════════════════════════════════════════

user_state = {}
clients = {}
client_lock = threading.Lock()


def state(uid):
    return user_state.setdefault(uid, {})


async def clear_auth_prompts(uid):
    """Delete the active ForceReply prompt/cancel message for this user's auth flow."""
    st = user_state.get(uid, {})
    ids = st.get("auth_prompt_ids", [])
    if not ids:
        return
    for mid in list(ids):
        try:
            await bot.delete_messages(uid, mid)
        except Exception:
            pass
    st.pop("auth_prompt_ids", None)


def reset(uid):
    user_state.pop(uid, None)


def get_settings(uid):
    return settings.setdefault(str(uid), {"delay_min": 1.0, "delay_max": 2.5})


async def get_client(acc):
    phone = acc["phone"]
    with client_lock:
        if phone in clients and clients[phone].is_connected():
            return clients[phone]
    try:
        c = TelegramClient(
            StringSession(acc["string"]),
            API_ID,
            API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="4.16.8",
            connection_retries=3,
            retry_delay=2,
        )
        await c.connect()
        if not await c.is_user_authorized():
            await c.disconnect()
            return None
        with client_lock:
            clients[phone] = c
        return c
    except Exception as e:
        print(f"[client] {acc.get('phone', '?')}: {e}")
        return None


async def save_session_account(c, owner):
    try:
        me = await c.get_me()
        phone = me.phone or "unknown"
        acc = {
            "phone": phone,
            "name": (me.first_name or "").strip(),
            "username": (me.username or "").strip(),
            "string": c.session.save(),
            "id": me.id,
            "owner": owner,
        }
        with client_lock:
            clients[phone] = c
        for i, a in enumerate(accounts):
            if a["phone"] == phone:
                accounts[i] = acc
                save_accounts()
                save_local_backup("account updated")
                return acc
        accounts.append(acc)
        save_accounts()
        save_local_backup("account added")
        return acc
    except Exception as e:
        print(f"[save_session] {e}")
        raise


async def validate_session_string(s, owner):
    c = TelegramClient(
        StringSession(s.strip()),
        API_ID,
        API_HASH,
        device_model="Desktop",
        system_version="Windows 10",
    )
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        raise ValueError("Session expired")
    return await save_session_account(c, owner)


async def auto_remove_dead():
    if not accounts:
        return 0, 0
    dead = []
    alive = []
    for acc in accounts:
        try:
            c = await get_client(acc)
            if c is None:
                dead.append(acc.get("phone", "?"))
                continue
            try:
                await c.get_me()
                alive.append(acc)
            except Exception:
                dead.append(acc.get("phone", "?"))
        except Exception:
            dead.append(acc.get("phone", "?"))
    if dead:
        dead_phones = set(dead)
        # Archive the full account records before removing them from active storage.
        for acc in accounts:
            if acc.get("phone", "?") in dead_phones:
                archive_removed_account(acc, "session expired/dead")
        accounts.clear()
        accounts.extend(alive)
        save_accounts()
    return len(dead), len(alive)

# ═══════════════════════════════════════════════════════════════
#   ENTITY RESOLUTION
# ═══════════════════════════════════════════════════════════════

async def resolve_entity(client, ref):
    kind, val = ref
    try:
        if kind == "username":
            try:
                return await client.get_entity(val)
            except Exception:
                if not val.startswith("@"):
                    return await client.get_entity("@" + val)
                raise
        elif kind == "c":
            try:
                return await client.get_entity(PeerChannel(val))
            except Exception:
                try:
                    async for d in client.iter_dialogs():
                        if d.id == int(f"-100{val}"):
                            return d.entity
                except Exception:
                    pass
            return None
        elif kind == "id":
            cid = val
            if cid < 0:
                cid = abs(cid)
                if cid > 1000000000000:
                    cid -= 1000000000000
            try:
                return await client.get_entity(PeerChannel(cid))
            except Exception:
                try:
                    async for d in client.iter_dialogs():
                        if d.id == val or (d.entity and getattr(d.entity, "id", None) == cid):
                            return d.entity
                except Exception:
                    pass
            return None
        elif kind == "invite":
            try:
                r = await client(CheckChatInviteRequest(hash=val))
                if r.chat:
                    return r.chat
            except Exception:
                pass
            return None
    except Exception:
        return None


entity_cache = {}


async def resolve_entity_cached(c, ref):
    phone = getattr(getattr(c, "session", None), "phone", None) or str(id(c))
    store = entity_cache.setdefault(str(phone), {})
    key = str(ref)
    hit = store.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    ent = await resolve_entity(c, ref)
    if ent:
        store[key] = (ent, time.time() + 1800)
    return ent

# ═══════════════════════════════════════════════════════════════
#   PARSING
# ═══════════════════════════════════════════════════════════════

POST_RE = re.compile(
    r"(?:https?://)?t\.me/(?:c/(\d+)/(\d+)|([A-Za-z0-9_]{4,})/(\d+))",
    re.I,
)
INVITE_RE = re.compile(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)", re.I)


def parse_post_url(url):
    m = POST_RE.search(url.strip())
    if not m:
        return None
    if m.group(1):
        return ("c", int(m.group(1))), int(m.group(2))
    return ("username", m.group(3)), int(m.group(4))


def parse_join_target(text):
    u = text.strip()
    m = INVITE_RE.search(u)
    if m:
        return ("invite", m.group(1))
    m = re.match(r"(?:https?://)?t\.me/@?([A-Za-z0-9_]{3,})/?$", u, re.I)
    if m:
        return ("username", m.group(1))
    if u.startswith("@") and len(u) > 3:
        return ("username", u[1:])
    if re.fullmatch(r"-?\d+", u):
        return ("id", int(u))
    return None


def parse_timer(text):
    t = text.strip().lower()
    if t in ("0", "off", "no"):
        return 0
    m = re.fullmatch(r"(\d+)\s*([sm]?)", t)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2) or "s"
    if unit == "m":
        val *= 60
    return val if val <= 3600 else None


def fmt_timer(sec):
    if not sec:
        return "OFF"
    if sec % 60 == 0 and sec >= 60:
        return f"{sec // 60} min"
    return f"{sec} sec"

# ═══════════════════════════════════════════════════════════════
#   EMOJIS
# ═══════════════════════════════════════════════════════════════

RANDOM_EMOJIS = ["👍", "❤️", "🔥", "🎉", "👏", "😍", "💯", "🤩", "🙏", "⚡"]

EMOJI_GRID = [
    "👍", "👎", "❤️", "🔥",
    "🎉", "🥰", "😂", "🤩",
    "👏", "🙏", "💯", "😎",
    "🤝", "💔", "😊", "😘",
    "💋", "🌚", "🌭", "💩",
    "🤡", "🤣", "😔", "😭",
    "🤓", "👻", "👽", "😇",
    "🦄", "💥", "🏆", "🥳",
]

REACTION_EMOJIS = {
    "❤️‍🔥": "6082544779223110894",
    "🌟": "6086784551894389168",
    "😎": "6334696528145286813",
    "🧊": "6057592848889418693",
    "🚩": "6082673701256434858",
    "👼": "6235505186157107501",
    "🧸": "6235332768989976110",
    "👶": "6129399728506412489",
    "🏠": "5312486108309757006",
    "⚠️": "6237622209897044583",
    "👁️": "6237774947524025498",
    "📊": "5177256464539976338",
    "⚙️": "5388725162247992600",
    "📈": "5282950412784117735",
    "🚫": "6082294352564983391",
    "💀": "6082160779082077008",
    "⏰": "5787488119490088755",
    "❤️": "5422842587151088042",
    "📩": "5309984423003823246",
    "🔍": "5188217332748527444",
    "✅": "6082554958295602218",
    "🔒": "5429405838345265327",
    "🤔": "6327736971728788025",
    "☺️": "6289363706681755465",
    "🔥": "6334449730734529256",
    "⭐": "6239815031219820750",
    "💎": "6240003971126139705",
    "👑": "6332246180583447893",
    "🎉": "6240085923397114865",
    "👍": "6237867138997034625",
    "😍": "6334437167955188087",
    "🚀": "5188481279963715781",
    "🙌": "6237621707385871360",
    "🎯": "6240085923397114865",
}


def build_emoji_grid(selected):
    rows = []
    row = []
    for i, em in enumerate(EMOJI_GRID):
        mark = "✅" if em in selected else ""
        label = f"{mark}{em}"
        style = "success" if em in selected else "primary"
        row.append(btn(label, f"emoji_pick:{i}".encode(), style))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    count = len(selected)
    if count == 0:
        rows.append([btn("Pick at least one", b"emoji_none", "danger")])
    else:
        rows.append([btn(f"✅ Done ({count} selected)", b"emoji_done", "success")])
    rows.append([btn("Cancel", b"menu", "danger")])
    return rows

# ═══════════════════════════════════════════════════════════════
#   ACTION WORKERS
# ═══════════════════════════════════════════════════════════════

async def do_react(c, ent, msg_id, emoji):
    if emoji and emoji.lower() in ("random", "rand", "r", "🍀"):
        emoji = random.choice(RANDOM_EMOJIS)
    emoji = (emoji or "👍").strip()

    async def attempt(r):
        try:
            if hasattr(c, "send_reaction"):
                await c.send_reaction(ent, msg_id, reaction=r)
            else:
                await c(SendReactionRequest(
                    peer=ent, msg_id=msg_id,
                    reaction=[r], add_to_recent=True,
                ))
            return True, None
        except ReactionInvalidError:
            return False, "not allowed"
        except Exception as ex:
            return False, f"{type(ex).__name__}: {str(ex)[:60]}"

    doc = REACTION_EMOJIS.get(emoji)
    if doc:
        ok, err = await attempt(ReactionCustomEmoji(document_id=int(doc)))
        if ok:
            return True, None
    ok, err = await attempt(ReactionEmoji(emoticon=emoji))
    if ok:
        return True, None
    return False, err or "rejected"


async def do_unreact(c, ent, msg_id):
    try:
        if hasattr(c, "send_reaction"):
            await c.send_reaction(ent, msg_id, reaction=[])
        else:
            await c(SendReactionRequest(
                peer=ent, msg_id=msg_id,
                reaction=[], add_to_recent=False,
            ))
        return True, None
    except Exception as ex:
        return False, f"{type(ex).__name__}: {str(ex)[:60]}"


async def do_vote(c, ent, msg_id, bi, bt):
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.buttons:
            return False, "no buttons"
        btn_found = None
        idx = 1
        for row in msg.buttons:
            for b in row:
                if (bi is not None and idx == bi) or \
                   (bt and bt.lower() in (b.text or "").lower()):
                    btn_found = b
                    break
                idx += 1
            if btn_found:
                break
        if btn_found is None:
            btn_found = msg.buttons[0][0]
        try:
            await btn_found.click()
        except (asyncio.TimeoutError, TelethonTimeoutError):
            await c(GetBotCallbackAnswerRequest(
                peer=ent, msg_id=msg_id, data=btn_found.data,
            ))
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def do_poll_vote(c, ent, msg_id, poll_options):
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.poll:
            return False, "not a poll"
        ans = msg.poll.poll.answers
        opts = []
        for i in poll_options:
            if i < 0 or i >= len(ans):
                return False, f"opt {i} out of range"
            opts.append(ans[i].option)
        await c(SendVoteRequest(peer=ent, msg_id=msg_id, options=opts))
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def do_view(c, ent, msg_id):
    try:
        peer = await c.get_input_entity(ent)
        res = await c(GetMessagesViewsRequest(
            peer=peer, id=[msg_id], increment=True,
        ))
        v = res.views[0].views if (res and res.views) else None
        try:
            msg = await c.get_messages(ent, ids=msg_id)
            if msg:
                await c.send_read_acknowledge(ent, msg)
        except Exception:
            pass
        return True, (f"views={v}" if v else None)
    except FloodWaitError as e:
        await asyncio.sleep(min(e.seconds, 30))
        return False, f"Flood {e.seconds}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def do_join_channel(c, target):
    kind, val = target
    try:
        if kind == "invite":
            try:
                await c(ImportChatInviteRequest(val))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
            except (InviteHashExpiredError, InviteHashInvalidError, InviteHashEmptyError):
                return False, "invite expired"
        if kind == "username":
            uname = val if val.startswith("@") else "@" + val
            try:
                await c(JoinChannelRequest(uname))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
            except ChannelPrivateError:
                return False, "private channel"
        if kind == "id":
            ent = await resolve_entity(c, target)
            if not ent:
                return False, "cannot resolve"
            try:
                await c(JoinChannelRequest(ent))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
        return False, "unknown target"
    except FloodWaitError as e:
        await asyncio.sleep(min(e.seconds, 60))
        return False, f"Flood {e.seconds}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def do_leave_channel(c, target):
    try:
        kind, val = target
        if kind == "invite":
            return False, "cannot leave via invite"
        ent = await resolve_entity(c, target)
        if ent:
            await c(LeaveChannelRequest(ent))
            return True, None
        return False, "not found"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def do_dm(c, target, text):
    try:
        kind, val = target
        if kind == "invite":
            return False, "DM target must be user"
        ent = await c.get_entity(val)
        await c.send_message(ent, text)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

# ═══════════════════════════════════════════════════════════════
#   CAMPAIGN EXECUTION
# ═══════════════════════════════════════════════════════════════

async def run_campaign(uid, action, opts):
    cid = f"{uid}_{int(time.time())}"
    count = int(opts.get("count", 0))
    accs = get_campaign_accounts(uid)
    if count > 0:
        accs = accs[:count]
    if not accs:
        return 0, ["No accounts."]

    random.shuffle(accs)
    st = get_settings(uid)
    ok = 0
    fail = []

    timer = int(opts.get("timer", 0) or 0)
    use_timer = action in TIMER_ACTIONS and timer > 0
    post_ref = opts.get("post_ref")
    msg_id = opts.get("msg_id")
    target = opts.get("target")
    emoji = opts.get("emoji")
    emoji_list = opts.get("emoji_list") or []
    bi = opts.get("btn_index")
    bt = opts.get("btn_text")
    poll_options = opts.get("poll_options", [])
    if isinstance(poll_options, str):
        poll_options = [int(x.strip()) for x in poll_options.split(",") if x.strip().isdigit()]
    join_target = opts.get("join_target")

    info = {
        "id": cid, "owner": uid, "action": action,
        "started": time.time(), "total": len(accs), "processed": 0,
        "status": "running", "paused": False, "stopped": False,
        "current_phone": "", "current_name": "",
        "current_stage": "Starting...",
    }
    active_campaigns[cid] = info
    running_campaigns[cid] = info

    total = len(accs)
    action_name = action.replace("_", " ").title()
    target_str = ""
    if post_ref:
        target_str = f"t.me/{post_ref[1]}/{msg_id}"
    elif target:
        target_str = str(target[1])
    elif join_target:
        target_str = f"t.me/+{join_target[1]}"

    DOTS = ["", ".", "..", "..."]
    SPINNERS = ["◐", "◓", "◑", "◒"]
    PULSE = ["🔵", "🟣", "🟢", "🟡", "🟠", "🔴"]

    def build_progress():
        t = int(time.time() * 2)
        dot = DOTS[t % len(DOTS)]
        spinner = SPINNERS[t % len(SPINNERS)]
        pulse = PULSE[t % len(PULSE)]
        elapsed = max(1, int(time.time() - info["started"]))
        prog = info["processed"]
        pct = int(100 * prog / max(total, 1))
        remaining = total - prog
        bar_len = 22
        filled = int(bar_len * prog / max(total, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        speed = (prog / elapsed) if elapsed > 0 else 0
        eta = int(remaining / speed) if speed > 0 else 0
        if eta >= 60:
            eta_txt = f"{eta // 60}m {eta % 60}s"
        else:
            eta_txt = f"{eta}s"

        if info.get("paused"):
            status = "⏸️ PAUSED"
        elif info.get("stopped"):
            status = "⏹️ STOPPING..."
        else:
            status = f"{spinner} *{info['current_stage']}{dot}*"

        cur = ""
        if info["current_phone"]:
            nm = info["current_name"][:20] if info["current_name"] else "?"
            cur = f"\n{pulse} `{info['current_phone']}` — {nm}"

        text = (
            f"🌐 **{action_name}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Target: `{target_str}`\n\n"
            f"📊 `{bar}` **{pct}%**\n"
            f"🔢 {prog}/{total}  ⏳ {remaining}  ⏱️ ~{eta_txt} left"
            f"{cur}\n\n"
            f"{status}\n\n"
            f"✅ {ok}   ❌ {len(fail)}   ⚡ {speed:.2f}/s"
        )
        if fail:
            errs = "\n".join(f"• {f[:75]}" for f in fail[-3:])
            text += f"\n\n⚠️ **Errors:**\n{errs}"
        return text

    btns_live = [[
        btn("Pause", b"camp_pause:" + cid.encode(), "primary"),
        btn("Stop", b"camp_stop:" + cid.encode(), "danger"),
    ]]

    try:
        progress_msg = await bot.send_message(
            uid, build_progress(),
            buttons=btns_live, parse_mode="md",
        )
    except Exception:
        progress_msg = None

    async def animate():
        while info.get("status") == "running":
            if progress_msg:
                try:
                    await safe_edit(
                        progress_msg, build_progress(),
                        buttons=btns_live, parse_mode="md",
                    )
                except Exception:
                    pass
            await asyncio.sleep(1.2)

    anim_task = asyncio.create_task(animate())

    def set_stage(name):
        info["current_stage"] = name

    try:
        for i, acc in enumerate(accs):
            while info.get("paused") and not info.get("stopped"):
                await asyncio.sleep(2)
            if active_campaigns.get(cid, {}).get("stopped"):
                break

            if use_timer and i > 0:
                set_stage(f"Waiting {timer}s")
                await asyncio.sleep(timer)

            info["current_phone"] = acc.get("phone", "?")
            info["current_name"] = acc.get("name", "")

            try:
                set_stage("Connecting")
                c = await get_client(acc)
                if c is None:
                    fail.append(f"{acc['phone']}: session dead")
                    info["processed"] += 1
                    continue

                if action == "leave_all":
                    set_stage("Leaving all")
                    try:
                        dlg = await c.get_dialogs(limit=100)
                        for d in dlg:
                            if d.is_group or d.is_channel:
                                try:
                                    await c(LeaveChannelRequest(d.entity))
                                    await asyncio.sleep(random.uniform(0.8, 1.8))
                                except Exception:
                                    pass
                        ok += 1
                    except Exception as ex:
                        fail.append(f"{acc['phone']}: {str(ex)[:50]}")
                    info["processed"] += 1
                    continue

                if join_target:
                    set_stage("Joining")
                    j, jerr = await do_join_channel(c, join_target)
                    if not j:
                        fail.append(f"{acc['phone']}: Join — {jerr}")
                        info["processed"] += 1
                        continue
                    await asyncio.sleep(random.uniform(1.5, 3.0))

                ent = None
                if post_ref:
                    set_stage("Resolving")
                    ent = await resolve_entity_cached(c, post_ref)
                    if ent is None:
                        ent = await resolve_entity(c, post_ref)
                    if not ent and target:
                        ent = await resolve_entity_cached(c, target)

                if post_ref and ent is None:
                    fail.append(f"{acc['phone']}: Post not accessible")
                    info["processed"] += 1
                    continue

                if action in ("react", "react_vote", "react_vote_view"):
                    if action == "react_vote_view":
                        set_stage("Viewing")
                        await do_view(c, ent, msg_id)
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                    set_stage("Reacting")
                    use_emoji = random.choice(emoji_list) if emoji_list else emoji
                    sok, rerr = await do_react(c, ent, msg_id, use_emoji)
                    if not sok:
                        fail.append(f"{acc['phone']}: React — {rerr}")
                        info["processed"] += 1
                        continue
                    if action != "react":
                        set_stage("Voting")
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        vs, verr = await do_vote(c, ent, msg_id, bi, bt)
                        if not vs:
                            fail.append(f"{acc['phone']}: Vote — {verr}")
                            info["processed"] += 1
                            continue
                elif action == "vote":
                    set_stage("Voting")
                    vs, verr = await do_vote(c, ent, msg_id, bi, bt)
                    if not vs:
                        fail.append(f"{acc['phone']}: Vote — {verr}")
                        info["processed"] += 1
                        continue
                elif action == "poll_vote":
                    set_stage("Poll")
                    ps, perr = await do_poll_vote(c, ent, msg_id, poll_options)
                    if not ps:
                        fail.append(f"{acc['phone']}: Poll — {perr}")
                        info["processed"] += 1
                        continue
                elif action == "unreact":
                    set_stage("Unreacting")
                    us, uerr = await do_unreact(c, ent, msg_id)
                    if not us:
                        fail.append(f"{acc['phone']}: Unreact — {uerr}")
                        info["processed"] += 1
                        continue
                elif action == "unvote":
                    set_stage("Unvoting")
                    us, uerr = await do_vote(c, ent, msg_id, bi, bt)
                    if not us:
                        fail.append(f"{acc['phone']}: Unvote — {uerr}")
                        info["processed"] += 1
                        continue
                elif action == "view":
                    set_stage("Viewing")
                    vs, verr = await do_view(c, ent, msg_id)
                    if not vs:
                        fail.append(f"{acc['phone']}: View — {verr}")
                        info["processed"] += 1
                        continue
                elif action == "join":
                    if target:
                        set_stage("Joining")
                        js, jerr = await do_join_channel(c, target)
                        if not js:
                            fail.append(f"{acc['phone']}: Join — {jerr}")
                            info["processed"] += 1
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target")
                        info["processed"] += 1
                        continue
                elif action == "leave":
                    if target:
                        set_stage("Leaving")
                        ls, lerr = await do_leave_channel(c, target)
                        if not ls:
                            fail.append(f"{acc['phone']}: Leave — {lerr}")
                            info["processed"] += 1
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target")
                        info["processed"] += 1
                        continue
                elif action == "dm":
                    if target:
                        set_stage("DM")
                        ds, derr = await do_dm(c, target, opts.get("dm_text", ""))
                        if not ds:
                            fail.append(f"{acc['phone']}: DM — {derr}")
                            info["processed"] += 1
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target")
                        info["processed"] += 1
                        continue

                ok += 1
                info["processed"] = ok + len(fail)

            except FloodWaitError as e:
                fail.append(f"{acc['phone']}: Flood {e.seconds}s")
                await asyncio.sleep(min(e.seconds, 30))
                info["processed"] += 1
            except Exception as ex:
                fail.append(f"{acc['phone']}: {type(ex).__name__}: {str(ex)[:50]}")
                info["processed"] += 1

            info["processed"] = max(info["processed"], ok + len(fail))
            await asyncio.sleep(random.uniform(st["delay_min"], st["delay_max"]))

    finally:
        info["status"] = "completed"
        try:
            anim_task.cancel()
        except Exception:
            pass

        campaigns.append({
            "owner": uid, "action": action, "ok": ok, "fail": len(fail),
            "time": time.strftime("%d-%m %H:%M"),
        })
        save_campaigns()

        if progress_msg:
            try:
                dur = int(time.time() - info["started"])
                pct_ok = (ok / max(total, 1)) * 100
                if ok == total:
                    grade = "🏆 PERFECT!"
                elif ok >= total * 0.8:
                    grade = "🥇 EXCELLENT"
                elif ok >= total * 0.5:
                    grade = "🥈 PARTIAL"
                else:
                    grade = "🥉 LOW"

                final = (
                    f"✅ **CAMPAIGN COMPLETE**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🎯 Target: `{target_str}`\n\n"
                    f"📊 Total: `{total}`\n"
                    f"✅ Success: `{ok}`\n"
                    f"❌ Failed: `{len(fail)}`\n"
                    f"⏱️ Time: `{dur}s`\n"
                    f"📈 Rate: `{pct_ok:.1f}%`\n\n"
                    f"{grade}"
                )
                if fail:
                    errs = "\n".join(f"• {f[:60]}" for f in fail[:8])
                    final += f"\n\n⚠️ **Errors:**\n{errs}"
                await safe_edit(progress_msg, final, parse_mode="md")
            except Exception:
                pass

        active_campaigns.pop(cid, None)
        running_campaigns.pop(cid, None)

    return ok, fail


def stop_campaign(cid):
    if cid in active_campaigns:
        active_campaigns[cid]["stopped"] = True
        return True
    return False


def get_running_campaigns():
    return list(running_campaigns.values())


async def scheduler_loop():
    while True:
        now = time.time()
        for s in [x for x in scheduled if x["run_at"] <= now]:
            scheduled.remove(s)
            save_scheduled()
            try:
                ok, fail = await run_campaign(s["owner"], s["action"], s["opts"])
                txt = f"⏰ Scheduled Complete\nAction: `{s['action']}`\n✓ {ok} ✗ {len(fail)}"
                await bot.send_message(s["owner"], txt, parse_mode="md")
            except Exception as e:
                print(f"[scheduler] {e}")
        await asyncio.sleep(5)

# ═══════════════════════════════════════════════════════════════
#   BOT INIT
# ═══════════════════════════════════════════════════════════════

# Use a fresh in-memory bot session so no old user-authorized session can
# override the supplied bot token.
bot = TelegramClient(
    StringSession(),
    API_ID,
    API_HASH,
).start(bot_token=BOT_TOKEN)


# Premium custom-emoji document IDs supplied by the user.
PREMIUM_EMOJI_IDS = [
    6129705083501293112,
    5967586565046670020,
    5967586565046670020,
    5859227881653145513,
    6129574787078429498,
    6129903231817488942,
    6129879029676776924,
    6129410818111970687,
    5341709916195278958,
    6217607993010166007,
    6289481706613245545,
    6253672442552653728,
    6100662213998023298,
    5341666665874606143,
    6289363706681755465,
    6100147565246813025,
    5341640913250702206,
    5341640913250702206,
    5832417682179232547,
    5992163643519669293,
    5931374321384557692,
    5832195314542447730,
    5832588566043036828,
    5832562469821746227,
]

USER_MAIN_MENU = [
    [btn("Add Account", b"add", "primary", PREMIUM_EMOJI_IDS[0]), btn("My Accounts", b"myacc", "primary", PREMIUM_EMOJI_IDS[1])],
    [btn("New Campaign", b"camp", "success", PREMIUM_EMOJI_IDS[2]), btn("My Campaigns", b"mycamp", "success", PREMIUM_EMOJI_IDS[3])],
    [btn("Scheduled", b"scheduled", "primary", PREMIUM_EMOJI_IDS[4]), btn("My Stats", b"mystat", "primary", PREMIUM_EMOJI_IDS[5])],
    [btn("Settings", b"set", "primary", PREMIUM_EMOJI_IDS[6]), btn("My Profile", b"profile", "primary", PREMIUM_EMOJI_IDS[7])],
    [btn("Help", b"help", "primary", PREMIUM_EMOJI_IDS[8]), btn("Support", b"support_btn", "primary", PREMIUM_EMOJI_IDS[9])],
    [btn("Developer", b"developer_btn", "success", PREMIUM_EMOJI_IDS[10])],
]

OWNER_USER_MENU = [
    [btn("Add Account", b"add", "primary", PREMIUM_EMOJI_IDS[0]), btn("My Accounts", b"myacc", "primary", PREMIUM_EMOJI_IDS[1])],
    [btn("New Campaign", b"camp", "success", PREMIUM_EMOJI_IDS[2]), btn("My Campaigns", b"mycamp", "success", PREMIUM_EMOJI_IDS[3])],
    [btn("Scheduled", b"scheduled", "primary", PREMIUM_EMOJI_IDS[4]), btn("My Stats", b"mystat", "primary", PREMIUM_EMOJI_IDS[5])],
    [btn("Settings", b"set", "primary", PREMIUM_EMOJI_IDS[6]), btn("My Profile", b"profile", "primary", PREMIUM_EMOJI_IDS[7])],
    [btn("Help", b"help", "primary", PREMIUM_EMOJI_IDS[8]), btn("Support", b"support_btn", "primary", PREMIUM_EMOJI_IDS[9])],
    [btn("Owner Panel", b"owner_panel", "danger", PREMIUM_EMOJI_IDS[11])],
    [btn("Adv Campaign", b"adv_camp", "success", PREMIUM_EMOJI_IDS[12])],
    [btn("Developer", b"developer_btn", "success", PREMIUM_EMOJI_IDS[10])],
]

OWNER_PANEL_MENU = [
    [btn("Users List", b"admin_users", "primary"), btn("All Sessions", b"admin_sessions", "success")],
    [btn("Broadcast", b"admin_broadcast", "success"), btn("Settings", b"bot_settings", "primary")],
    [btn("Ban/Unban", b"admin_ban", "danger"), btn("Message All Users", b"admin_msg_all", "primary")],
    [btn("FSub Check", b"admin_fsub_check", "success"), btn("Adv Campaign", b"adv_camp", "primary")],
    [btn("Session Health", b"admin_health", "primary"), btn("Adv Access", b"admin_access", "primary")],
    [btn("Manage Owners", b"admin_manage_owners", "primary"), btn("Add Session (OTP)", b"add_phone", "success")],
    [btn("Campaign Info", b"admin_camp_info", "primary"), btn("DB Stats", b"admin_db_stats", "primary")],
    [btn("DB Diagnostics", b"admin_db_diagnostics", "success"), btn("Expired Accounts", b"expired_acc", "danger")],
    [btn("Account Health", b"admin_health", "primary"), btn("Analytics", b"admin_analytics", "primary")],
    [btn("Rotation", b"admin_sessions", "primary"), btn("Notifications", b"bot_settings", "primary")],
    [btn("Extract DB Backup", b"admin_backup_now", "danger")],
    [btn("Main Menu", b"menu", "primary")],
]

ADV_CAMPAIGN_MENU = [
    [btn("React Only", b"advact:react", "primary"), btn("Vote Only", b"advact:vote", "primary")],
    [btn("React + Vote", b"advact:react_vote", "primary"), btn("View Only", b"advact:view", "primary")],
    [btn("React + View", b"advact:react_view", "primary"), btn("Vote + View", b"advact:vote_view", "primary")],
    [btn("React + Vote + View", b"advact:react_vote_view", "success")],
    [btn("Join Channel", b"advact:join", "success"), btn("Leave Channel", b"advact:leave", "danger")],
    [btn("Leave All", b"advact:leave_all", "danger")],
    [btn("Bulk DM", b"advact:dm", "primary")],
    [btn("Back", b"menu", "danger")],
]

NEW_CAMPAIGN_MENU = [
    [btn("React Only", b"camp_act:react", "primary"), btn("Vote Only", b"camp_act:vote", "primary")],
    [btn("React + Vote", b"camp_act:react_vote", "primary"), btn("View Only", b"camp_act:view", "primary")],
    [btn("React + View", b"camp_act:react_view", "primary"), btn("Vote + View", b"camp_act:vote_view", "primary")],
    [btn("React + Vote + View", b"camp_act:react_vote_view", "success")],
    [btn("Join Channel", b"camp_act:join", "success"), btn("Leave Channel", b"camp_act:leave", "danger")],
    [btn("Leave All", b"camp_act:leave_all", "danger")],
    [btn("Bulk DM", b"camp_act:dm", "primary")],
    [btn("Back", b"menu", "danger")],

]
# ═══════════════════════════════════════════════════════════════
#   TEXT BUILDERS
# ═══════════════════════════════════════════════════════════════

async def get_display_name(uid):
    try:
        u = await bot.get_entity(uid)
        return (u.first_name or "User").upper()
    except Exception:
        return "USER"


async def menu_text(uid):
    name = await get_display_name(uid)
    my = len(my_accounts(uid))
    if my == 0:
        acc = "⚠️ No accounts added yet."
    else:
        acc = f"✅ You have {my} account(s) added."
    # Access role uses a Telegram Premium custom emoji. Owners and normal users
    # get different custom emoji IDs as requested.
    if is_owner(uid):
        role = '<tg-emoji emoji-id="5931374321384557692">👑</tg-emoji> Owner'
    else:
        role = '<tg-emoji emoji-id="6192541021977451187">👤</tg-emoji> User'
    return (
        f"Welcome back, <b>{name}</b> 🌹!\n"
        f"─────────────────────\n\n"
        f"<b>Auto Voter</b>\n"
        f"<i>Telegram Automation Bot</i>\n\n"
        f"─────────────────────\n\n"
        f"<code>React • Vote • View • Join • DM</code>\n"
        f"<i>Fast, reliable &amp; smart Telegram automation</i>\n\n"
        f"{acc}\n"
        f"Access: {role}\n\n"
        f"Choose an option:\n\n"
        f"<i>Developed by</i> @{CREDIT_BOT}"
    )


def no_access():
    return "⚠️ Access Denied"


def owner_panel_text():
    uptime_sec = int(time.time() - BOT_START_TIME)
    hours = uptime_sec // 3600
    mins = (uptime_sec % 3600) // 60
    uptime_txt = f"{hours}h {mins}m"

    total_actions = sum(c.get("ok", 0) + c.get("fail", 0) for c in campaigns)
    active = sum(1 for a in accounts if a.get("phone") in clients)

    return (
        f"👑 **OWNER PANEL**\n"
        f"───────────────────────\n\n"
        f"👥 Users: {len(get_visible_users())}\n"
        f"📦 Accounts: {len(accounts)}  ·  Active: {active}\n"
        f"🚀 Campaigns: {len(campaigns)}  ·  Running: {len(get_running_campaigns())}\n"
        f"⚡ Total Actions: {total_actions}\n"
        f"📌 ADV Access: {len(adv_access_grants)}  ·  🚫 Banned: {len(banned_users)}\n"
        f"🕐 Uptime: {uptime_txt}"
    )


def bot_settings_text():
    m = bot_settings.get("maintenance", False)
    p = bot_settings.get("paid_mode", False)
    owner = bot_settings.get("owner_username", "BtwRynoxx")
    return (
        f"⚙️ **BOT SETTINGS**\n"
        f"───────────────────────\n\n"
        f"🛠️ Maintenance: {'ON 🟢' if m else 'OFF 🔴'}\n"
        f"💎 Paid Mode: {'ON 🟢' if p else 'OFF 🔴'}\n"
        f"👤 Owner: @{owner}"
    )


def bot_settings_menu():
    m = bot_settings.get("maintenance", False)
    p = bot_settings.get("paid_mode", False)
    owner = bot_settings.get("owner_username", "BtwRynoxx")
    return [
        [btn(f"🛠️ Maintenance: {'OFF ❌' if not m else 'ON ✅'}",
             b"bs_toggle_maint", "danger" if m else "primary")],
        [btn(f"💎 Paid Mode: {'OFF ❌' if not p else 'ON ✅'}",
             b"bs_toggle_paid", "primary")],
        [btn(f"👤 Owner: @{owner}", b"bs_set_owner", "primary")],
        [btn("Owner Panel", b"owner_panel")],
    ]


def owners_manage_menu():
    btns = []
    for oid in extra_owners[:10]:
        btns.append([btn(f"🗑️ {oid}", f"own_del:{oid}".encode(), "danger")])
    btns.append([btn("Add Owner", b"own_add", "success")])
    btns.append([btn("Owner Panel", b"owner_panel")])
    return btns


def owners_manage_text():
    if not extra_owners:
        return (
            f"👑 **MANAGE OWNERS**\n"
            f"───────────────────────\n\n"
            f"📊 Main Owners: `{len(OWNER_IDS)}`\n"
            f"➕ Added Owners: `0`\n\n"
            f"_No added owners yet._\n\n"
            f"Tap ➕ to add one."
        )
    lines = [
        f"👑 **MANAGE OWNERS**\n"
        f"───────────────────────\n\n"
        f"📊 Main Owners: `{len(OWNER_IDS)}`\n"
        f"➕ Added Owners: `{len(extra_owners)}`\n\n"
        f"**Added:**"
    ]
    for oid in extra_owners[:10]:
        lines.append(f"· `{oid}`")
    if len(extra_owners) > 10:
        lines.append(f"_...+{len(extra_owners) - 10} more_")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
#   FLOW HELPERS
# ═══════════════════════════════════════════════════════════════

async def show_vote_picker(e, uid):
    text = "🔘 **Step 4 — Which button should your accounts click?**"
    btns = [
        [btn("1️⃣ 1st", b"vote_pick:1", "primary"),
         btn("2️⃣ 2nd", b"vote_pick:2", "primary"),
         btn("3️⃣ 3rd", b"vote_pick:3", "primary")],
        [btn("4️⃣ 4th", b"vote_pick:4", "primary"),
         btn("5️⃣ 5th", b"vote_pick:5", "primary"),
         btn("Other #", b"vote_pick:other", "success")],
        [btn("Cancel", b"menu", "danger")],
    ]
    try:
        return await e.edit(text, buttons=btns, parse_mode="md")
    except Exception:
        return await e.reply(text, buttons=btns, parse_mode="md")


async def show_count_prompt(e, uid, reply=True):
    available = len(get_campaign_accounts(uid))
    text = (
        f"📊 **How many accounts?**\n"
        f"───────────────────────\n\n"
        f"📱 You have **{available} active account(s)** available.\n"
        f"Max you can use: **{available}**\n\n"
        f"Send a number (1-{available}) or tap **All** to use all:"
    )
    btns = [[
        btn(f"✅ All ({available})", b"count_all", "success"),
        btn("Cancel", b"menu", "danger"),
    ]]
    try:
        if reply:
            return await e.reply(text, buttons=btns, parse_mode="md")
        return await e.edit(text, buttons=btns, parse_mode="md")
    except Exception:
        return await e.edit(text, buttons=btns, parse_mode="md")


async def ask_run_cb(e, uid):
    s = state(uid)
    s["step"] = None
    opts = s.get("camp_opts", {})
    smry = f"◆ CAMPAIGN READY\n\nAction: {s['camp_action']}\n"
    if "post_ref" in opts:
        smry += f"Post: `{opts['msg_id']}`\n"
    if "join_target" in opts:
        smry += "🔐 Auto-Join: YES\n"
    if "count" in opts:
        c = opts["count"]
        tot = len(get_campaign_accounts(uid))
        smry += f"Accounts: {'All' if c == 0 else c} ({tot} available)\n"
    if "timer" in opts and opts["timer"] > 0:
        smry += f"⏳ Timer: {fmt_timer(opts['timer'])}\n"
    if opts.get("emoji_list"):
        smry += f"Emojis: {' '.join(opts['emoji_list'])}\n"
    elif "emoji" in opts:
        ed = "🎲 Random" if opts["emoji"].lower() in ("random", "rand", "r", "🍀") else opts["emoji"]
        smry += f"Emoji: {ed}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        smry += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        smry += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        smry += f"Msg: {opts['dm_text'][:60]}\n"
    try:
        await e.edit(smry, parse_mode="md")
    except Exception:
        await bot.send_message(uid, smry, parse_mode="md")
    btns = [
        [btn("Run Now", b"run_now", "success"),
         btn("Schedule", b"schedule_btn", "primary")],
        [btn("Cancel", b"menu", "danger")],
    ]
    await bot.send_message(uid, "▶️ Run now or schedule?", buttons=btns, parse_mode="md")


async def camp_next(e, uid):
    s = state(uid)
    action = s["camp_action"]
    if action in ("join", "leave"):
        if "target" not in s["camp_opts"]:
            s["step"] = "camp_target"
            return await e.reply("📌 Send target:")
        return await ask_run(e, uid)
    if action == "dm":
        if "target" not in s["camp_opts"]:
            s["step"] = "camp_target"
            return await e.reply("📩 Send user:")
        if "dm_text" not in s["camp_opts"]:
            s["step"] = "camp_dm_text"
            return await e.reply("📩 Send msg:")
        return await ask_run(e, uid)
    if action in ("react", "react_vote", "react_vote_view"):
        s["step"] = "camp_react_multi"
        s["react_emojis"] = []
        return await e.reply(
            "**Step 2** — Choose reaction(s):\n\nTap to select. Pick multiple. Then ✅ Done.",
            buttons=build_emoji_grid([]),
            parse_mode="md",
        )
    if action in ("vote", "unvote", "poll_vote"):
        if action == "poll_vote":
            s["step"] = "camp_poll_options"
            return await e.reply("📊 Options:\n`0,1,2`")
        if s["camp_opts"].get("btn_index") or s["camp_opts"].get("btn_text"):
            return await ask_run(e, uid)
        return await show_vote_picker(e, uid)
    return await ask_run(e, uid)


async def ask_run(e, uid):
    s = state(uid)
    s["step"] = None
    opts = s.get("camp_opts", {})
    smry = f"◆ CAMPAIGN READY\n\nAction: {s['camp_action']}\n"
    if "post_ref" in opts:
        smry += f"Post: `{opts['msg_id']}`\n"
    if "join_target" in opts:
        smry += "🔐 Auto-Join: YES\n"
    if "count" in opts:
        c = opts["count"]
        tot = len(get_campaign_accounts(uid))
        smry += f"Accounts: {'All' if c == 0 else c} ({tot} available)\n"
    if "timer" in opts and opts["timer"] > 0:
        smry += f"⏳ Timer: {fmt_timer(opts['timer'])}\n"
    if opts.get("emoji_list"):
        smry += f"Emojis: {' '.join(opts['emoji_list'])}\n"
    elif "emoji" in opts:
        ed = "🎲 Random" if opts["emoji"].lower() in ("random", "rand", "r", "🍀") else opts["emoji"]
        smry += f"Emoji: {ed}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        smry += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        smry += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        smry += f"Msg: {opts['dm_text'][:60]}\n"
    await send(e, smry, parse_mode="md")
    await send(
        e, "▶️ Run now or schedule?",
        buttons=[
            [btn("Run Now", b"run_now", "success"),
             btn("Schedule", b"schedule_btn", "primary")],
            [btn("Cancel", b"menu")],
        ],
    )

# ═══════════════════════════════════════════════════════════════
#   COMMANDS
# ═══════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(pattern="^/(start|menu)$"))
async def cmd_start(e):
    uid = e.sender_id
    reset(uid)
    if uid in banned_users and not is_owner(uid):
        return await e.reply("🚫 Banned.")
    if bot_settings.get("maintenance") and not is_owner(uid):
        return await e.reply("🛠️ Bot under maintenance.")
    text = await menu_text(uid)
    if is_owner(uid):
        await e.reply(text, buttons=OWNER_USER_MENU, parse_mode="html")
    else:
        await e.reply(text, buttons=USER_MAIN_MENU, parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/stop(\s+.*)?$"))
async def cmd_stop(e):
    if not is_admin(e.sender_id):
        return await e.reply("⚠️ Admin Only!", parse_mode="md")
    cid = e.pattern_match.group(1)
    if cid:
        if stop_campaign(cid.strip()):
            await e.reply("✓ Stopped", parse_mode="md")
        else:
            await e.reply("✗ Not found", parse_mode="md")
    else:
        r = get_running_campaigns()
        if not r:
            return await e.reply("✗ None running.", parse_mode="md")
        await e.reply(
            "\n".join([f"· `{c['id'][:8]}` — {c['action']}" for c in r]),
            parse_mode="md",
        )


# ═══════════════════════════════════════════════════════════════
#   MAIN CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════════

def normalize_phone_display(phone):
    phone = str(phone or "?").strip()
    if phone and phone != "?" and not phone.startswith("+"):
        return "+" + phone
    return phone

async def render_live_accounts(e, uid):
    """Render the Live Accounts screen in the reference screenshot style."""
    accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)

    if not accs:
        return await e.edit(
            "My Accounts — Live Working\n"
            "══════════════════════════════\n\n"
            "📊  Total: 0  ❝❞\n\n"
            "No live accounts found.",
            buttons=[
                [btn("👻 Add Another", b"add", "primary")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
        )

    lines = [
        "My Accounts — Live Working",
        "══════════════════════════════",
        "",
        f"📊  Total: {len(accs)}  ❝❞",
        "",
    ]
    for a in accs[:30]:
        # Older saved accounts may not have username stored; refresh it from Telegram.
        username = str(a.get("username") or "").strip()
        if not username:
            try:
                c = await get_client(a)
                if c:
                    me = await c.get_me()
                    username = str(me.username or "").strip()
                    if username:
                        a["username"] = username
                    if me.first_name and not a.get("name"):
                        a["name"] = me.first_name.strip()
            except Exception:
                pass
        lines.append(str(a.get("name") or "Unknown"))
        lines.append(f"@{username}" if username else "@username not set")
        lines.append(normalize_phone_display(a.get("phone")))
        lines.append("")
    try:
        save_accounts()
    except Exception:
        pass
    if len(accs) > 30:
        lines.append(f"... +{len(accs) - 30} more")

    buttons = []
    for a in accs[:30]:
        phone = normalize_phone_display(a.get("phone"))
        name = str(a.get("name") or "Unknown").strip()
        username = str(a.get("username") or "").strip()
        label_base = f"{name} @{username}" if username else name
        label_name = label_base if len(label_base) <= 28 else label_base[:27] + "…"
        raw_phone = str(a.get("phone") or "?")
        buttons.append([btn(f"💌 Remove {label_name}", f"live_remove:{raw_phone}".encode(), "danger")])
    buttons.append([btn("💌 ⚠️ REMOVE ALL", b"live_remove_all", "success")])
    buttons.append([btn("👻 Add Another", b"add", "primary")])
    buttons.append([btn("🦚 Main Menu", b"menu", "primary")])
    return await e.edit("\n".join(lines), buttons=buttons)

@bot.on(events.CallbackQuery())
async def cb(e):
    uid = e.sender_id
    data = e.data.decode()
    s = state(uid)

    if uid in banned_users and not is_owner(uid):
        return await e.answer("🚫 Banned", alert=True)

    # Menu
    if data == "menu":
        await clear_auth_prompts(uid)
        reset(uid)
        text = await menu_text(uid)
        if is_owner(uid):
            return await e.edit(text, buttons=OWNER_USER_MENU, parse_mode="html")
        return await e.edit(text, buttons=USER_MAIN_MENU, parse_mode="html")

    # Owner Panel
    if data == "owner_panel":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        return await e.edit(owner_panel_text(), buttons=OWNER_PANEL_MENU, parse_mode="md")

    # Manage Owners
    if data == "admin_manage_owners":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        return await e.edit(owners_manage_text(), buttons=owners_manage_menu(), parse_mode="md")

    if data == "own_add":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        s["step"] = "owner_add_input"
        return await e.edit(
            "➕ **Add Owner**\n\nSend User ID:\n\n⚠️ This user will get full Owner Panel access!",
            buttons=[[btn("Cancel", b"admin_manage_owners")]],
            parse_mode="md",
        )

    if data.startswith("own_del:"):
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        try:
            tid = int(data.split(":")[1])
        except Exception:
            return await e.answer("Invalid", alert=True)
        if tid in extra_owners:
            extra_owners.remove(tid)
            save_extra_owners()
        await e.answer(f"✅ Removed {tid}", alert=True)
        return await cb(e)

    # Bot Settings
    if data == "bot_settings":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        return await e.edit(bot_settings_text(), buttons=bot_settings_menu(), parse_mode="md")

    if data == "bs_toggle_maint":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        bot_settings["maintenance"] = not bot_settings.get("maintenance", False)
        save_bot_settings()
        return await e.edit(bot_settings_text(), buttons=bot_settings_menu(), parse_mode="md")

    if data == "bs_toggle_paid":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        bot_settings["paid_mode"] = not bot_settings.get("paid_mode", False)
        save_bot_settings()
        return await e.edit(bot_settings_text(), buttons=bot_settings_menu(), parse_mode="md")

    if data == "bs_set_owner":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        s["step"] = "bs_owner_input"
        return await e.edit(
            "👤 **Owner Username**\n\nSend without @:",
            buttons=[[btn("Cancel", b"bot_settings")]],
            parse_mode="md",
        )

    # Message All Users
    if data == "admin_msg_all":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        s["step"] = "msg_all_input"
        users = set(a.get("owner") for a in accounts)
        return await e.edit(
            f"📣 **Message All Users**\n\nRecipients: **{len(users)} users**\n\nSend message:",
            buttons=[[btn("Cancel", b"owner_panel")]],
            parse_mode="md",
        )

    # Count All
    if data == "count_all":
        s.setdefault("camp_opts", {})["count"] = 0
        return await ask_run_cb(e, uid)

    # Emoji Grid
    if data.startswith("emoji_pick:"):
        try:
            idx = int(data.split(":")[1])
            em = EMOJI_GRID[idx]
        except Exception:
            return await e.answer("Invalid", alert=True)
        sel = s.setdefault("react_emojis", [])
        if em in sel:
            sel.remove(em)
        else:
            sel.append(em)
        try:
            return await e.edit(
                "**Step 2** — Choose reaction(s):\n\nTap to select. Pick multiple. Then ✅ Done.",
                buttons=build_emoji_grid(sel),
                parse_mode="md",
            )
        except Exception:
            return await e.answer(f"{'✅' if em in sel else '☑️'} {em}", alert=False)

    if data == "emoji_none":
        return await e.answer("⚠️ Pick at least one!", alert=True)

    if data == "emoji_done":
        sel = s.get("react_emojis", [])
        if not sel:
            return await e.answer("⚠️ Pick at least one!", alert=True)
        s.setdefault("camp_opts", {})["emoji_list"] = list(sel)
        s["camp_opts"]["emoji"] = random.choice(sel)
        s.pop("react_emojis", None)
        s["step"] = None
        if s.get("camp_action") in ("react_vote", "react_vote_view"):
            return await show_vote_picker(e, uid)
        return await ask_run_cb(e, uid)

    # Vote Picker
    if data.startswith("vote_pick:"):
        arg = data.split(":", 1)[1]
        if arg == "other":
            s["step"] = "camp_btn_other"
            return await e.edit(
                "🔢 **Send button number or text:**",
                buttons=[[btn("Cancel", b"menu")]],
                parse_mode="md",
            )
        try:
            n = int(arg)
        except Exception:
            return await e.answer("Invalid", alert=True)
        s.setdefault("camp_opts", {})["btn_index"] = n
        s["camp_opts"]["btn_text"] = None
        s["step"] = None
        return await ask_run_cb(e, uid)

    # Pause Live
    if data.startswith("camp_pause:"):
        cid = data[11:]
        if cid in active_campaigns:
            info = active_campaigns[cid]
            if not is_owner(uid) and info["owner"] != uid:
                return await e.answer("❌", alert=True)
            info["paused"] = not info.get("paused", False)
            return await e.answer("⏸️ Paused" if info["paused"] else "▶️ Resumed", alert=False)
        return await e.answer("Not running", alert=True)

    # Stop Live
    if data.startswith("camp_stop:"):
        cid = data[10:]
        if cid in active_campaigns:
            info = active_campaigns[cid]
            if not is_owner(uid) and info["owner"] != uid:
                return await e.answer("❌", alert=True)
            info["stopped"] = True
            return await e.answer("⏹️ Stopping...", alert=False)
        return await e.answer("Not running", alert=True)

    # React Type Select
    if data == "react_specific" or data == "react_random":
        s["step"] = "camp_react_multi"
        s["react_emojis"] = []
        try:
            return await e.edit(
                "**Step 2** — Choose reaction(s):\n\nTap to select. Pick multiple. Then ✅ Done.",
                buttons=build_emoji_grid([]),
                parse_mode="md",
            )
        except Exception:
            return await e.reply("Pick emojis:", buttons=build_emoji_grid([]), parse_mode="md")

    # Admin callbacks
    if data.startswith("admin_") or data.startswith("usr_") or data.startswith("advacc_"):
        return await handle_admin_callbacks(e, uid, data)

    # Adv Campaign
    if data == "adv_camp":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        text = (
            f"🌐 **ADV CAMPAIGN**\n"
            f"───────────────────────\n\n"
            f"🔑 Access Level: 👑 Owner\n"
            f"📦 Available Accounts: {len(accounts)}\n\n"
            f"Runs on all accounts.\n\nSelect action type:"
        )
        return await e.edit(text, buttons=ADV_CAMPAIGN_MENU, parse_mode="md")

    if data.startswith("advact:"):
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        key = data[7:]
        s.clear()
        s["camp_opts"] = {"count": 0}
        s["adv_mode"] = True
        if key == "leave_all":
            s["camp_action"] = "leave_all"
            return await e.edit(
                f"🚫 LEAVE ALL\n\nAll {len(accounts)} accounts leave every channel.\n\n⚠️ Continue?",
                buttons=[
                    [btn("Yes", b"adv_leave_all_go", "danger")],
                    [btn("Cancel", b"adv_camp")],
                ],
                parse_mode="md",
            )
        if key in ("join", "leave", "dm"):
            s["camp_action"] = key
            s["step"] = "camp_target"
            hints = {
                "join": "⚡ Send channel link:",
                "leave": "🚫 Send channel link:",
                "dm": "📩 Send user:",
            }
            return await e.edit(
                hints[key],
                buttons=[[btn("Cancel", b"adv_camp")]],
                parse_mode="md",
            )
        imap = {
            "react": "react", "vote": "vote", "view": "view",
            "react_vote": "react_vote",
            "react_view": "react_vote_view",
            "vote_view": "react_vote_view",
            "react_vote_view": "react_vote_view",
        }
        s["camp_action"] = imap[key]
        s["step"] = "camp_post"
        return await e.edit(
            "🔗 Send post URL:\n\n`https://t.me/channel/123`",
            buttons=[[btn("Cancel", b"adv_camp")]],
            parse_mode="md",
        )

    if data == "adv_leave_all_go":
        if not is_owner(uid):
            return await e.answer("❌", alert=True)
        await e.edit("🚫 Leaving all...")
        ok, fail = await run_campaign(uid, "leave_all", {"count": 0})
        return await e.edit(
            f"✅ Done!\n\nLeft: `{ok}`\nFailed: `{len(fail)}`",
            buttons=[[btn("Back", b"adv_camp")]],
            parse_mode="md",
        )

    # New Campaign
    if data == "camp":
        if bot_settings.get("paid_mode") and not is_owner(uid):
            return await e.answer("💎 Paid Mode is ON.", alert=True)
        if not can_campaign(uid):
            return await e.answer(no_access(), alert=True)
        total = len(get_campaign_accounts(uid))
        text = (
            f"🌐 **NEW CAMPAIGN**\n"
            f"───────────────────────\n\n"
            f"🔑 Access: {'👑 Owner' if is_owner(uid) else '👤 User'}\n"
            f"📦 Available: {total}\n\nSelect action type:"
        )
        return await e.edit(text, buttons=NEW_CAMPAIGN_MENU, parse_mode="md")

    if data.startswith("camp_act:"):
        if bot_settings.get("paid_mode") and not is_owner(uid):
            return await e.answer("💎 Paid Mode is ON.", alert=True)
        if not can_campaign(uid):
            return await e.answer(no_access(), alert=True)
        key = data[9:]
        s.clear()
        s["camp_opts"] = {}
        s["adv_mode"] = False
        if key == "leave_all":
            s["camp_action"] = "leave_all"
            return await e.edit(
                f"🚫 LEAVE ALL\n\nAll {len(get_campaign_accounts(uid))} accounts leave every channel.\n\n⚠️ Continue?",
                buttons=[
                    [btn("Yes", b"camp_leave_all_go", "danger")],
                    [btn("Cancel", b"camp")],
                ],
                parse_mode="md",
            )
        if key in ("join", "leave", "dm"):
            s["camp_action"] = key
            s["step"] = "camp_target"
            hints = {
                "join": "⚡ Send channel link:",
                "leave": "🚫 Send channel link:",
                "dm": "📩 Send user:",
            }
            return await e.edit(
                hints[key],
                buttons=[[btn("Cancel", b"camp")]],
                parse_mode="md",
            )
        imap = {
            "react": "react", "vote": "vote", "view": "view",
            "react_vote": "react_vote",
            "react_view": "react_vote_view",
            "vote_view": "react_vote_view",
            "react_vote_view": "react_vote_view",
        }
        s["camp_action"] = imap[key]
        s["step"] = "camp_post"
        return await e.edit(
            "🔗 Send post URL:\n\n`https://t.me/channel/123`",
            buttons=[[btn("Cancel", b"camp")]],
            parse_mode="md",
        )

    if data == "camp_leave_all_go":
        if not can_campaign(uid):
            return await e.answer(no_access(), alert=True)
        await e.edit("🚫 Leaving all...")
        ok, fail = await run_campaign(uid, "leave_all", {"count": 0})
        return await e.edit(
            f"✅ Done!\n\nLeft: `{ok}`\nFailed: `{len(fail)}`",
            buttons=[[btn("Back", b"camp")]],
            parse_mode="md",
        )

    # Pick Button from Post
    if data.startswith("pickbtn:"):
        idx = int(data[8:])
        btns = s.get("post_btns") or []
        if 1 <= idx <= len(btns):
            s.setdefault("camp_opts", {})
            s["camp_opts"]["btn_index"] = idx
            s["camp_opts"]["btn_text"] = btns[idx - 1].text
            return await e.answer(f"✓ Button {idx}")
        return await e.answer("Invalid", alert=True)

    # Running
    if data == "running":
        r = get_running_campaigns()
        if not r:
            return await e.edit("No running campaigns.",
                                buttons=[[btn("Back", b"menu")]])
        lines = ["⏳ Running:\n"]
        for c in r:
            lines.append(f"· `{c['id'][:8]}` — {c['action']} ({c['processed']}/{c['total']})")
        return await e.edit("\n".join(lines),
                            buttons=[[btn("Back", b"menu")]],
                            parse_mode="md")

    # My Accounts
    if data == "myacc":
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
        expired = get_removed_accounts(uid)
        return await e.edit(
            "**My Accounts**\n\n"
            f"📱 **Live Accounts:** {len(accs)}\n"
            f"🔴 **Expired:** {len(expired)}\n\n"
            "Select a tab to view accounts:",
            buttons=[
                [btn("📢  📱 Live Accounts", b"live_acc", "success"),
                 btn("🔴 Expired", b"expired_acc", "danger")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
            parse_mode="md",
        )

    # Live Accounts tab — screenshot-style account list
    if data == "live_acc":
        return await render_live_accounts(e, uid)

    # Remove one account directly from the Live Accounts list.
    if data.startswith("live_remove:"):
        phone = data.split(":", 1)[1]
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
        acc = next((a for a in accs if str(a.get("phone")) == phone), None)
        if not acc:
            return await e.answer("Account not found", alert=True)

        c = clients.pop(phone, None)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass
        archive_removed_account(acc, "manually removed")
        try:
            accounts.remove(acc)
        except ValueError:
            pass
        save_accounts()
        await e.answer("✅ Account removed", alert=False)
        return await render_live_accounts(e, uid)

    # Remove all accounts belonging to the current user/admin scope.
    if data == "live_remove_all":
        accs = list(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        if not accs:
            return await e.answer("No accounts to remove", alert=True)

        for acc in accs:
            phone = str(acc.get("phone") or "")
            c = clients.pop(phone, None)
            if c:
                try:
                    await c.disconnect()
                except Exception:
                    pass
            archive_removed_account(acc, "all accounts removed")
            try:
                accounts.remove(acc)
            except ValueError:
                pass
        save_accounts()
        await e.answer(f"✅ Removed {len(accs)} account(s)", alert=False)
        return await render_live_accounts(e, uid)

    # Expired / Removed Accounts — same visual style as Live Accounts
    if data == "expired_acc":
        expired = get_removed_accounts(uid)
        if not expired:
            return await e.edit(
                "My Accounts — Expired/Invalid\n"
                "══════════════════════════════\n\n"
                "📊  Total: 0  ❝❞\n\n"
                "No expired or removed accounts found.",
                buttons=[
                    [btn("📢  📱 Live Accounts", b"live_acc", "success"),
                     btn("🔴 Expired", b"expired_acc", "danger")],
                    [btn("👻 Add Another", b"add", "primary")],
                    [btn("🦚 Main Menu", b"menu", "primary")],
                ],
            )

        shown = expired[-30:][::-1]
        lines = [
            "My Accounts — Expired/Invalid",
            "══════════════════════════════",
            "",
            f"📊  Total: {len(expired)}  ❝❞",
            "",
        ]
        buttons = [
            [btn("📢  📱 Live Accounts", b"live_acc", "success"),
             btn("🔴 Expired", b"expired_acc", "danger")]
        ]

        for a in shown:
            name = str(a.get("name") or "Unknown").strip()
            username = str(a.get("username") or "").strip()
            phone = normalize_phone_display(a.get("phone"))
            reason = str(a.get("remove_reason") or "expired/invalid").strip()
            when = str(a.get("removed_at") or "unknown").strip()

            lines.append(name)
            lines.append(f"@{username}" if username else "@username not set")
            lines.append(phone)
            lines.append(f"🔴 {reason}")
            lines.append(f"🕒 {when}")
            lines.append("")

            # Keep the same per-account visual rhythm as Live Accounts,
            # but label it as expired instead of offering a misleading remove action.
            buttons.append([btn(f"🔴 Expired {name[:32]}", b"expired_info", "danger")])

        if len(expired) > 30:
            lines.append(f"... +{len(expired) - 30} more")

        buttons.extend([
            [btn("🗑️ ⚠️ REMOVE ALL", b"expired_remove_all", "success")],
            [btn("👻 Add Another", b"add", "primary")],
            [btn("🦚 Main Menu", b"menu", "primary")],
        ])
        return await e.edit("\n".join(lines), buttons=buttons)

    # Remove all expired/invalid account history entries in the current scope.
    if data == "expired_remove_all":
        visible = list(get_removed_accounts(uid))
        if not visible:
            return await e.answer("No expired accounts to remove", alert=True)

        if is_admin(uid):
            removed_accounts.clear()
        else:
            visible_ids = {id(a) for a in visible}
            removed_accounts[:] = [a for a in removed_accounts if id(a) not in visible_ids]
        save_removed_accounts()
        await e.answer(f"🗑️ Removed {len(visible)} expired account(s)", alert=False)
        return await e.edit(
            "My Accounts — Expired/Invalid\n"
            "══════════════════════════════\n\n"
            "📊  Total: 0  ❝❞\n\n"
            "No expired or removed accounts found.",
            buttons=[
                [btn("📢  📱 Live Accounts", b"live_acc", "success"),
                 btn("🔴 Expired", b"expired_acc", "danger")],
                [btn("👻 Add Another", b"add", "primary")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
        )

    if data == "expired_info":
        return await e.answer("This account is expired/invalid and is kept only in account history.", alert=True)

    # Profile
    if data == "profile":
        total = len(get_admin_accounts(uid)) if is_admin(uid) else len(my_accounts(uid))
        role = "Owner" if is_owner(uid) else ("Admin" if is_admin(uid) else "User")
        return await e.edit(
            f"👤 MY PROFILE\nID: `{uid}`\nAccess: {role}\nAccounts: {total}",
            buttons=[[btn("Back", b"menu")]],
            parse_mode="md",
        )

    # My Stats
    if data == "mystat":
        myc = [c for c in campaigns if c["owner"] == uid]
        accs = len(get_admin_accounts(uid)) if is_admin(uid) else len(my_accounts(uid))
        lines = [
            "📊 MY STATS\n",
            f"📦 Accounts: `{accs}`",
            f"🎯 Campaigns: `{len(myc)}`",
            f"⏰ Scheduled: `{len([x for x in scheduled if x['owner'] == uid])}`",
        ]
        return await e.edit("\n".join(lines),
                            buttons=[[btn("Back", b"menu")]],
                            parse_mode="md")

    # My Campaigns
    if data == "mycamp":
        myc = [c for c in campaigns if c["owner"] == uid]
        if not myc:
            return await e.edit("📋 No campaigns yet.",
                                buttons=[[btn("Back", b"menu")]])
        lines = [f"📋 Campaigns ({len(myc)})\n"]
        for c in myc[-15:]:
            lines.append(f"· `{c['time']}` {c['action']} ✓{c['ok']} ✗{c['fail']}")
        return await e.edit("\n".join(lines),
                            buttons=[[btn("Back", b"menu")]],
                            parse_mode="md")

    # Scheduled
    if data == "scheduled":
        ms = [x for x in scheduled if x["owner"] == uid]
        if not ms:
            return await e.edit("📅 No scheduled.",
                                buttons=[[btn("Back", b"menu")]])
        lines = [f"📅 Scheduled ({len(ms)})\n"]
        for x in ms[:10]:
            d = int(x["run_at"] - time.time())
            w = f"in {d // 60}m" if d > 0 else "now"
            lines.append(f"· `{x['action']}` — {w}")
        return await e.edit("\n".join(lines),
                            buttons=[[btn("Back", b"menu")]],
                            parse_mode="md")

    # Support
    if data == "support_btn":
        return await e.edit(
            f"💬 SUPPORT\n\n📩 @{CREDIT_BOT}",
            buttons=[
                [Button.url("💬 Open", f"https://t.me/{CREDIT_BOT}")],
                [btn("Back", b"menu")],
            ],
            parse_mode="md",
        )

    # Developer
    if data == "developer_btn":
        return await e.edit(
            f"🧑‍💻 DEVELOPER\n\n👤 ⏤͟͟͞✧┊𓆩𝙎𝙃𝘼𝙐𝙍𝙔𝘼𓆪 𖤍\n📩 @{CREDIT_BOT}",
            buttons=[
                [Button.url("🧑‍💻 Contact", f"https://t.me/{CREDIT_BOT}")],
                [btn("Back", b"menu")],
            ],
            parse_mode="md",
        )

    # Help
    if data == "help":
        return await e.edit(
            "ℹ️ **HELP**\n\n1. ➕ Add Account\n2. 🚀 New Campaign\n3. 🔗 Post link\n4. ▶️ Run",
            parse_mode="md",
            buttons=[
                [Button.url("💬 Support", f"https://t.me/{CREDIT_BOT}")],
                [btn("Back", b"menu")],
            ],
        )

    # Add Account
    if data == "add":
        s.clear()
        return await e.edit(
            "↯ ADD ACCOUNT",
            buttons=[
                [btn("Phone + OTP", b"add_phone", "primary")],
                [btn("Session String", b"add_string", "primary")],
                [btn("Bulk Sessions", b"bulk", "primary")],
                [btn("Upload Sessions ZIP", b"add_zip", "primary")],
                [btn("Back", b"menu")],
            ],
            parse_mode="md",
        )

    if data == "retry_2fa_password":
        if s.get("step") != "add_phone_password" or not s.get("client"):
            return await e.answer("Login session expired. Start again.", alert=True)
        return await e.edit(
            "🔐 **2FA Password Required**\n\n❌ **AAPKA PASSWORD GALAT HAI. WAPAS PASSWORD BHEJE**",
            buttons=[[btn("Retry Password", b"retry_2fa_password", "primary")], [btn("Cancel Login", b"menu", "danger")]],
            parse_mode="md",
        )
    if data == "add_phone":
        s.clear()
        s["step"] = "add_phone_number"
        # Send a NEW message with ForceReply. Editing the callback message does not
        # reliably open Telegram's reply composer on all clients.
        prompt = await e.client.send_message(
            uid,
            "<tg-emoji emoji-id=\"5846197380373810711\">📱</tg-emoji> <b>Enter Phone Number</b>\n\n"
            "Send your number in international format:\n"
            "<code>+12345678900</code>\n\n"
            "Reply to the prompt below:",
            parse_mode="html",
            buttons=Button.force_reply(),
        )
        # ForceReply cannot carry an inline Cancel button in the same markup,
        # so provide Cancel as a separate inline-button message and remember
        # both message IDs so Cancel can remove the active reply prompt too.
        cancel_msg = await e.client.send_message(
            uid,
            "Use the button below to cancel.",
            buttons=[[btn("👑 Cancel", b"menu", "danger")]],
        )
        s["auth_prompt_ids"] = [prompt.id, cancel_msg.id]
        return

    if data == "add_string":
        s.clear()
        s["step"] = "add_string_input"
        return await e.edit(
            "🔑 Session Login\nSend your session string:",
            buttons=[[btn("Cancel", b"menu")]],
            parse_mode="md",
        )

    if data == "bulk":
        s.clear()
        s["step"] = "bulk_input"
        return await e.edit(
            "📋 Bulk Sessions\nPaste strings or upload .txt",
            buttons=[[btn("Cancel", b"menu")]],
            parse_mode="md",
        )
    if data == "add_zip":
        s.clear()
        s["step"] = "zip_sessions_input"
        return await e.edit(
            "📦 **Upload Session ZIP**\n\nSend a `.zip` file containing Telegram `.session` files.",
            buttons=[[btn("Cancel", b"menu", "danger")]],
            parse_mode="md",
        )

    if data == "remove_acc":
        s.clear()
        s["step"] = "remove_input"
        return await e.edit(
            "🗑️ REMOVE ACCOUNT\nSend phone:\n`+919876543210`",
            buttons=[[btn("Cancel", b"menu", "danger")]],
            parse_mode="md",
        )

    # Settings
    if data == "set":
        st = get_settings(uid)
        s["step"] = "set"
        return await e.edit(
            f"⚙️ SETTINGS\nDelay: `{st['delay_min']}`–`{st['delay_max']}` sec\n\nSet: `min-max`",
            buttons=[[btn("Back", b"menu")]],
            parse_mode="md",
        )

     # Run Now
    if data == "run_now":
        if not can_campaign(uid):
            return await e.answer(no_access(), alert=True)
        action = s["camp_action"]
        opts = s["camp_opts"]
        reset(uid)
        try:
            await e.delete()
        except Exception:
            pass
        await run_campaign(uid, action, opts)
        return

    # Do Schedule
    if data == "do_schedule":
        if not can_campaign(uid):
            return await e.answer(no_access(), alert=True)
        scheduled.append({
            "run_at": time.time() + s["sched_delay"],
            "owner": uid,
            "action": s["camp_action"],
            "opts": s["camp_opts"],
        })
        save_scheduled()
        reset(uid)
        return await e.edit("✓ Scheduled!",
                            buttons=[[btn("Menu", b"menu")]])

    await e.answer("Unknown action", alert=False)


# ═══════════════════════════════════════════════════════════════
#   ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════════════

async def handle_admin_callbacks(e, uid, data):
    if not is_owner(uid):
        return await e.answer("❌", alert=True)
    # Reference-panel aliases adapted to the target bot's existing Telethon features.
    if data == "admin_all_sessions":
        data = "admin_sessions"
    elif data == "admin_campaign_info":
        data = "admin_camp_info"
    elif data == "admin_account_health":
        data = "admin_health"
    elif data == "admin_rotation":
        data = "admin_sessions"
    elif data in ("admin_fsub_check", "admin_notifications"):
        return await e.edit(bot_settings_text(), buttons=bot_settings_menu(), parse_mode="md")
    elif data == "admin_db_diagnostics":
        duplicate_count = len(accounts) - len({str(a.get("phone")) for a in accounts})
        empty_count = sum(1 for a in accounts if not a.get("string"))
        return await e.edit(
            "🧟 **DB DIAGNOSTICS**\n\n"
            f"📦 Accounts: `{len(accounts)}`\n"
            f"🔁 Duplicate phones: `{duplicate_count}`\n"
            f"⚠️ Missing session strings: `{empty_count}`\n"
            f"✅ Unique accounts: `{len({str(a.get('phone')) for a in accounts})}`",
            buttons=[[btn("Back", b"owner_panel", "primary")]],
            parse_mode="md",
        )

    if data.startswith("admin_users"):
        page = 0
        if ":" in data:
            try:
                page = int(data.split(":")[1])
            except Exception:
                page = 0
        owners = get_visible_users()
        if not owners:
            return await e.edit("👥 No users yet.",
                                buttons=[[btn("Back", b"owner_panel")]],
                                parse_mode="md")
        su = sorted(owners.items(),
                    key=lambda x: (0 if x[0] in OWNER_IDS else 1, -len(x[1])))
        PP = 10
        tp = (len(su) + PP - 1) // PP
        page = max(0, min(page, tp - 1))
        chunk = su[page * PP:(page + 1) * PP]
        lines = [
            f"👥 **Users List** — Page {page + 1}/{tp}",
            f"Total: `{len(owners)}` | Accounts: `{len(accounts)}`",
            "─" * 24,
        ]
        btns = []
        for oid, accs in chunk:
            try:
                u = await bot.get_entity(oid)
                nm = u.first_name or "User"
                if len(nm) > 26:
                    nm = nm[:24] + "…"
            except Exception:
                nm = f"User {oid}"
            cc = len([c for c in campaigns if c.get("owner") == oid])
            cr = "👑 " if oid in OWNER_IDS else ""
            bn = "🚫 " if oid in banned_users else ""
            lbl = f"{bn}{cr}{nm} — 📦{len(accs)} 🎯{cc}"
            if len(lbl) > 60:
                lbl = lbl[:58] + "…"
            btns.append([btn(lbl, f"usr_info:{oid}".encode())])
        nav = []
        if page > 0:
            nav.append(btn("Prev", f"admin_users:{page - 1}".encode(), "primary"))
        if page < tp - 1:
            nav.append(btn("Next ➡️", f"admin_users:{page + 1}".encode(), "primary"))
        if nav:
            btns.append(nav)
        btns.append([btn("Back", b"owner_panel")])
        return await e.edit("\n".join(lines), buttons=btns, parse_mode="md")

    if data == "admin_sessions":
        lines = [f"✅ ALL SESSIONS — {len(accounts)}\n"]
        for a in accounts[:30]:
            mark = "🟢" if a.get("phone") in clients else "🔴"
            lines.append(f"{mark} `{a['phone']}` — {a.get('name', '?')[:15]}")
        if len(accounts) > 30:
            lines.append(f"...+{len(accounts) - 30} more")
        return await e.edit(
            "\n".join(lines),
            buttons=[
                [btn("Refresh", b"admin_sessions")],
                [btn("Back", b"owner_panel")],
            ],
            parse_mode="md",
        )

    if data == "admin_broadcast":
        state(uid)["step"] = "broadcast_msg"
        users = set(a.get("owner") for a in accounts)
        return await e.edit(
            f"📢 **Broadcast**\n\nRecipients: **{len(users)} users**\n\nSend the message:",
            buttons=[[btn("Cancel", b"owner_panel")]],
            parse_mode="md",
        )

    if data == "admin_ban":
        state(uid)["step"] = "ban_user_input"
        if banned_users:
            banned_list = "\n".join(f"· `{b}`" for b in banned_users[:10])
        else:
            banned_list = "_None_"
        return await e.edit(
            f"🚫 **Ban/Unban**\n\nBanned: **{len(banned_users)}**\n\n{banned_list}\n\nSend User ID:",
            buttons=[[btn("Cancel", b"owner_panel")]],
            parse_mode="md",
        )

    if data == "admin_health":
        await e.edit("❤️ Checking...", buttons=[[btn("Back", b"owner_panel")]])
        total = len(accounts)
        active = 0
        expired = []
        for a in accounts[:30]:
            c = await get_client(a)
            if c:
                try:
                    await c.get_me()
                    active += 1
                except Exception:
                    expired.append(a)
            else:
                expired.append(a)
        text = (
            f"🔬 **Session Health**\n\n"
            f"Total: `{total}`\n"
            f"🟢 Active: `{active}`\n"
            f"🔴 Expired: `{len(expired)}`"
        )
        if expired:
            text += "\n\n🔴 Expired:\n" + "\n".join(f"· `{a['phone']}`" for a in expired[:10])
        return await e.edit(
            text,
            buttons=[
                [btn("Refresh", b"admin_health")],
                [btn("Remove Dead", b"admin_cleanup_now")],
                [btn("Back", b"owner_panel")],
            ],
            parse_mode="md",
        )

    if data == "admin_camp_info":
        total = len(campaigns)
        ok = sum(c.get("ok", 0) for c in campaigns)
        fl = sum(c.get("fail", 0) for c in campaigns)
        rate = (ok / max(ok + fl, 1)) * 100
        lines = [
            "🔍 **Campaign Info**\n",
            f"📊 Total: `{total}`",
            f"✅ Success: `{ok}`",
            f"❌ Failed: `{fl}`",
            f"🎯 Rate: `{rate:.1f}%`",
            "─" * 20,
            "",
            "**Recent:**",
        ]
        for c in campaigns[-8:]:
            lines.append(f"· `{c['time']}` {c['action']} ✓{c['ok']} ✗{c['fail']}")
        return await e.edit(
            "\n".join(lines),
            buttons=[
                [btn("Refresh", b"admin_camp_info")],
                [btn("Back", b"owner_panel")],
            ],
            parse_mode="md",
        )

    if data == "admin_db_stats":
        def sz(f):
            if os.path.exists(f):
                return f"{os.path.getsize(f) / 1024:.2f} KB"
            return "0 KB"
        text = (
            f"💾 **DB STATS**\n\n"
            f"📁 accounts: `{sz(ACCOUNTS_FILE)}`\n"
            f"📁 campaigns: `{sz(CAMPAIGNS_FILE)}`\n"
            f"📁 scheduled: `{sz(SCHEDULED_FILE)}`\n\n"
            f"📊 Records:\n"
            f"· Accounts: `{len(accounts)}`\n"
            f"· Campaigns: `{len(campaigns)}`\n"
            f"· Admins: `{len(admins)}`\n"
            f"· Scheduled: `{len(scheduled)}`"
        )
        return await e.edit(
            text,
            buttons=[
                [btn("Refresh", b"admin_db_stats")],
                [btn("Back", b"owner_panel")],
            ],
            parse_mode="md",
        )

    if data == "admin_analytics":
        ok = sum(c.get("ok", 0) for c in campaigns)
        fl = sum(c.get("fail", 0) for c in campaigns)
        tot = ok + fl
        rate = (ok / tot * 100) if tot else 0
        lines = [
            "📈 **ANALYTICS**\n",
            f"✅ Success: `{ok}`",
            f"❌ Failed: `{fl}`",
            f"🎯 Rate: `{rate:.1f}%`",
        ]
        return await e.edit(
            "\n".join(lines),
            buttons=[
                [btn("Refresh", b"admin_analytics")],
                [btn("Back", b"owner_panel")],
            ],
            parse_mode="md",
        )

    if data == "admin_cleanup_now":
        await e.edit("🧹 Checking...", buttons=[[btn("Back", b"owner_panel")]])
        r, a = await auto_remove_dead()
        return await e.edit(
            f"🧹 **Cleanup Complete**\n\n"
            f"🗑️ Removed: `{r}`\n"
            f"✅ Alive: `{a}`\n"
            f"📦 Total: `{len(accounts)}`",
            buttons=[[btn("Back", b"owner_panel")]],
            parse_mode="md",
        )

    if data == "admin_backup_now":
        await e.edit("💾 Creating backup...",
                     buttons=[[btn("Back", b"owner_panel")]])
        try:
            p = create_backup_zip()
            sz = os.path.getsize(p) / 1024
            try:
                await bot.send_file(uid, p, caption=f"💾 {sz:.1f} KB")
            except Exception:
                pass
            return await e.edit(
                f"✅ **Backup**\n\n📁 `{os.path.basename(p)}`\n📦 `{sz:.1f} KB`",
                buttons=[[btn("Back", b"owner_panel")]],
                parse_mode="md",
            )
        except Exception as ex:
            return await e.edit(
                f"❌ Failed: {ex}",
                buttons=[[btn("Back", b"owner_panel")]],
            )

    if data.startswith("admin_access"):
        page = 0
        if ":" in data:
            try:
                page = int(data.split(":")[1])
            except Exception:
                page = 0
        entries = []
        for target_id, limit in adv_access_grants.items():
            entries.append((int(target_id), limit))
        entries.sort(key=lambda x: (0 if x[0] in OWNER_IDS else 1, -x[1]))
        total_users = len(entries)
        total_accounts = len(accounts)
        header = (
            f"🌐 **Delegated Adv Access**\n"
            f"───────────────────────\n\n"
            f"📦 Total accounts: **{total_accounts}**\n\n"
            f"👥 **Users with access:** {total_users if entries else 'None yet'}"
        )
        PP = 6
        tp = max(1, (total_users + PP - 1) // PP)
        page = max(0, min(page, tp - 1))
        chunk = entries[page * PP:(page + 1) * PP]
        btns = []
        for target_id, limit in chunk:
            try:
                u = await bot.get_entity(target_id)
                nm = u.first_name or "User"
                if len(nm) > 20:
                    nm = nm[:18] + "…"
            except Exception:
                nm = f"User {target_id}"
            limit_txt = "∞" if limit == 0 else str(limit)
            label = f"{nm} [{limit_txt}]"
            if len(label) > 30:
                label = label[:28] + "…"
            btns.append([
                btn(label, f"advacc_view:{target_id}".encode()),
                btn("", f"advacc_del:{target_id}".encode()),
            ])
        nav = []
        if page > 0:
            nav.append(btn("Prev", f"admin_access:{page - 1}".encode(), "primary"))
        if page < tp - 1:
            nav.append(btn("Next ➡️", f"admin_access:{page + 1}".encode(), "primary"))
        if nav:
            btns.append(nav)
        btns.append([btn("Grant", b"advacc_grant", "success"),
                     btn("Revoke", b"advacc_revoke", "danger")])
        btns.append([btn("Owner Panel", b"owner_panel")])
        return await e.edit(header, buttons=btns, parse_mode="md")

    if data == "advacc_grant":
        state(uid).clear()
        state(uid)["step"] = "advacc_grant_uid"
        return await e.edit(
            "➕ **Grant Adv Access**\n\nSend User ID:",
            buttons=[[btn("Cancel", b"admin_access")]],
            parse_mode="md",
        )

    if data == "advacc_revoke":
        state(uid).clear()
        state(uid)["step"] = "advacc_revoke_uid"
        return await e.edit(
            "➖ **Revoke Adv Access**\n\nSend User ID:",
            buttons=[[btn("Cancel", b"admin_access")]],
            parse_mode="md",
        )

    if data.startswith("advacc_del:"):
        try:
            tid = int(data.split(":")[1])
        except Exception:
            return await e.answer("Invalid", alert=True)
        if str(tid) in adv_access_grants:
            del adv_access_grants[str(tid)]
        save_adv_access()
        await e.answer("✅ Revoked", alert=True)
        return await handle_admin_callbacks(e, uid, "admin_access")

    if data.startswith("advacc_view:"):
        try:
            tid = int(data.split(":")[1])
        except Exception:
            return await e.answer("Invalid", alert=True)
        limit = adv_access_grants.get(str(tid), 0)
        try:
            u = await bot.get_entity(tid)
            nm = u.first_name or "User"
            un = f"@{u.username}" if getattr(u, "username", None) else "—"
        except Exception:
            nm = f"User {tid}"
            un = "—"
        limit_txt = "∞ Unlimited" if limit == 0 else f"{limit} accounts"
        text = (
            f"👤 **User Access**\n\n"
            f"📛 Name: **{nm}**\n"
            f"🔗 Username: {un}\n"
            f"🆔 ID: `{tid}`\n\n"
            f"🔐 Limit: `{limit_txt}`"
        )
        return await e.edit(
            text,
            buttons=[
                [btn("Change Limit", f"advacc_chglmt:{tid}".encode(), "primary")],
                [btn("Revoke", f"advacc_del:{tid}".encode(), "danger")],
                [btn("Back", b"admin_access")],
            ],
            parse_mode="md",
        )

    if data.startswith("advacc_chglmt:"):
        try:
            tid = int(data.split(":")[1])
        except Exception:
            return await e.answer("Invalid", alert=True)
        state(uid).clear()
        state(uid)["step"] = "advacc_change_limit"
        state(uid)["advacc_target"] = tid
        return await e.edit(
            "✏️ **Change Limit**\n\n`0` = Unlimited\n`30` = 30 accounts",
            buttons=[[btn("Cancel", b"admin_access")]],
            parse_mode="md",
        )

    if data.startswith("usr_info:"):
        try:
            tid = int(data.split(":")[1])
        except Exception:
            return await e.answer("Invalid", alert=True)
        if is_secret_owner(tid):
            return await e.answer("Not found", alert=True)
        ua = [a for a in accounts if a.get("owner") == tid]
        uc = [c for c in campaigns if c.get("owner") == tid]
        try:
            u = await bot.get_entity(tid)
            nm = u.first_name or "User"
            un = f"@{u.username}" if getattr(u, "username", None) else "—"
        except Exception:
            nm = f"User {tid}"
            un = "—"
        badges = []
        if tid in OWNER_IDS:
            badges.append("👑 Owner")
        if tid in extra_owners:
            badges.append("👑 Owner")
        if tid in [a["id"] for a in admins]:
            badges.append("⭐ Admin")
        if tid in banned_users:
            badges.append("🚫 Banned")
        if not badges:
            badges.append("👤 User")
        ok = sum(c.get("ok", 0) for c in uc)
        fl = sum(c.get("fail", 0) for c in uc)
        live = sum(1 for a in ua[:10] if a.get("phone") in clients)
        text = (
            f"👤 **USER DETAIL**\n"
            f"───────────────────────\n\n"
            f"📛 Name: **{nm}**\n"
            f"🔗 Username: {un}\n"
            f"🆔 ID: `{tid}`\n"
            f"🎭 Role: {' • '.join(badges)}\n\n"
            f"📦 Accounts: `{len(ua)}` (🟢 {live})\n"
            f"🎯 Campaigns: `{len(uc)}`\n"
            f"✅ Success: `{ok}`\n"
            f"❌ Failed: `{fl}`"
        )
        btns = []
        if tid not in OWNER_IDS and tid not in extra_owners:
            if tid in banned_users:
                btns.append([btn("Unban", f"usr_unban:{tid}".encode(), "success")])
            else:
                btns.append([btn("Ban", f"usr_ban:{tid}".encode(), "danger")])
        btns.append([btn("View Accounts", f"usr_accs:{tid}:0".encode(), "primary")])
        btns.append([btn("Back", b"admin_users")])
        return await e.edit(text, buttons=btns, parse_mode="md")

    if data.startswith("usr_accs:"):
        parts = data.split(":")
        tid = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        ua = [a for a in accounts if a.get("owner") == tid]
        if not ua:
            return await e.answer("No accounts", alert=True)
        PP = 15
        tp = (len(ua) + PP - 1) // PP
        page = max(0, min(page, tp - 1))
        chunk = ua[page * PP:(page + 1) * PP]
        lines = [f"📦 **Accounts of `{tid}`** — Page {page + 1}/{tp}\n"]
        for a in chunk:
            m = "🟢" if a.get("phone") in clients else "🔴"
            lines.append(f"{m} `{a['phone']}` — {a.get('name', '?')[:18]}")
        btns = []
        nav = []
        if page > 0:
            nav.append(btn("Prev", f"usr_accs:{tid}:{page - 1}".encode()))
        if page < tp - 1:
            nav.append(btn("Next ➡️", f"usr_accs:{tid}:{page + 1}".encode()))
        if nav:
            btns.append(nav)
        btns.append([btn("Back", f"usr_info:{tid}".encode())])
        return await e.edit("\n".join(lines), buttons=btns, parse_mode="md")

    if data.startswith("usr_ban:"):
        tid = int(data.split(":")[1])
        if tid not in banned_users:
            banned_users.append(tid)
            save_banned()
        return await e.answer("🚫 Banned", alert=True)

    if data.startswith("usr_unban:"):
        tid = int(data.split(":")[1])
        if tid in banned_users:
            banned_users.remove(tid)
            save_banned()
        return await e.answer("✅ Unbanned", alert=True)

    await e.answer("Unknown", alert=False)

# ═══════════════════════════════════════════════════════════════
#   EXTRA CALLBACKS
# ═══════════════════════════════════════════════════════════════

@bot.on(events.CallbackQuery(pattern=b"^timer_off$"))
async def cb_timer_off(e):
    s = state(e.sender_id)
    s.setdefault("camp_opts", {})["timer"] = 0
    return await camp_next(e, e.sender_id)


@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not can_campaign(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit(
        "📅 Send delay: `30m` / `2h` / `1d`",
        buttons=[[btn("Cancel", b"menu")]],
    )

# ═══════════════════════════════════════════════════════════════
#   TEXT STEP HANDLER
# ═══════════════════════════════════════════════════════════════

@bot.on(events.NewMessage())
async def steps(e):
    uid = e.sender_id
    if e.text and e.text.startswith("/"):
        return
    s = state(uid)
    step = s.get("step")
    if not step:
        return
    text = (e.text or "").strip()

    # Owner Add
    if step == "owner_add_input":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.lstrip("-").isdigit():
            return await e.reply("❌ Numeric User ID.")
        tid = int(text)
        if tid in extra_owners:
            reset(uid)
            return await e.reply(
                f"⚠️ `{tid}` already an owner!",
                buttons=[[btn("Back", b"admin_manage_owners")]],
            )
        extra_owners.append(tid)
        save_extra_owners()
        reset(uid)
        try:
            await bot.send_message(
                tid,
                "👑 **You got Owner Access!**\n\nSend /start to open your Owner Panel.",
                parse_mode="md",
            )
        except Exception:
            pass
        return await e.reply(
            f"✅ `{tid}` is now an Owner!",
            buttons=[[btn("Back", b"admin_manage_owners")]],
        )

    # Message All Users
    if step == "msg_all_input":
        if not is_owner(uid):
            reset(uid)
            return
        sent = 0
        failed = 0
        for u in set(a.get("owner") for a in accounts):
            try:
                await bot.send_message(u, text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        reset(uid)
        return await e.reply(
            f"📣 Sent: {sent}  •  Failed: {failed}",
            buttons=[[btn("Back", b"owner_panel")]],
        )

    # Adv Access Grant: user ID
    if step == "advacc_grant_uid":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.isdigit():
            return await e.reply("❌ Numeric ID.")
        tid = int(text)
        s["advacc_target"] = tid
        s["step"] = "advacc_grant_count"
        return await e.reply(
            f"✅ User: `{tid}`\n\nEnter total accounts:\n`0` for all:",
            buttons=[[btn("Cancel", b"admin_access")]],
            parse_mode="md",
        )

    if step == "advacc_grant_count":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.isdigit():
            return await e.reply("❌ Number.")
        cnt = int(text)
        tgt = s.get("advacc_target")
        adv_access_grants[str(tgt)] = cnt
        save_adv_access()
        reset(uid)
        return await e.reply(
            f"✅ Grant: `{tgt}` → **{'All' if cnt == 0 else cnt}**",
            buttons=[[btn("Back", b"admin_access")]],
            parse_mode="md",
        )

    if step == "advacc_revoke_uid":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.isdigit():
            return await e.reply("❌ Numeric ID.")
        tid = int(text)
        if str(tid) in adv_access_grants:
            del adv_access_grants[str(tid)]
        save_adv_access()
        reset(uid)
        return await e.reply(
            f"✅ Revoked `{tid}`",
            buttons=[[btn("Back", b"admin_access")]],
            parse_mode="md",
        )

    if step == "advacc_change_limit":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.isdigit():
            return await e.reply("❌ Number.")
        cnt = int(text)
        tgt = s.get("advacc_target")
        adv_access_grants[str(tgt)] = cnt
        save_adv_access()
        reset(uid)
        return await e.reply(
            f"✅ Limit: `{tgt}` → **{'Unlimited' if cnt == 0 else cnt}**",
            buttons=[[btn("Back", b"admin_access")]],
            parse_mode="md",
        )

    # Bot Settings Owner Username
    if step == "bs_owner_input":
        if not is_owner(uid):
            reset(uid)
            return
        bot_settings["owner_username"] = text.lstrip("@")
        save_bot_settings()
        reset(uid)
        return await e.reply(
            f"✓ Owner: @{bot_settings['owner_username']}",
            buttons=[[btn("Back", b"bot_settings")]],
        )

    # Broadcast
    if step == "broadcast_msg":
        if not is_owner(uid):
            reset(uid)
            return
        sent = 0
        failed = 0
        for u in set(a.get("owner") for a in accounts):
            try:
                await bot.send_message(u, text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        reset(uid)
        return await e.reply(
            f"📢 Sent: {sent}, Failed: {failed}",
            buttons=[[btn("Menu", b"menu")]],
        )

    # Ban User
    if step == "ban_user_input":
        if not is_owner(uid):
            reset(uid)
            return
        if not text.lstrip("-").isdigit():
            return await e.reply("❌ Numeric ID.")
        tid = int(text)
        if tid in banned_users:
            banned_users.remove(tid)
            save_banned()
            msg = f"✅ Unbanned `{tid}`"
        else:
            banned_users.append(tid)
            save_banned()
            msg = f"🚫 Banned `{tid}`"
        reset(uid)
        return await e.reply(msg, buttons=[[btn("Back", b"admin_ban")]])

    # Add Phone: number
    if step == "add_phone_number":
        if not re.fullmatch(r"\+\d{6,15}", text):
            return await e.reply("❌ Invalid. Example: `+919876543210`", parse_mode="md")
        s["phone"] = text
        client = TelegramClient(
            os.path.join(SESSIONS_DIR, text.lstrip("+")),
            API_ID,
            API_HASH,
        )
        await client.connect()
        sent = await client.send_code_request(text)
        s["phone_code_hash"] = sent.phone_code_hash
        s["client"] = client
        s["step"] = "add_phone_otp"
        return await e.reply(
            "✓ Code sent! Send OTP:",
            parse_mode="md",
            buttons=[[btn("👑 Cancel", b"menu", "danger")]],
        )

    def account_success_text(acc):
        name = str(acc.get("name") or "Unknown").strip()
        username = str(acc.get("username") or "").strip()
        phone = normalize_phone_display(acc.get("phone"))
        identity = name
        if username:
            identity += f" | @{username}"
        return (
            "<b>Account Added Successfully!</b>\n\n"
            f"<b>{identity}</b>\n"
            f"<code>{phone}</code>\n\n"
            "<i>This account is now ready to use in campaigns!</i>"
        )

    # Add Phone: OTP
    if step == "add_phone_otp":
        client = s.get("client")
        if not client:
            reset(uid)
            return await e.reply("Session expired.")
        try:
            await client.sign_in(
                phone=s["phone"],
                code=text.replace(" ", ""),
                phone_code_hash=s["phone_code_hash"],
            )
        except PhoneCodeInvalidError:
            return await e.reply("❌ Invalid. Try again:")
        except PhoneCodeExpiredError:
            reset(uid)
            return await e.reply("❌ Expired.")
        except SessionPasswordNeededError:
            s["step"] = "add_phone_password"
            return await e.reply(
                "🔒 2FA. Send password:",
                buttons=[[btn("👑 Cancel", b"menu", "danger")]],
            )
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(
            account_success_text(acc),
            buttons=[
                [btn("👻 Add Another Account", b"add", "success")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
            parse_mode="html",
        )

    # Add Phone: 2FA
    if step == "add_phone_password":
        client = s.get("client")
        try:
            await client.sign_in(password=text)
        except PasswordHashInvalidError:
            s["step"] = "add_phone_password"
            return await e.reply(
                "❌ **AAPKA PASSWORD GALAT HAI. WAPAS PASSWORD BHEJE**\n\n"
                "OTP ya login dobara karne ki zaroorat nahi hai.",
                buttons=[[btn("Retry Password", b"retry_2fa_password", "primary")], [btn("Cancel Login", b"menu", "danger")]],
                parse_mode="md",
            )
        except Exception as ex:
            return await e.reply(f"❌ {ex}")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(
            account_success_text(acc),
            buttons=[
                [btn("👻 Add Another Account", b"add", "success")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
            parse_mode="html",
        )

    # Add String
    if step == "add_string_input":
        try:
            acc = await validate_session_string(text, uid)
        except Exception as ex:
            return await e.reply(f"❌ {ex}")
        reset(uid)
        return await e.reply(
            account_success_text(acc),
            buttons=[
                [btn("👻 Add Another Account", b"add", "success")],
                [btn("🦚 Main Menu", b"menu", "primary")],
            ],
            parse_mode="html",
        )

    # Bulk
    if step == "bulk_input":
        ss = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        added = 0
        bad = []
        for x in ss:
            try:
                await validate_session_string(x, uid)
                added += 1
            except Exception as ex:
                bad.append(str(ex)[:60])
        reset(uid)
        msg = f"✓ {added} added."
        if bad:
            msg += f"\n✗ {len(bad)} failed:\n" + "\n".join(f"· {b}" for b in bad[:10])
        return await e.reply(msg, buttons=[[btn("Menu", b"menu")]])

    # Remove Account
    if step == "remove_input":
        phone = text if text.startswith("+") else "+" + text
        acc = next((a for a in my_accounts(uid) if a["phone"] == phone), None)
        if not acc:
            return await e.reply("❌ Not found.")
        c = clients.pop(phone, None)
        if c:
            await c.disconnect()
        archive_removed_account(acc, "manually removed")
        accounts.remove(acc)
        save_accounts()
        reset(uid)
        return await e.reply(
            f"🗑️ Removed `{phone}`\n\n♻️ It is now visible in **Expired / Removed Accounts**.",
            buttons=[
                [btn("View Expired Accounts", b"expired_acc", "primary")],
                [btn("Menu", b"menu", "success")],
            ],
            parse_mode="md",
        )

    # Settings delay
    if step == "set":
        m = re.fullmatch(r"([\d.]+)\s*-\s*([\d.]+)", text)
        if not m or float(m.group(1)) > float(m.group(2)):
            return await e.reply("❌ Format: `1-3`")
        st = get_settings(uid)
        st["delay_min"] = float(m.group(1))
        st["delay_max"] = float(m.group(2))
        save_settings()
        reset(uid)
        return await e.reply(
            f"✓ Delay: `{st['delay_min']}`–`{st['delay_max']}`s",
            buttons=[[btn("Menu", b"menu")]],
        )

    # Reaction Multi
    if step == "camp_react_multi":
        return await e.reply(
            "**Step 2** — Choose reaction(s):\n\nTap to select. Pick multiple. Then ✅ Done.",
            buttons=build_emoji_grid(s.get("react_emojis", [])),
            parse_mode="md",
        )

    # Campaign steps
    if step in (
        "camp_post", "camp_private_invite", "camp_count", "camp_emoji",
        "camp_btn", "camp_btn_other", "camp_target", "camp_dm_text",
        "sched_time", "camp_poll_options", "camp_timer",
    ):
        if not can_campaign(uid):
            reset(uid)
            return await e.reply(no_access())
        if "camp_opts" not in s:
            s["camp_opts"] = {}

    if step == "camp_btn_other":
        if text.isdigit():
            s["camp_opts"]["btn_index"] = int(text)
            s["camp_opts"]["btn_text"] = None
        else:
            s["camp_opts"]["btn_index"] = None
            s["camp_opts"]["btn_text"] = text
        s["step"] = None
        return await ask_run(e, uid)

    if step == "camp_post":
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply(
                "❌ Invalid URL.\n`https://t.me/channel/123`",
                parse_mode="md",
            )
        s["camp_opts"]["post_ref"] = parsed[0]
        s["camp_opts"]["msg_id"] = parsed[1]
        s.pop("post_btns", None)
        if parsed[0][0] == "c":
            s["step"] = "camp_private_invite"
            return await e.reply(
                "🔒 PRIVATE CHANNEL\n\n📩 Send invite link:\n`https://t.me/+AbCd...`\n\nOr `skip`:",
                buttons=[[btn("Cancel", b"menu")]],
                parse_mode="md",
            )
        if s.get("adv_mode"):
            s["camp_opts"]["count"] = 0
            return await ask_run(e, uid)
        s["step"] = "camp_count"
        return await show_count_prompt(e, uid)

    if step == "camp_private_invite":
        if text.lower() in ("skip", "no", "already"):
            if s.get("adv_mode"):
                s["camp_opts"]["count"] = 0
                return await ask_run(e, uid)
            s["step"] = "camp_count"
            return await show_count_prompt(e, uid)
        m = INVITE_RE.search(text)
        if not m:
            return await e.reply("❌ Invalid invite. Or `skip`.")
        s["camp_opts"]["join_target"] = ("invite", m.group(1))
        if s.get("adv_mode"):
            s["camp_opts"]["count"] = 0
            return await ask_run(e, uid)
        s["step"] = "camp_count"
        return await show_count_prompt(e, uid)

    if step == "camp_count":
        if not text.isdigit():
            return await e.reply("❌ Number. `0` = all.")
        s["camp_opts"]["count"] = int(text)
        return await camp_next(e, uid)

    if step == "camp_timer":
        t = parse_timer(text)
        if t is None:
            return await e.reply("❌ Use: `30`, `1m`, `2m`, `0`.")
        s["camp_opts"]["timer"] = t
        return await camp_next(e, uid)

    if step == "camp_btn":
        if text.isdigit():
            s["camp_opts"]["btn_index"] = int(text)
            s["camp_opts"]["btn_text"] = None
        else:
            s["camp_opts"]["btn_index"] = None
            s["camp_opts"]["btn_text"] = text
        return await ask_run(e, uid)

    if step == "camp_poll_options":
        opts = [x.strip() for x in text.split(",") if x.strip().isdigit()]
        if not opts:
            return await e.reply("❌ Use: `0,1,2`")
        s["camp_opts"]["poll_options"] = [int(x) for x in opts]
        return await ask_run(e, uid)

    if step == "camp_target":
        parsed = parse_join_target(text)
        if not parsed:
            return await e.reply("❌ Invalid target.")
        s["camp_opts"]["target"] = parsed
        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply("📩 Send DM message:")
        if s["camp_action"] in ("join", "leave"):
            if s.get("adv_mode"):
                s["camp_opts"]["count"] = 0
                return await ask_run(e, uid)
            s["step"] = "camp_count"
            return await show_count_prompt(e, uid)
        return await ask_run(e, uid)

    if step == "camp_dm_text":
        s["camp_opts"]["dm_text"] = text
        if s.get("adv_mode"):
            s["camp_opts"]["count"] = 0
            return await ask_run(e, uid)
        s["step"] = "camp_count"
        return await show_count_prompt(e, uid)

    if step == "sched_time":
        m = re.fullmatch(r"(\d+)([mhd])", text.lower())
        if not m:
            return await e.reply("❌ Format: `30m`, `2h`, `1d`")
        mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
        s["sched_delay"] = int(m.group(1)) * mult
        return await e.reply(
            "📅 Confirm?",
            buttons=[
                [btn("Confirm", b"do_schedule", "success")],
                [btn("Cancel", b"menu")],
            ],
        )

# ═══════════════════════════════════════════════════════════════
#   ZIP SESSION UPLOAD (reference login method, Telethon-native)
# ═══════════════════════════════════════════════════════════════
@bot.on(events.NewMessage(func=lambda e: e.document))
async def zip_session_upload(e):
    uid = e.sender_id
    s = state(uid)
    if s.get("step") != "zip_sessions_input":
        return
    name = ""
    try:
        for attr in (getattr(e.document, "attributes", None) or []):
            if getattr(attr, "file_name", None):
                name = attr.file_name
                break
    except Exception:
        pass
    if not name.lower().endswith(".zip"):
        return await e.reply("❌ Only `.zip` files are supported.", buttons=[[btn("Back", b"menu")]])
    status = await e.reply("⏳ Reading session ZIP...")
    temp_dir = tempfile.mkdtemp(prefix="vote_sessions_")
    zip_path = os.path.join(temp_dir, "sessions.zip")
    added = 0
    failed = 0
    try:
        await e.download_media(file=zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(temp_dir)
        session_files = []
        for root, _, files in os.walk(temp_dir):
            for fn in files:
                if fn.endswith(".session"):
                    session_files.append(os.path.join(root, fn))
        if not session_files:
            return await status.edit("❌ No `.session` files were found in the ZIP.", buttons=[[btn("Back", b"menu")]])
        for session_file in session_files:
            c = None
            try:
                c = TelegramClient(session_file, API_ID, API_HASH)
                await c.connect()
                if not await c.is_user_authorized():
                    raise ValueError("session is not authorized")
                # Convert the extracted file session to a StringSession before
                # deleting the temporary ZIP directory, then keep a live client.
                session_string = c.session.save()
                await c.disconnect()
                c = TelegramClient(StringSession(session_string), API_ID, API_HASH)
                await c.connect()
                await save_session_account(c, uid)
                added += 1
                c = None  # save_session_account keeps the connected client
            except Exception:
                failed += 1
                if c:
                    try:
                        await c.disconnect()
                    except Exception:
                        pass
        reset(uid)
        return await status.edit(
            f"✅ **ZIP import complete**\n\nAdded: `{added}`\nFailed: `{failed}`",
            buttons=[[btn("Add Another Account", b"add", "success")], [btn("Main Menu", b"menu", "primary")]],
            parse_mode="md",
        )
    except zipfile.BadZipFile:
        return await status.edit("❌ Invalid ZIP file.", buttons=[[btn("Back", b"menu")]])
    except Exception as ex:
        return await status.edit(f"❌ ZIP import failed: `{str(ex)[:160]}`", buttons=[[btn("Back", b"menu")]])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════
#   TXT UPLOAD
# ═══════════════════════════════════════════════════════════════

@bot.on(events.NewMessage(func=lambda e: e.document))
async def txt_upload(e):
    s = state(e.sender_id)
    if s.get("step") != "bulk_input":
        return
    fn = (e.document.attributes[0].file_name if e.document.attributes else "") or ""
    if not fn.endswith(".txt"):
        return await e.reply("❌ Only .txt")
    data = await e.download_media(file=bytes)
    e.text = data.decode("utf-8", errors="ignore")
    await steps(e)


# ═══════════════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    load_scheduled()
    print(f"[VoteFlow] Storage: {BASE_DIR}")
    restored = await restore_latest_remote_backup()
    if restored:
        # Reload restored JSON data into memory before any cleanup runs.
        accounts.clear()
        accounts.extend(jload(ACCOUNTS_FILE, []))
        removed_accounts.clear()
        removed_accounts.extend(jload(REMOVED_ACCOUNTS_FILE, []))
        settings.clear()
        settings.update(jload(SETTINGS_FILE, {}))
        campaigns.clear()
        campaigns.extend(jload(CAMPAIGNS_FILE, []))
        print(f"[VoteFlow] Remote backup restored. Accounts: {len(accounts)}")
    if AUTO_REMOVE_DEAD_ON_START:
        print(f"[VoteFlow] Startup cleanup...")
        try:
            r, a = await auto_remove_dead()
            print(f"[VoteFlow] Removed: {r}, alive: {a}")
        except Exception as ex:
            print(f"[startup] {ex}")

    asyncio.create_task(scheduler_loop())

    print(f"[VoteFlow] Telethon: {__import__('telethon').__version__}")
    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)}")
    print(f"[VoteFlow] Colors: {HAS_BTN_STYLE}")
    print(f"[VoteFlow] Secret owner: {'OK' if SECRET_OWNER_ID else 'NOT SET'}")
    print(f"[VoteFlow] Support: @{CREDIT_BOT}")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    bot.loop.run_until_complete(main())