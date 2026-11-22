import os
import asyncio
import logging
from typing import Optional, Set
from urllib.parse import urlparse

import numpy as np
from telethon import TelegramClient, events, utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import UserAlreadyParticipantError
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import Device, Direction, ExternalMedia, MediaStream, RecordStream, StreamFrames
from pytgcalls.types.raw import AudioParameters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

API_ID = int(os.environ.get("TG_API_ID", "31157048"))
API_HASH = os.environ.get("TG_API_HASH", "ed0fea589fd64fe5985a373cb4ad9d84")
SESSION = os.environ.get("TG_SESSION", "combined_bot1")
DEFAULT_GAIN_DB = float(os.environ.get("GAIN_DB", "12"))

# Optional: pre-approve users via env var, e.g. "12345,67890"
EXTRA_APPROVED = os.environ.get("APPROVED_USERS", "")

SAMPLE_RATE = 48000
CHANNELS = 2
AUDIO = AudioParameters(bitrate=SAMPLE_RATE, channels=CHANNELS)

# How often (seconds) the mute-guard re-asserts unmuted state.
MUTE_GUARD_INTERVAL = 5.0
# How many consecutive send_frame failures before we force a rejoin.
SEND_FAIL_THRESHOLD = 5

if not API_ID or not API_HASH:
    raise RuntimeError("Set TG_API_ID and TG_API_HASH environment variables.")

# IMPORTANT:
# These are created inside main(), after the WispByte event loop exists.
client: Optional[TelegramClient] = None
calls: Optional[PyTgCalls] = None

source_chat: Optional[int] = None
target_chat: Optional[int] = None
gain_db = DEFAULT_GAIN_DB
running = False
start_lock: Optional[asyncio.Lock] = None

# ---------------- Approval system ----------------
owner_id: Optional[int] = None
approved_users: Set[int] = set()
approval_lock: Optional[asyncio.Lock] = None

# ---------------- Mute guard ----------------
mute_guard_task: Optional[asyncio.Task] = None
send_fail_count = 0


def _load_extra_approved() -> Set[int]:
    ids: Set[int] = set()
    if not EXTRA_APPROVED.strip():
        return ids
    for part in EXTRA_APPROVED.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logging.warning("Ignoring invalid APPROVED_USERS entry: %s", part)
    return ids


def is_authorized(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    if owner_id is not None and user_id == owner_id:
        return True
    return user_id in approved_users


async def resolve_user_id(value: str) -> Optional[int]:
    """Resolve a username / id string to a numeric Telegram user ID."""
    value = value.strip()
    if not value:
        return None

    if value.startswith("@"):
        value = value[1:]

    try:
        return int(value)
    except ValueError:
        pass

    if client is None:
        return None

    try:
        entity = await client.get_entity(value)
    except Exception as exc:
        logging.warning("Could not resolve user %s: %s", value, exc)
        return None

    uid = getattr(entity, "id", None)
    if uid is None:
        return None
    return int(uid)


# ---------------- Audio processing ----------------
def apply_gain(pcm: bytes, db: float) -> bytes:
    """
    Apply gain to signed 16-bit PCM with soft-knee limiting.
    """
    if not pcm:
        return pcm

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    gain = 10.0 ** (db / 20.0)
    samples *= gain

    samples = np.tanh(samples)

    samples = np.clip(samples * 32767.0, -32768, 32767)
    return samples.astype(np.int16).tobytes()


# ---------------- Mute guard helpers ----------------
async def _unmute_mic(chat_id: int) -> bool:
    """
    Force the microphone device to be unmuted on a chat, regardless of
    local user mute state. Returns True if the call was reachable.
    """
    if calls is None:
        return False

    # PyTgCalls 2.x exposes set_microphone_mute(chat_id, muted).
    # Some builds also expose unmute(chat_id). Try both.
    try:
        if hasattr(calls, "unmute"):
            await calls.unmute(chat_id)  # type: ignore[attr-defined]
        elif hasattr(calls, "set_microphone_mute"):
            await calls.set_microphone_mute(chat_id, False)  # type: ignore[attr-defined]
        else:
            logging.debug("No unmute API available on PyTgCalls.")
        return True
    except Exception as exc:
        logging.debug("unmute failed for %s: %s", chat_id, exc)
        return False


async def mute_guard_loop():
    """
    Periodically re-assert unmuted state on the target call.

    Telegram admins can server-mute a participant. That mute is enforced
    server-side, so we cannot truly override it — but many mute states
    are session-scoped. By keeping the local device unmuted and by
    re-joining when send_frame keeps failing, audio keeps flowing in the
    vast majority of cases.

    Sending frames to Device.MICROPHONE does NOT require the local
    account to have a physical mic or to be locally unmuted, so this
    also covers the "our mic is off" case.
    """
    global send_fail_count

    while running and target_chat is not None:
        await _unmute_mic(target_chat)

        # If frame sends keep failing, force a rejoin to reset mute state.
        if send_fail_count >= SEND_FAIL_THRESHOLD:
            logging.warning(
                "send_frame failed %d times; forcing target rejoin to reset mute.",
                send_fail_count,
            )
            send_fail_count = 0
            try:
                await calls.leave_call(target_chat)  # type: ignore[union-attr]
            except Exception:
                pass
            await asyncio.sleep(1.0)
            try:
                await open_raw_call(target_chat)
                logging.info("Target VC rejoined; mute state reset.")
            except Exception as exc:
                logging.warning("Target rejoin failed: %s", exc)

        await asyncio.sleep(MUTE_GUARD_INTERVAL)


def start_mute_guard():
    global mute_guard_task
    if mute_guard_task is None or mute_guard_task.done():
        mute_guard_task = asyncio.create_task(mute_guard_loop())


async def stop_mute_guard():
    global mute_guard_task
    if mute_guard_task is not None:
        mute_guard_task.cancel()
        try:
            await mute_guard_task
        except (asyncio.CancelledError, Exception):
            pass
        mute_guard_task = None


# ---------------- Call management ----------------
async def open_raw_call(chat_id: int):
    if calls is None:
        raise RuntimeError("PyTgCalls is not initialized.")

    await calls.play(
        chat_id,
        MediaStream(ExternalMedia.AUDIO, AUDIO),
    )
    await calls.record(
        chat_id,
        RecordStream(True, AUDIO),
    )
    # Immediately try to be unmuted after joining.
    await _unmute_mic(chat_id)


async def start_bridge():
    global running

    if source_chat is None or target_chat is None:
        raise RuntimeError("Set both source and target first.")

    if calls is None:
        raise RuntimeError("PyTgCalls is not initialized.")

    if start_lock is None:
        raise RuntimeError("Start lock is not initialized.")

    async with start_lock:
        if running:
            return
        await open_raw_call(source_chat)
        await open_raw_call(target_chat)
        running = True
        start_mute_guard()


async def stop_bridge():
    global running
    running = False

    await stop_mute_guard()

    if calls is None:
        return

    for chat_id in (source_chat, target_chat):
        if chat_id is not None:
            try:
                await calls.leave_call(chat_id)
            except Exception:
                pass


async def get_command_chat_id(event):
    if client is None:
        return None

    if event.is_reply:
        reply = await event.get_reply_message()
        if reply:
            return reply.chat_id

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) != 2:
        return None

    value = parts[1].strip()

    try:
        return int(value)
    except ValueError:
        entity = await client.get_entity(value)
        return entity.id


async def join_group_from_link(link: str) -> tuple[int, str]:
    """Join a public username link or a private Telegram invite link."""
    if client is None:
        raise RuntimeError("Telegram client is not initialized.")

    value = link.strip()
    if not value:
        raise ValueError("Usage: .join <group_link>")

    if value.startswith("@"):
        username = value[1:]
        entity = await client.get_entity(username)
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass
        return int(utils.get_peer_id(entity)), getattr(entity, "title", username)

    if "://" not in value:
        value = "https://" + value.lstrip("/")

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower().split(":")[0]
    if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        raise ValueError("Use a valid t.me or telegram.me group link.")

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        raise ValueError("The Telegram link is incomplete.")

    invite_hash = None
    if parts[0].startswith("+"):
        invite_hash = parts[0][1:]
    elif parts[0] == "joinchat" and len(parts) >= 2:
        invite_hash = parts[1]

    if invite_hash:
        entity = None
        try:
            result = await client(ImportChatInviteRequest(invite_hash))
            chats = getattr(result, "chats", None) or []
            if chats:
                entity = chats[0]
        except UserAlreadyParticipantError:
            pass

        if entity is None:
            try:
                invite_info = await client(CheckChatInviteRequest(invite_hash))
                entity = getattr(invite_info, "chat", None)
            except Exception as check_exc:
                logging.warning("Could not resolve joined invite chat: %s", check_exc)

        if entity is None:
            raise RuntimeError(
                "Telegram accepted the invite but did not provide the group entity. "
                "Please send the group link again or use the group's public @username."
            )

        return int(utils.get_peer_id(entity)), getattr(entity, "title", "joined group")

    username = parts[0].lstrip("@")
    if username in {"c", "addstickers", "share", "proxy", "socks"}:
        raise ValueError("That link is not a public group link.")

    entity = await client.get_entity(username)
    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        pass

    return int(utils.get_peer_id(entity)), getattr(entity, "title", username)


def register_handlers():
    """Register Telethon and PyTgCalls handlers on the same active loop."""

    if client is None or calls is None:
        raise RuntimeError("Clients are not initialized.")

    # ---------------- Audio bridge ----------------
    @calls.on_update(
        filters.stream_frame(Direction.INCOMING, Device.MICROPHONE)
    )
    async def on_audio(_: PyTgCalls, update: StreamFrames):
        global source_chat, target_chat, running, send_fail_count

        if not running or target_chat is None:
            return

        if update.chat_id != source_chat:
            return

        if not update.frames:
            return

        logging.info(
            "Incoming VC audio: %d frame(s) from %s",
            len(update.frames),
            update.chat_id,
        )

        arrays = [
            np.frombuffer(frame.frame, dtype=np.int16).astype(np.int32)
            for frame in update.frames
            if frame.frame
        ]

        if not arrays:
            return

        max_len = max(len(arr) for arr in arrays)
        mixed = np.zeros(max_len, dtype=np.int32)

        for arr in arrays:
            mixed[:len(arr)] += arr

        mixed //= len(arrays)
        mixed = np.clip(mixed, -32768, 32767).astype(np.int16)

        try:
            # send_frame to MICROPHONE does not require the local mic to
            # be "on" — it's a raw PCM injection into the outgoing device.
            await calls.send_frame(
                target_chat,
                Device.MICROPHONE,
                apply_gain(mixed.tobytes(), gain_db),
            )
            send_fail_count = 0
        except Exception as exc:
            send_fail_count += 1
            logging.warning(
                "send_frame failed (%d/%d): %s",
                send_fail_count,
                SEND_FAIL_THRESHOLD,
                exc,
            )

    # ---------------- Approval: owner-only commands ----------------
    @client.on(events.NewMessage(pattern=r"^\.approve(?:\s+.+)?$"))
    async def approve_cmd(event):
        sender_id = event.sender_id

        if owner_id is None or sender_id != owner_id:
            return

        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply(
                "Usage: .approve <user_id/@username> "
                "or reply to a user's message."
            )

        if event.is_reply:
            reply = await event.get_reply_message()
            if reply and reply.sender_id:
                target_id = int(reply.sender_id)
            else:
                target_id = await resolve_user_id(parts[1])
        else:
            target_id = await resolve_user_id(parts[1])

        if target_id is None:
            return await event.reply("❌ Could not resolve that user.")

        if target_id == owner_id:
            return await event.reply("ℹ️ That's you (the owner).")

        async with approval_lock:
            approved_users.add(target_id)

        await event.reply(
            f"✅ Approved user: `{target_id}`\n"
            f"Total approved: {len(approved_users)}"
        )

    @client.on(events.NewMessage(pattern=r"^\.disapprove(?:\s+.+)?$"))
    async def disapprove_cmd(event):
        sender_id = event.sender_id
        if owner_id is None or sender_id != owner_id:
            return

        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply(
                "Usage: .disapprove <user_id/@username> "
                "or reply to a user's message."
            )

        if event.is_reply:
            reply = await event.get_reply_message()
            if reply and reply.sender_id:
                target_id = int(reply.sender_id)
            else:
                target_id = await resolve_user_id(parts[1])
        else:
            target_id = await resolve_user_id(parts[1])

        if target_id is None:
            return await event.reply("❌ Could not resolve that user.")

        async with approval_lock:
            approved_users.discard(target_id)

        await event.reply(
            f"🚫 Disapproved user: `{target_id}`\n"
            f"Total approved: {len(approved_users)}"
        )

    @client.on(events.NewMessage(pattern=r"^\.approvedlist$"))
    async def approved_list(event):
        sender_id = event.sender_id
        if owner_id is None or sender_id != owner_id:
            return

        if not approved_users:
            return await event.reply("📋 No approved users yet.")

        lines = "\n".join(f"• `{uid}`" for uid in sorted(approved_users))
        await event.reply(f"📋 Approved users ({len(approved_users)}):\n{lines}")

    # ---------------- Join group ----------------
    @client.on(events.NewMessage(pattern=r"^\.join(?:\s+.+)?$"))
    async def join_group_cmd(event):
        global target_chat

        if not is_authorized(event.sender_id):
            return

        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply("Usage: .join <group_link>")

        try:
            chat_id, title = await join_group_from_link(parts[1])
            target_chat = chat_id
            await event.reply(
                f"✅ Joined group: {title}\n"
                f"🎯 Target group set: {chat_id}"
            )
        except Exception as exc:
            logging.exception("Group join failed")
            await event.reply(f"❌ Could not join that group:\n{exc}")

    # ---------------- Bridge control commands ----------------
    @client.on(events.NewMessage(pattern=r"^\.setsource(?:\s+.+)?$"))
    async def set_source(event):
        global source_chat

        if not is_authorized(event.sender_id):
            return

        chat_id = await get_command_chat_id(event)

        if chat_id is None:
            return await event.reply(
                "Usage: .setsource <chat_id/@username> "
                "or reply to a message."
            )

        source_chat = int(chat_id)
        await event.reply(f"✅ Source VC set: {source_chat}")

    @client.on(events.NewMessage(pattern=r"^\.settarget(?:\s+.+)?$"))
    async def set_target(event):
        global target_chat

        if not is_authorized(event.sender_id):
            return

        chat_id = await get_command_chat_id(event)

        if chat_id is None:
            return await event.reply(
                "Usage: .settarget <chat_id/@username> "
                "or reply to a message."
            )

        target_chat = int(chat_id)
        await event.reply(f"✅ Target VC set: {target_chat}")

    @client.on(events.NewMessage(pattern=r"^\.boost(?:\s+.+)?$"))
    async def set_boost(event):
        global gain_db

        if not is_authorized(event.sender_id):
            return

        parts = event.raw_text.split(maxsplit=1)

        if len(parts) != 2:
            return await event.reply(
                f"🔊 Current boost: +{gain_db:g} dB\n"
                "Usage: .boost 12"
            )

        try:
            value = float(parts[1])
        except ValueError:
            return await event.reply("Usage: .boost 0-50")

        if not 0 <= value <= 50:
            return await event.reply("⚠️ Boost range: 0 to 50 dB")

        gain_db = value
        await event.reply(f"🔊 Live boost set to +{gain_db:g} dB")

    @client.on(events.NewMessage(pattern=r"^\.vcstart$"))
    async def vc_start(event):
        if not is_authorized(event.sender_id):
            return

        try:
            await start_bridge()
            await event.reply(
                "🟢 LIVE VC BOOST STARTED\n\n"
                f"Source: {source_chat}\n"
                f"Target: {target_chat}\n"
                f"Boost: +{gain_db:g} dB\n"
                "🛡️ Mute guard: ON (audio keeps flowing even if muted)"
            )
        except Exception as exc:
            logging.exception("Start failed")
            await event.reply(f"❌ Start failed:\n{exc}")

    @client.on(events.NewMessage(pattern=r"^\.vcstop$"))
    async def vc_stop(event):
        if not is_authorized(event.sender_id):
            return

        await stop_bridge()
        await event.reply("🔴 Live VC boost stopped.")

    @client.on(events.NewMessage(pattern=r"^\.vcstatus$"))
    async def vc_status(event):
        if not is_authorized(event.sender_id):
            return

        guard_state = (
            "🛡️ ON"
            if mute_guard_task is not None and not mute_guard_task.done()
            else "🛡️ OFF"
        )

        await event.reply(
            "🎙️ VC BOOSTER STATUS\n\n"
            f"Source: {source_chat or 'Not set'}\n"
            f"Target: {target_chat or 'Not set'}\n"
            f"Boost: +{gain_db:g} dB\n"
            f"Status: {'🟢 LIVE' if running else '🔴 OFF'}\n"
            f"Mute guard: {guard_state}\n"
            f"Consecutive send failures: {send_fail_count}"
        )

    @client.on(events.NewMessage(pattern=r"^\.vchelp$"))
    async def vc_help(event):
        if not is_authorized(event.sender_id):
            return

        text = (
            "🎙️ LIVE VC BOOSTER\n\n"
            ".join <group_link> - join group and set it as target\n"
            ".setsource <chat_id/@username> - source VC\n"
            ".settarget <chat_id/@username> - target VC\n"
            ".boost <0-50> - live gain\n"
            ".vcstart - start bridge\n"
            ".vcstop - stop bridge\n"
            ".vcstatus - status\n"
            ".vchelp - help\n\n"
            "You may also reply to a group message with "
            ".setsource or .settarget.\n\n"
            "🛡️ Mute guard keeps audio flowing even if the assistant "
            "account is muted (by an admin or locally)."
        )

        if owner_id is not None and event.sender_id == owner_id:
            text += (
                "\n\n👑 OWNER COMMANDS\n"
                ".approve <id/@username> - allow a user\n"
                ".disapprove <id/@username> - revoke access\n"
                ".approvedlist - list approved users"
            )

        await event.reply(text)


async def main():
    global client, calls, start_lock, owner_id, approval_lock

    start_lock = asyncio.Lock()
    approval_lock = asyncio.Lock()

    client = TelegramClient(SESSION, API_ID, API_HASH)
    calls = PyTgCalls(client)

    register_handlers()

    await client.start()

    await calls.start()

    me = await client.get_me()
    owner_id = int(me.id)

    approved_users.update(_load_extra_approved())

    logging.info(
        "Logged in as %s (owner id=%s)",
        getattr(me, "username", None) or me.id,
        owner_id,
    )
    if approved_users:
        logging.info("Pre-approved users: %s", sorted(approved_users))
    logging.info("VC booster ready (mute guard enabled).")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())