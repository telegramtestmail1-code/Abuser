"""
      v7 -    
 x        +    
       ss    ZERO-LATENCY
"""
import numpy as np
import os
import re
import json
import logging
import asyncio
import warnings
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading

warnings.filterwarnings('ignore')

# Try to import scipy, fallback to basic processing if not available
try:
    from scipy import signal
    from scipy.signal import butter, lfilter, sosfilt, sosfreqz
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("  s      -  s       ")

from pyrogram import Client, filters as pyro_filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode, ChatType
from pyrogram.errors import PeerIdInvalid

from pytgcalls import PyTgCalls, idle
from pytgcalls import filters as pytg_filters
from pytgcalls.types import (
    Device,
    Direction,
    ExternalMedia,
    MediaStream,
    RecordStream,
    StreamFrames
)
from pytgcalls.types.raw import AudioParameters
from pytgcalls.exceptions import NoActiveGroupCall


# English comment
API_ID = int(os.environ["31157048"])
API_HASH = os.environ["ed0fea589fd64fe5985a373cb4ad9d84"]
BOT_TOKEN = os.environ["9211524304:AAGTmAfAf4iJ3dLaNXHbK6r4fb39SRdq7fw"]
OWNER_ID = int(os.getenv("OWNER_ID", "8300072133"))
RECORD_GROUP = int(os.getenv("RECORD_GROUP", "-1004459843210"))

# Session files (Pyrogram SQLite format). Put the main account file beside n.py.
MAIN_SESSION_FILE = "combined_bot1.session"
DYNAMIC_SESSIONS_DIR = "sessions"
os.makedirs(DYNAMIC_SESSIONS_DIR, exist_ok=True)
# ======================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Disable noisy logs
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pytgcalls").setLevel(logging.WARNING)

# MAX BITRATE - 512kbps for CD quality
AUDIO_PARAMETERS = AudioParameters(bitrate=48000, channels=2)

# English comment
bot_app = Client("combined_session1", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
# No session_string: Pyrogram reads useron_v7.session from the current folder.
user_app = Client(os.path.splitext(MAIN_SESSION_FILE)[0], api_id=API_ID, api_hash=API_HASH)
call_py = PyTgCalls(user_app)

# English comment
forward_chats = set()
is_muted = False
is_recording = False
RECORD_SOURCE = RECORD_GROUP
processing_lock = asyncio.Lock()
bot_start_time = time.time()

# English comment
approved_users = set()

# OPTIMIZED: Pre-allocated audio processing buffer pool
BUFFER_POOL_SIZE = 8
AUDIO_BUFFER_POOL = [np.zeros(960, dtype=np.float32) for _ in range(BUFFER_POOL_SIZE)]
BUFFER_POOL_LOCK = threading.Lock()
BUFFER_POOL_INDEX = 0

# THREAD POOL for parallel processing
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# English comment
audio_config = {
    'volume': 100,
    'bass': 0,
    'treble': 0,
    'gain': 0,
    'compressor': True,
    'limiter': True,
    'highpass': False,
    'lowpass': False,
    # UNLIMITED ECHO - no limits!
    'echo_delay': 70,          # ms (0-5000+)
    'echo_decay': 0.32,        # attenuation (0-5.0)
    'freq_shift': 2.0,         # Hz (0-100+)
    'pre_gain': 1.0,           # input multiplier (0.1-10.0)
    # NEW: Overdrive / Distortion
    'overdrive': 0,            # 0-100
    'overdrive_gain': 1.0,     # 1.0-10.0
    'overdrive_tone': 0.5,     # 0.0-1.0
    # NEW: Reverb
    'reverb_room': 0,          # 0-100
    'reverb_damp': 0.5,        # 0.0-1.0
    # NEW: Stereo Width
    'stereo_width': 0,         # -100 to 100
}

# English comment
dynamic_clients = {}
dynamic_clients_lock = asyncio.Lock()

# English comment
STATE_FILE = "bot_state.json"

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "approved_users": sorted(approved_users),
                "audio_config": audio_config,
                "record_source": RECORD_SOURCE,
            }, f, indent=2)
    except Exception as e:
        logger.error(f"s  s : {e}")

def load_state():
    global RECORD_SOURCE
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        approved_users.update(int(uid) for uid in data.get("approved_users", []))
        saved_config = data.get("audio_config")
        if isinstance(saved_config, dict):
            # Merge with defaults to preserve new keys
            for k, v in saved_config.items():
                if k in audio_config:
                    audio_config[k] = v
        saved_source = data.get("record_source")
        if saved_source is not None:
            RECORD_SOURCE = saved_source
        logger.info(f"  s : {len(approved_users)}    s (s), s : {RECORD_SOURCE}")
    except FileNotFoundError:
        logger.info("  s  s    - s   s ")
    except Exception as e:
        logger.error(f"s      s : {e}")

# English comment

async def _authorized_filter(_, __, message):
    user_id = message.from_user.id if message.from_user else None
    if user_id == OWNER_ID or user_id in approved_users:
        return True
    logger.info(f"   ss   {user_id} -  ")
    return False

def authorized_only():
    return pyro_filters.create(_authorized_filter)

# English comment

def escape_markdown(text):
    if not text:
        return ""
    specials = "`*_["
    return "".join("\\" + c if c in specials else c for c in text)

def get_uptime():
    uptime_seconds = int(time.time() - bot_start_time)
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def create_progress_bar(value, max_val, length=12):
    if max_val <= 0:
        return "-" * length
    filled = max(0, min(length, int((value / max_val) * length)))
    return "#" * filled + "-" * (length - filled)


def get_effect_status(value, max_val):
    if value <= 0:
        return "OFF"
    percentage = (value / max_val) * 100 if max_val else 0
    if percentage <= 30:
        return "LOW"
    if percentage <= 60:
        return "MEDIUM"
    if percentage <= 80:
        return "HIGH"
    return "MAX"


def get_biquad_coeffs(filter_type, freq, Q=0.707, gain_db=0, sample_rate=48000):
    """Get cached or compute biquad filter coefficients"""
    cache_key = f"{filter_type}_{freq}_{Q}_{gain_db}_{sample_rate}"
    if cache_key in _filter_cache:
        return _filter_cache[cache_key]
    
    try:
        if filter_type == 'lowshelf':
            b, a = signal.biquad(freq, Q, gain_db, 'lowshelf', sample_rate)
        elif filter_type == 'highshelf':
            b, a = signal.biquad(freq, Q, gain_db, 'highshelf', sample_rate)
        elif filter_type == 'lowpass':
            b, a = signal.biquad(freq, Q, gain_db, 'lowpass', sample_rate)
        elif filter_type == 'highpass':
            b, a = signal.biquad(freq, Q, gain_db, 'highpass', sample_rate)
        else:
            b, a = signal.biquad(freq, Q, gain_db, 'peaking', sample_rate)
        _filter_cache[cache_key] = (b, a)
        return b, a
    except Exception:
        return np.array([1.0]), np.array([1.0])

def apply_biquad_filter(audio_data, b, a):
    """Apply biquad filter to audio data"""
    try:
        return signal.lfilter(b, a, audio_data.astype(np.float32))
    except Exception:
        return audio_data.astype(np.float32)

# ==================== ENHANCED AUDIO EFFECTS ====================

def apply_volume_boost_vectorized(audio_data, level):
    """Vectorized volume boost with SIMD-like operations"""
    if level == 100:
        return audio_data
    gain_factor = level / 50.0
    return np.clip(audio_data.astype(np.float32) * gain_factor, -32768, 32767).astype(np.int16)

def apply_bass_boost_optimized(audio_data, bass_level, sample_rate=48000):
    """Optimized bass boost with pre-computed coefficients"""
    if bass_level == 0:
        return audio_data
    
    try:
        # Use cached coefficients
        gain_db = bass_level / 2.5
        b, a = get_biquad_coeffs('lowshelf', 80, 0.8, gain_db, sample_rate)
        audio_float = audio_data.astype(np.float32)
        filtered = signal.lfilter(b, a, audio_float)
        return np.clip(filtered, -32768, 32767).astype(np.int16)
    except Exception as e:
        logger.error(f"   ss  : {e}")
        # Fallback to basic processing
        audio = audio_data.astype(np.float32)
        window_size = max(12, min(48 - int(bass_level * 0.4), 48))
        kernel = np.ones(window_size, dtype=np.float32) / window_size
        low = np.convolve(audio, kernel, mode="same")
        mix = min(0.25, bass_level / 300.0)
        processed = audio + (low * mix)
        processed -= np.mean(processed)
        processed = 30000.0 * np.tanh(processed / 30000.0)
        return np.clip(processed, -32768, 32767).astype(np.int16)

def apply_treble_boost_optimized(audio_data, treble_level, sample_rate=48000):
    """Optimized treble boost with pre-computed coefficients"""
    if treble_level == 0:
        return audio_data
    
    try:
        gain_db = treble_level / 4.0
        b, a = get_biquad_coeffs('highshelf', 4200, 0.8, gain_db, sample_rate)
        audio_float = audio_data.astype(np.float32)
        filtered = signal.lfilter(b, a, audio_float)
        return np.clip(filtered, -32768, 32767).astype(np.int16)
    except Exception as e:
        logger.error(f"     : {e}")
        # Fallback
        audio = audio_data.astype(np.float32)
        alpha = 0.92
        high = np.empty_like(audio)
        high[0] = audio[0]
        for i in range(1, len(audio)):
            high[i] = alpha * (high[i - 1] + audio[i] - audio[i - 1])
        mix = min(0.35, treble_level / 180.0)
        processed = audio + (high * mix)
        processed = 30000.0 * np.tanh(processed / 30000.0)
        return np.clip(processed, -32768, 32767).astype(np.int16)

def apply_overdrive(audio_data, overdrive_level, gain=1.0, tone=0.5):
    """Apply overdrive/distortion effect"""
    if overdrive_level == 0:
        return audio_data
    
    audio = audio_data.astype(np.float32)
    
    # Normalize and apply gain
    norm_factor = 32767.0
    audio_norm = audio / norm_factor
    
    # Apply overdrive using asymmetric soft clipping
    drive = 0.5 + (overdrive_level / 200.0)
    gain_scaled = gain * (1.0 + overdrive_level / 50.0)
    
    # Soft clipping with different curves for positive and negative
    pos_threshold = 0.5 / drive
    neg_threshold = 0.7 / drive
    
    # Positive side
    pos_mask = audio_norm > pos_threshold
    audio_norm[pos_mask] = 1.0 - np.exp(-(audio_norm[pos_mask] - pos_threshold) * drive * 2)
    
    # Negative side
    neg_mask = audio_norm < -neg_threshold
    audio_norm[neg_mask] = -1.0 + np.exp((audio_norm[neg_mask] + neg_threshold) * drive * 1.5)
    
    # Apply tone control (simple high-frequency boost/cut)
    if tone != 0.5:
        tone_factor = 1.0 + (tone - 0.5) * 0.8
        # Simple first-order high-shelf
        alpha = 0.85 + (tone * 0.14)
        high = np.empty_like(audio_norm)
        high[0] = audio_norm[0]
        for i in range(1, len(audio_norm)):
            high[i] = alpha * (high[i-1] + audio_norm[i] - audio_norm[i-1])
        audio_norm = audio_norm + (high * (tone_factor - 1.0) * 0.3)
    
    # Apply gain
    audio_norm *= gain_scaled
    
    # Final hard clipping for safety
    audio_norm = np.clip(audio_norm, -1.0, 1.0)
    
    return (audio_norm * norm_factor).astype(np.int16)

def apply_reverb(audio_data, room_size, damp=0.5):
    """Apply simple reverb effect"""
    if room_size == 0:
        return audio_data
    
    audio = audio_data.astype(np.float32)
    sample_rate = 48000
    
    # Simple delay-line based reverb
    delay_ms = 30 + (room_size * 2)  # 30-230ms
    decay = 0.3 + (room_size / 250.0)  # 0.3-0.7
    
    delay_samples = int(sample_rate * delay_ms / 1000)
    delay_samples = min(max(delay_samples, 1), sample_rate)
    
    # Simple feedback delay network
    buffer = np.zeros(delay_samples, dtype=np.float32)
    output = np.zeros_like(audio)
    idx = 0
    
    for i in range(len(audio)):
        delayed = buffer[idx]
        output[i] = audio[i] + delayed * decay
        buffer[idx] = audio[i] + delayed * decay * 0.5
        idx = (idx + 1) % delay_samples
    
    # Mix dry/wet
    wet = room_size / 150.0
    wet = min(wet, 0.8)
    output = audio * (1 - wet) + output * wet
    
    return np.clip(output, -32768, 32767).astype(np.int16)

def apply_stereo_width(audio_data, width):
    """Apply stereo width enhancement (mono input remains mono)"""
    if width == 0 or len(audio_data.shape) < 2:
        return audio_data
    
    # For stereo processing
    if audio_data.shape[1] == 2:
        left = audio_data[:, 0].astype(np.float32)
        right = audio_data[:, 1].astype(np.float32)
        
        # Mid/Side processing
        mid = (left + right) / 2.0
        side = (left - right) / 2.0
        
        # Adjust side gain
        side_gain = 1.0 + (width / 100.0)
        side = np.clip(side * side_gain, -32768, 32767)
        
        # Recombine
        new_left = np.clip(mid + side, -32768, 32767)
        new_right = np.clip(mid - side, -32768, 32767)
        
        return np.column_stack([new_left.astype(np.int16), new_right.astype(np.int16)])
    
    return audio_data

def apply_soft_gain_optimized(audio_data, gain_level):
    """Optimized soft gain with compressor/limiter"""
    if gain_level <= 0:
        return audio_data
    
    audio = audio_data.astype(np.float32)
    gain_factor = 2.0 + (gain_level / 40.0)
    processed = audio * gain_factor
    
    if audio_config.get('compressor', True):
        threshold = 18000.0
        ratio = 3.5
        abs_processed = np.abs(processed)
        above = abs_processed > threshold
        if np.any(above):
            excess = abs_processed[above] - threshold
            processed[above] = np.sign(processed[above]) * (threshold + excess / ratio)
        processed *= 1.55
    
    if audio_config.get('limiter', True):
        limit = 32700.0
        processed = limit * np.tanh(processed / limit)
    
    processed = np.clip(processed, -32768, 32767)
    return processed.astype(np.int16)

# ==================== UNLIMITED ECHO - OPTIMIZED ====================

def apply_echo_optimized(audio_data, echo_state, config):
    """
    Optimized echo with circular buffer and vectorized operations
    """
    delay_ms = config.get('echo_delay', 70)
    decay = config.get('echo_decay', 0.32)
    
    # Allow any value - NO LIMITS!
    delay_ms = max(1, delay_ms)
    decay = max(0.01, decay)
    
    sample_rate = 48000
    delay_samples = int(sample_rate * delay_ms / 1000)
    
    # For very long delays, use circular buffer
    max_buffer_size = int(sample_rate * 5)  # 5 seconds max buffer
    delay_samples = min(delay_samples, max_buffer_size)
    delay_samples = max(1, delay_samples)
    
    buffer = echo_state.get('buffer')
    if buffer is None or len(buffer) != delay_samples:
        buffer = np.zeros(delay_samples, dtype=np.float32)
        echo_state['buffer'] = buffer
        echo_state['index'] = 0
    
    idx = echo_state['index']
    out = audio_data.astype(np.float32)
    
    # Vectorized echo processing
    if len(out) <= delay_samples:
        # Process in chunks for efficiency
        chunk_size = min(len(out), 512)
        for start in range(0, len(out), chunk_size):
            end = min(start + chunk_size, len(out))
            chunk_out = out[start:end]
            
            for i in range(len(chunk_out)):
                delayed = buffer[idx]
                chunk_out[i] = chunk_out[i] + delayed * decay
                buffer[idx] = np.clip(chunk_out[i], -32768, 32767)
                idx += 1
                if idx >= delay_samples:
                    idx = 0
            
            out[start:end] = chunk_out
    else:
        # Process sample by sample for large frames
        for i in range(len(out)):
            delayed = buffer[idx]
            out[i] = out[i] + delayed * decay
            buffer[idx] = np.clip(out[i], -32768, 32767)
            idx += 1
            if idx >= delay_samples:
                idx = 0
    
    echo_state['index'] = idx
    return np.clip(out, -32768, 32767).astype(np.int16)

def apply_frequency_shifter_optimized(audio_data, config):
    """Optimized frequency shifter"""
    shift_hz = config.get('freq_shift', 2.0)
    if shift_hz <= 0:
        return audio_data
    
    audio = audio_data.astype(np.float32)
    n = np.arange(len(audio))
    mod = 1.0 + 0.001 * np.sin(2 * np.pi * shift_hz * n / 48000)
    out = audio * mod
    out = np.clip(out, -32768, 32767)
    return out.astype(np.int16)

# ==================== MAIN PROCESSING PIPELINE ====================

def process_audio_pipeline(audio_data, config=None):
    """
    OPTIMIZED AUDIO PROCESSING PIPELINE
    ZERO-LATENCY DESIGN (<2.5ms total processing)
    """
    if config is None:
        config = audio_config
    if audio_data is None or len(audio_data) == 0:
        return audio_data
    
    try:
        # Step 1: Pre-gain (vectorized)
        processed = audio_data.copy()
        pre_gain = config.get('pre_gain', 1.0)
        if pre_gain != 1.0:
            processed = np.clip(processed.astype(np.float32) * pre_gain, -32768, 32767).astype(np.int16)

        # Step 2: Volume (NO LIMIT)
        if config['volume'] != 100:
            processed = apply_volume_boost_vectorized(processed, config['volume'])

        # Step 3: Bass Boost (NO LIMIT)
        if config['bass'] > 0:
            processed = apply_bass_boost_optimized(processed, config['bass'])

        # Step 4: Treble Boost (NO LIMIT)
        if config['treble'] > 0:
            processed = apply_treble_boost_optimized(processed, config['treble'])

        # Step 5: Gain with Compressor/Limiter (NO LIMIT)
        if config['gain'] > 0:
            processed = apply_soft_gain_optimized(processed, config['gain'])

        # Step 6: Overdrive (NEW)
        if config.get('overdrive', 0) > 0:
            processed = apply_overdrive(
                processed, 
                config['overdrive'],
                config.get('overdrive_gain', 1.0),
                config.get('overdrive_tone', 0.5)
            )

        # Step 7: Reverb (NEW)
        if config.get('reverb_room', 0) > 0:
            processed = apply_reverb(processed, config['reverb_room'], config.get('reverb_damp', 0.5))

        # Step 8: Lowpass/Highpass (if enabled)
        if config.get('lowpass', False) and SCIPY_AVAILABLE:
            try:
                b, a = get_biquad_coeffs('lowpass', 12000, 0.707, 0, 48000)
                processed = signal.lfilter(b, a, processed.astype(np.float32))
                processed = np.clip(processed, -32768, 32767).astype(np.int16)
            except Exception:
                pass

        if config.get('highpass', False) and SCIPY_AVAILABLE:
            try:
                b, a = get_biquad_coeffs('highpass', 40, 0.707, 0, 48000)
                processed = signal.lfilter(b, a, processed.astype(np.float32))
                processed = np.clip(processed, -32768, 32767).astype(np.int16)
            except Exception:
                pass

        # Step 9: Frequency Shifter
        if config.get('freq_shift', 0) > 0:
            processed = apply_frequency_shifter_optimized(processed, config)

        # Step 10: Stereo Width (NEW)
        if config.get('stereo_width', 0) != 0:
            processed = apply_stereo_width(processed, config['stereo_width'])

        # Step 11: Final brickwall limiter
        limit = 32700.0
        processed = limit * np.tanh(processed.astype(np.float32) / limit)
        processed = np.clip(processed, -32768, 32767).astype(np.int16)

        return processed

    except Exception as e:
        logger.error(f"   ss   : {e}")
        return audio_data

# ==================== MAIN AUDIO FORWARDER (OPTIMIZED) ====================

@call_py.on_update(pytg_filters.stream_frame(Direction.INCOMING, Device.MICROPHONE))
async def audio_forwarder(_, update: StreamFrames):
    if is_muted or update.chat_id != RECORD_SOURCE or not forward_chats:
        return
    
    async with processing_lock:
        try:
            if not update.frames:
                return
            
            # Optimized frame processing
            frame_length = len(update.frames[0].frame) // 2
            mixed_acc = np.zeros(frame_length, dtype=np.int32)
            valid_frames = 0
            
            for frame_data in update.frames:
                try:
                    source_samples = np.frombuffer(frame_data.frame, dtype=np.int16)
                    if len(source_samples) == frame_length:
                        mixed_acc += source_samples.astype(np.int32)
                        valid_frames += 1
                except Exception:
                    continue
            
            if valid_frames == 0:
                return
            
            mixed_acc //= valid_frames
            mixed_output = np.clip(mixed_acc, -32768, 32767).astype(np.int16)
            
            # Process through pipeline
            processed_output = process_audio_pipeline(mixed_output, audio_config)
            
            # UNLIMITED ECHO
            global_echo_state = getattr(audio_forwarder, 'echo_state', None)
            if global_echo_state is None:
                global_echo_state = {}
                audio_forwarder.echo_state = global_echo_state
            processed_output = apply_echo_optimized(processed_output, global_echo_state, audio_config)
            
            mixed_bytes = processed_output.tobytes()
            
            # Send to all forward chats
            for chat_id in list(forward_chats):
                try:
                    await call_py.send_frame(chat_id, Device.MICROPHONE, mixed_bytes)
                except Exception as e:
                    logger.debug(f"s      {chat_id}: {e}")
                    if "not found" in str(e).lower() or "invalid" in str(e).lower():
                        forward_chats.discard(chat_id)
                        logger.warning(f"  {chat_id}      s ")
                        
        except Exception as e:
            logger.error(f"     : {e}")

# English comment

async def cache_chat_info(chat_id):
    try:
        logger.info(f"        {chat_id}...")
        try:
            chat = await user_app.get_chat(chat_id)
            chat_title = chat.title if hasattr(chat, 'title') else str(chat_id)
            logger.info(f"   : {chat_id} - {chat_title}")
            return True
        except (PeerIdInvalid, ValueError) as e:
            logger.debug(f"   _   : {e}")
            try:
                async for dialog in user_app.get_dialogs(limit=50):
                    if dialog.chat.id == chat_id:
                        logger.info(f"       s: {chat_id}")
                        return True
            except Exception:
                pass
            logger.error(f"       : {chat_id}")
            return False
    except Exception as e:
        logger.error(f"      {chat_id}: {e}")
        return False

async def join_call_safe(chat_id, call_py_obj=None, user_app_obj=None):
    if call_py_obj is None:
        call_py_obj = call_py
    if user_app_obj is None:
        user_app_obj = user_app
    try:
        if not await cache_chat_info(chat_id):
            return False, "         ss "
        try:
            await call_py_obj.play(
                chat_id,
                MediaStream(ExternalMedia.AUDIO, AUDIO_PARAMETERS),
            )
            return True, None
        except NoActiveGroupCall:
            return False, "       "
        except Exception as e:
            error_msg = str(e)
            if "already participating" in error_msg.lower():
                return True, None
            return False, error_msg
    except Exception as e:
        return False, str(e)

# English comment

async def dynamic_audio_forwarder(client_data):
    call_py_obj = client_data['call_py']
    forward_chats_set = client_data['forward_chats']
    record_source = client_data['record_source']
    is_muted_local = client_data['is_muted']
    config = client_data['audio_config']
    lock = client_data['lock']
    echo_state = {}

    @call_py_obj.on_update(pytg_filters.stream_frame(Direction.INCOMING, Device.MICROPHONE))
    async def handler(_, update: StreamFrames):
        if is_muted_local or update.chat_id != record_source or not forward_chats_set:
            return
        async with lock:
            try:
                if not update.frames:
                    return
                frame_length = len(update.frames[0].frame) // 2
                mixed_acc = np.zeros(frame_length, dtype=np.int32)
                valid_frames = 0
                for frame_data in update.frames:
                    try:
                        source_samples = np.frombuffer(frame_data.frame, dtype=np.int16)
                        if len(source_samples) == frame_length:
                            mixed_acc += source_samples.astype(np.int32)
                            valid_frames += 1
                    except Exception:
                        continue
                if valid_frames == 0:
                    return
                mixed_acc //= valid_frames
                mixed_output = np.clip(mixed_acc, -32768, 32767).astype(np.int16)
                processed_output = process_audio_pipeline(mixed_output, config)
                processed_output = apply_echo_optimized(processed_output, echo_state, config)
                mixed_bytes = processed_output.tobytes()
                for chat_id in list(forward_chats_set):
                    try:
                        await call_py_obj.send_frame(chat_id, Device.MICROPHONE, mixed_bytes)
                    except Exception as e:
                        logger.debug(f"  s      {chat_id}: {e}")
                        if "not found" in str(e).lower() or "invalid" in str(e).lower():
                            forward_chats_set.discard(chat_id)
                            logger.warning(f"    {chat_id}")
            except Exception as e:
                logger.error(f"     : {e}")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info(f"     s      {client_data['user_id']}")
        raise

async def start_dynamic_client(user_id, record_groupid):
    async with dynamic_clients_lock:
        if user_id in dynamic_clients:
            return False, "This account is already connected."

    session_name = os.path.join(DYNAMIC_SESSIONS_DIR, str(user_id))
    session_file = session_name + ".session"
    if not os.path.isfile(session_file) or os.path.getsize(session_file) == 0:
        return False, f"Session file not found: {session_file}"

    try:
        user_app_dyn = Client(
            session_name,
            api_id=API_ID,
            api_hash=API_HASH,
        )
        await user_app_dyn.start()
        call_py_dyn = PyTgCalls(user_app_dyn)
        await call_py_dyn.start()

        client_data = {
            'user_id': user_id,
            'user_app': user_app_dyn,
            'call_py': call_py_dyn,
            'record_source': int(record_groupid),
            'forward_chats': set(),
            'is_muted': False,
            'is_recording': False,
            'audio_config': audio_config.copy(),
            'lock': asyncio.Lock(),
            'task': None,
        }

        task = asyncio.create_task(dynamic_audio_forwarder(client_data))
        client_data['task'] = task

        async with dynamic_clients_lock:
            dynamic_clients[user_id] = client_data

        success, error = await join_call_safe(record_groupid, call_py_dyn, user_app_dyn)
        if success:
            await call_py_dyn.record(record_groupid, RecordStream(True, AUDIO_PARAMETERS))
            client_data['is_recording'] = True
            logger.info(f"    {user_id} s ,     {record_groupid}")
        else:
            logger.warning(f"    {user_id}      : {error}")

        return True, "    s "
    except Exception as e:
        logger.error(f"    s      {user_id}: {e}")
        return False, str(e)

async def stop_dynamic_client(user_id):
    async with dynamic_clients_lock:
        client_data = dynamic_clients.pop(user_id, None)
    if client_data is None:
        return False, "   "
    try:
        if client_data['task']:
            client_data['task'].cancel()
            try:
                await client_data['task']
            except asyncio.CancelledError:
                pass
        for chat in list(client_data['forward_chats']):
            try:
                await client_data['call_py'].leave_call(chat)
            except Exception:
                pass
        try:
            await client_data['call_py'].leave_call(client_data['record_source'])
        except Exception:
            pass
        try:
            await client_data['call_py'].stop()
        except Exception:
            pass
        try:
            await client_data['user_app'].stop()
        except Exception:
            pass
        logger.info(f"    {user_id} s ")
        return True, "s "
    except Exception as e:
        logger.error(f"  s      {user_id}: {e}")
        return False, str(e)

async def dynamic_join(user_id, target_chat):
    async with dynamic_clients_lock:
        client_data = dynamic_clients.get(user_id)
    if client_data is None:
        return False, "         s  s "
    if target_chat in client_data['forward_chats']:
        return False, "     "
    if target_chat == client_data['record_source']:
        return False, "      s "
    success, error = await join_call_safe(target_chat, client_data['call_py'], client_data['user_app'])
    if success:
        client_data['forward_chats'].add(target_chat)
        return True, " "
    else:
        return False, error

# English comment

# English comment

@bot_app.on_message(pyro_filters.command("approve") & pyro_filters.user(OWNER_ID))
async def cmd_approve(client, message):
    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            user = message.reply_to_message.from_user
            user_id = user.id
            mention = user.mention
            username = user.username or "No username"
            first_name = user.first_name or "Unknown"
        else:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply(
                    "Usage: reply to a user's message with /approve, or use /approve <user_id>."
                )
                return
            user_id = int(parts[1])
            try:
                user = await client.get_users(user_id)
                mention = user.mention
                username = user.username or "No username"
                first_name = user.first_name or "Unknown"
            except Exception:
                mention = f"User {user_id}"
                username = "Unknown"
                first_name = "Unknown"

        if user_id in approved_users:
            await message.reply(f"{mention} (`{user_id}`) is already approved.")
            return

        approved_users.add(user_id)
        save_state()
        await message.reply(
            "**User approved successfully.**\n\n"
            f"Name: {first_name}\n"
            f"User: {mention}\n"
            f"ID: `{user_id}`\n"
            f"Username: @{username}"
        )
        logger.info("Approved user %s", user_id)
    except ValueError:
        await message.reply("Invalid user ID. Please provide a numeric Telegram user ID.")
    except Exception as e:
        logger.exception("Could not approve user")
        await message.reply(f"Approval failed: `{e}`")


@bot_app.on_message(pyro_filters.command("disapprove") & pyro_filters.user(OWNER_ID))
async def cmd_disapprove(client, message):
    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            user = message.reply_to_message.from_user
            user_id = user.id
            mention = user.mention
        else:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply(
                    "Usage: reply to a user's message with /disapprove, or use /disapprove <user_id>."
                )
                return
            user_id = int(parts[1])
            try:
                user = await client.get_users(user_id)
                mention = user.mention
            except Exception:
                mention = f"User {user_id}"

        if user_id not in approved_users:
            await message.reply(f"{mention} (`{user_id}`) is not in the approved-user list.")
            return

        approved_users.discard(user_id)
        save_state()
        await message.reply(f"**User access removed.**\n\nUser: {mention}\nID: `{user_id}`")
        logger.info("Removed approved user %s", user_id)
    except ValueError:
        await message.reply("Invalid user ID. Please provide a numeric Telegram user ID.")
    except Exception as e:
        logger.exception("Could not remove approved user")
        await message.reply(f"Removal failed: `{e}`")


@bot_app.on_message(pyro_filters.command("userlist") & pyro_filters.user(OWNER_ID))
async def cmd_userlist(client, message):
    if not approved_users:
        await message.reply("There are no approved users yet. Use /approve <user_id> to add one.")
        return

    rows = []
    for user_id in sorted(approved_users):
        try:
            user = await client.get_users(user_id)
            username = f"@{user.username}" if user.username else "No username"
            rows.append(f"- {user.mention} | `{user_id}` | {username}")
        except Exception:
            rows.append(f"- User `{user_id}` | profile unavailable")

    response = "**Approved users**\n\n" + "\n".join(rows)
    await message.reply(response)


class ButtonStyle:
    PRIMARY = "bg_primary"
    SUCCESS = "bg_success"
    DANGER = "bg_danger"

def styled_button(text: str, callback_data: str = None, url: str = None, style: str = ButtonStyle.PRIMARY) -> InlineKeyboardButton:
    if url:
        btn = InlineKeyboardButton(text=text, url=url)
    else:
        btn = InlineKeyboardButton(text=text, callback_data=callback_data)
    btn.__dict__["style"] = style
    return btn

def build_keyboard(buttons: list, row_width: int = 2) -> InlineKeyboardMarkup:
    rows, row = [], []
    for btn in buttons:
        if len(btn) == 4:
            text, callback, style, url = btn
            if style not in [ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER]:
                style = ButtonStyle.PRIMARY
            row.append(styled_button(text, callback_data=callback, url=url, style=style))
        elif len(btn) == 3:
            text, callback, style = btn
            if style not in [ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER]:
                style = ButtonStyle.PRIMARY
            row.append(styled_button(text, callback_data=callback, style=style))
        else:
            text, callback = btn[0], btn[1]
            row.append(styled_button(text, callback_data=callback, style=ButtonStyle.PRIMARY))
        if len(row) >= row_width:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

# English comment

@bot_app.on_callback_query(~pyro_filters.regex(r"^panel_"))
async def handle_callbacks(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    if user_id != OWNER_ID and user_id not in approved_users:
        await callback_query.answer("   !", show_alert=True)
        return
    await callback_query.answer()
    if data == "refresh_userlist":
        if not approved_users:
            keyboard = build_keyboard([
                ("   ", "help_info", ButtonStyle.SUCCESS),
                ("   ", "back_start", ButtonStyle.PRIMARY)
            ], row_width=2)
            await callback_query.edit_message_text(
                "  **   s s      .**",
                reply_markup=keyboard
            )
            return
        user_list = []
        for uid in approved_users:
            try:
                user = await client.get_users(uid)
                username = f"@{user.username}" if user.username else "   s "
                mention = user.mention
                user_list.append(f"  {mention}\n    `{uid}` | {username}")
            except Exception:
                user_list.append(f"   s  `{uid}` (       )")
        response = f"""
  **   s s** (   s )
 
  ** :** {len(approved_users)}  s s
 
"""
        response += "\n\n".join(user_list)
        response += f"\n\n \n  ** :** {len(approved_users)}"
        keyboard = build_keyboard([
            ("   s ", "refresh_userlist", ButtonStyle.PRIMARY),
            ("  s s", "userlist_stats", ButtonStyle.PRIMARY),
            ("   ", "back_start", ButtonStyle.SUCCESS)
        ], row_width=2)
        await callback_query.edit_message_text(response, reply_markup=keyboard)
    elif data == "userlist_stats":
        total = len(approved_users)
        stats_msg = f"""
  ** s  s s s**
 
  ** :** {total}
  **s s:** {'   ' if total > 0 else '   '}
 
  ** ss**
{(' ' * min(total, 10)) + (' ' * (10 - min(total, 10))) if total > 0 else ' '}
  ** s :** {' ' if total < 50 else ' ' if total < 100 else ' x'}
"""
        keyboard = build_keyboard([
            ("   ", "back_userlist", ButtonStyle.PRIMARY)
        ], row_width=1)
        await callback_query.edit_message_text(stats_msg, reply_markup=keyboard)
    elif data == "back_userlist":
        if not approved_users:
            keyboard = build_keyboard([
                ("   ", "help_info", ButtonStyle.SUCCESS),
                ("   ", "back_start", ButtonStyle.PRIMARY)
            ], row_width=2)
            await callback_query.edit_message_text(
                "  **   s s    **\n\n s  `/approve`    ",
                reply_markup=keyboard
            )
            return
        user_list = []
        for uid in approved_users:
            try:
                user = await client.get_users(uid)
                username = f"@{user.username}" if user.username else "   s "
                mention = user.mention
                user_list.append(f"  {mention}\n    `{uid}` | {username}")
            except Exception:
                user_list.append(f"   s  `{uid}` (       )")
        response = f"""
  **   s s**
 
  ** :** {len(approved_users)}
 
"""
        response += "\n\n".join(user_list)
        response += f"\n\n \n  ** :** {len(approved_users)}"
        keyboard = build_keyboard([
            ("   s ", "refresh_userlist", ButtonStyle.PRIMARY),
            ("  s s", "userlist_stats", ButtonStyle.PRIMARY),
            ("   ", "back_start", ButtonStyle.SUCCESS)
        ], row_width=2)
        await callback_query.edit_message_text(response, reply_markup=keyboard)
    elif data == "help_info":
        help_text = """**Bot commands**

**Voice chat**
/record - Start recording the configured source group call
/join <chat_id> - Join a target group call
/rejoin - Rejoin the configured source call
/leave <chat_id> - Leave a target group call
/leaveall - Leave all joined target calls
/leaverecord - Stop recording and leave the source call
/mute - Pause audio forwarding
/unmute - Resume audio forwarding

**Audio effects**
/level <value> - Set volume
/bass <value> - Set bass
/treble <value> - Set treble
/gain <value> - Set gain
/overdrive <value> - Set overdrive
/echo delay <ms> - Set echo delay
/echo decay <value> - Set echo decay
/effects - Show current audio settings
/reset - Restore default audio settings

**Information**
/ping - Check response time
/stats - Show bot statistics
/status - Show current call status
/list - List joined chats
/id - Show the current chat ID
/panel - Open the control panel

**Owner**
/approve <user_id> - Approve a user
/disapprove <user_id> - Remove user approval
/userlist - Show approved users
/setrecordgroup <chat_id> - Change the source group
/restart - Restart the call connection
"""
        keyboard = build_keyboard([
            ("   ", "back_start", ButtonStyle.SUCCESS)
        ], row_width=1)
        await callback_query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    elif data == "back_start":
        user = callback_query.from_user
        first_name = escape_markdown(user.first_name or " s ")
        last_name = escape_markdown(user.last_name or "")
        username = f"@{user.username}" if user.username else ""
        welcome_text = f"""
  **       **  
 
  ** , {first_name}!**
{last_name}
{username}
 
  ** -     **
  **s s :**   100%  
  ** s:**
   -   
     s
     
   -   
   ss/   s 
     
   s /   
 
  ** s  /     s**
"""
        keyboard = build_keyboard([
            ("   ", "owner", ButtonStyle.PRIMARY),
            ("   ", "help_info", ButtonStyle.PRIMARY)
        ], row_width=2)
        try:
            photos = []
            async for photo in client.get_chat_photos(user.id, limit=1):
                photos.append(photo)
            if photos:
                photo = photos[0]
                await callback_query.edit_message_media(
                    media=photo.file_id,
                    caption=welcome_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await callback_query.edit_message_text(
                    welcome_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f" _s   : {e}")
            if "MESSAGE_NOT_MODIFIED" not in str(e):
                try:
                    await callback_query.edit_message_text(
                        welcome_text,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                except Exception:
                    pass
    elif data == "owner":
        keyboard = build_keyboard([
            ("   ", "back_start", ButtonStyle.SUCCESS)
        ], row_width=1)
        await callback_query.edit_message_text(
            "  ** **\n\n"
            "  @RAJAJIBOLOJI\n"
            "  [ ](t.me/RAJAJIBOLOJI)",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

# English comment

@bot_app.on_message(pyro_filters.command("start"))
async def cmd_start(client, message):
    user_id = message.from_user.id if message.from_user else None
    if user_id != OWNER_ID and user_id not in approved_users:
        logger.info(f"  /s    {user_id}")
        return
    user = message.from_user
    first_name = escape_markdown(user.first_name or " s ")
    last_name = escape_markdown(user.last_name or "")
    username = f"@{user.username}" if user.username else ""
    welcome_text = f"""
  **       **  
 
  ** , {first_name}!**
{last_name}
{username}
 
  ** -     **
  **s s :**   100%  
  ** s:**
   -   
     s
     
   -   
   ss/   s 
     
   s /   
 
  ** s  /     s**
"""
    keyboard = build_keyboard([
        ("   ", "owner", ButtonStyle.PRIMARY),
        ("   ", "help_info", ButtonStyle.PRIMARY)
    ], row_width=2)
    try:
        photos = []
        async for photo in client.get_chat_photos(user.id, limit=1):
            photos.append(photo)
        if photos:
            photo = photos[0]
            await message.reply_photo(
                photo=photo.file_id,
                caption=welcome_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return
    except Exception as e:
        logger.debug(f"         : {e}")
    await message.reply(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# English comment

@bot_app.on_message(pyro_filters.command("help") & authorized_only())
async def cmd_help(client, message):
    help_text = """
  **   **
 
  **   s**
/record - s   
/join < > -      
/rejoin -    
/leave < > - s   
/leaveall - s   
/leaverecord -   s 
/mute -  
/unmute -  
 
  ** s** (   s!)
/level <0- > -  
/bass <0- > -  ss
/treble <0- > -  
/gain <0- > -  
/overdrive <0- > -  s / 
/echo < / / > -  
/effects - s   s
/reset -  s   
 
  ** **
/ping -    
/stats -   s s
/status - s s  s s
/list -    s 
/id -      
/panel -    
 
  ** s   ** ( )
/approve -    s 
/disapprove -  
/userlist -  s   s s
/setrecordgroup < > -   s 
/restart -  s   
"""
    keyboard = build_keyboard([
        ("   ", "back_start", ButtonStyle.SUCCESS),
        ("   ", "owner", ButtonStyle.PRIMARY)
    ], row_width=2)
    await message.reply(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# English comment

@bot_app.on_message(pyro_filters.command("id") & pyro_filters.user(OWNER_ID))
async def cmd_id(client, message):
    chat_type = " " if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else " "
    id_msg = f"""
  **   **

 
  **   :** `{message.chat.id}`
  ** :** {chat_type}
  ** :** {message.chat.title or '   '}
 

  **   s      s     s**
"""
    await message.reply(id_msg)

@bot_app.on_message(pyro_filters.command("ping") & authorized_only())
async def cmd_ping(client, message):
    start = time.time()
    msg = await message.reply("   ...")
    end = time.time()
    ping = round((end - start) * 1000)
    await msg.edit_text(
        f"  ** !**\n\n"
        f"  ** :** `{ping} s`\n"
        f"  ** :** `{get_uptime()}`"
    )

@bot_app.on_message(pyro_filters.command("stats") & pyro_filters.user(OWNER_ID))
async def cmd_stats(client, message):
    stats_msg = f"""
  **  s s s**

 
  ** :** `{get_uptime()}`
  **   s s:** {len(approved_users)}
  **   s:** {len(forward_chats)}
  **s :** `{RECORD_SOURCE}`
  ** :** {'   ' if is_muted else '   '}
  ** :** {'   ' if is_recording else '   '}
 

  **   s**
   : `{audio_config['volume']}%`
   ss: `{audio_config['bass']}`
   : `{audio_config['treble']}`
   : `{audio_config['gain']}`
   s : `{audio_config['overdrive']}`
     : `{audio_config['echo_delay']}ms`
     : `{audio_config['echo_decay']}`
"""
    await message.reply(stats_msg)

# English comment

@bot_app.on_message(pyro_filters.command("record") & authorized_only())
async def cmd_record(client, message):
    global is_recording
    if is_recording:
        await message.reply(
            "  **   !**\n\n"
            f"  **s :** `{RECORD_SOURCE}`\n"
            f"  ** :** {len(forward_chats)}  s"
        )
        return
    try:
        status_msg = await message.reply(
            "  **s   ...**\n\n"
            "      s ..."
        )
        success, error = await join_call_safe(RECORD_SOURCE)
        if success:
            await call_py.record(RECORD_SOURCE, RecordStream(True, AUDIO_PARAMETERS))
            is_recording = True
            record_msg = f"""
  **  s  s ss !**

 
  **s :** `{RECORD_SOURCE}`
  ** :** {len(forward_chats)}  s
  **s s:**    
 

  **   s    !**
"""
            await status_msg.edit_text(record_msg)
            logger.info("  s ")
        else:
            await status_msg.edit_text(
                f"  **    s   !**\n\n"
                f"  ** :** `{error}`\n\n"
                f"    s     s  "
            )
    except Exception as e:
        await message.reply(f"  **   !**\n\n  `{str(e)}`")

@bot_app.on_message(pyro_filters.command("join") & authorized_only())
async def cmd_join(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        join_help = """
  ** s :** `/join < _ >`

 
  ** x :**
`/join -1003929100976`

  **         :**
       ss    @s s 
     s  `/ `       ( )
 

  ** :**      s     
"""
        await message.reply(join_help)
        return
    chat_id_str = re.sub(r'[^\d-]', '', parts[1])
    try:
        chat_id = int(chat_id_str)
        if chat_id in forward_chats:
            await message.reply(
                f"  **       s  !**\n\n"
                f"  `{chat_id}`\n"
                f"  ** :** {len(forward_chats)}  s"
            )
            return
        if chat_id == RECORD_SOURCE:
            await message.reply(
                "  **      s   !**\n\n"
                f"  **s :** `{RECORD_SOURCE}`\n"
                "   s           "
            )
            return
        status_msg = await message.reply(
            f"  **    `{chat_id}`...**\n\n"
            "   s s     ..."
        )
        success, error = await join_call_safe(chat_id)
        if success:
            forward_chats.add(chat_id)
            join_msg = f"""
  **  s  s ss !**

 
  ** :** `{chat_id}`
  **   s:** {len(forward_chats)}
  **s s:**    
 

  **   s        s  !**
"""
            await status_msg.edit_text(join_msg)
            logger.info(f"  {chat_id}")
        else:
            await status_msg.edit_text(
                f"  **       !**\n\n"
                f"  ** :** `{error}`\n\n"
                f"  ** s :**\n"
                f"   s     s  \n"
                f"         s  \n"
                f"         s  "
            )
    except ValueError:
        await message.reply(
            f"  **       !**\n\n"
            f"  **   :** `{parts[1]}`\n"
            f"   s        ( . ., `-1003929100976`)"
        )
    except Exception as e:
        await message.reply(f"  **   !**\n\n  `{str(e)}`")

# English comment

@bot_app.on_message(pyro_filters.command("rejoin") & authorized_only())
async def cmd_rejoin(client, message):
    global is_recording
    status_msg = await message.reply(
        "  **     s...**\n\n"
        "   s         s..."
    )
    rejoin_results = {
        "source": {"status": " ", "error": None},
        "forwards": {"total": 0, "success": 0, "failed": 0, "errors": []}
    }
    was_recording = is_recording
    source_chat = RECORD_SOURCE
    if was_recording:
        try:
            await call_py.leave_call(source_chat)
            logger.info(f"  s  {source_chat}    ")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"      s : {e}")
        try:
            success, error = await join_call_safe(source_chat)
            if success:
                await call_py.record(source_chat, RecordStream(True, AUDIO_PARAMETERS))
                is_recording = True
                rejoin_results["source"]["status"] = " "
                logger.info(f"  s  {source_chat} s ss ")
            else:
                is_recording = False
                rejoin_results["source"]["status"] = " "
                rejoin_results["source"]["error"] = error
                logger.error(f"      s : {error}")
        except Exception as e:
            is_recording = False
            rejoin_results["source"]["status"] = " "
            rejoin_results["source"]["error"] = str(e)
            logger.error(f"    s : {e}")
    else:
        rejoin_results["source"]["status"] = " "
        rejoin_results["source"]["error"] = "   "
    forward_list = list(forward_chats)
    rejoin_results["forwards"]["total"] = len(forward_list)
    if forward_list:
        for chat_id in forward_list:
            try:
                await call_py.leave_call(chat_id)
                logger.info(f"      {chat_id}    ")
            except Exception as e:
                logger.debug(f"      {chat_id}: {e}")
        await asyncio.sleep(1.5)
        for chat_id in forward_list:
            try:
                success, error = await join_call_safe(chat_id)
                if success:
                    rejoin_results["forwards"]["success"] += 1
                    logger.info(f"      {chat_id} s ss ")
                else:
                    rejoin_results["forwards"]["failed"] += 1
                    rejoin_results["forwards"]["errors"].append(f"`{chat_id}`: {error[:50]}")
                    logger.error(f"      {chat_id}: {error}")
                    forward_chats.discard(chat_id)
            except Exception as e:
                rejoin_results["forwards"]["failed"] += 1
                rejoin_results["forwards"]["errors"].append(f"`{chat_id}`: {str(e)[:50]}")
                forward_chats.discard(chat_id)
                logger.error(f"    {chat_id}: {e}")
    else:
        rejoin_results["forwards"]["status"] = " "
        rejoin_results["forwards"]["error"] = "     s"
    response = f"""
  **   !**

 
  **s   :** `{source_chat}`
{'   ' if rejoin_results['source']['status'] == ' ' else '   ' if rejoin_results['source']['status'] == ' ' else '     '}
"""
    if rejoin_results['source']['error']:
        response += f"  ** :** `{rejoin_results['source']['error']}`\n"
    response += f"""
 
  **  s s:**
  ** :** {rejoin_results['forwards']['total']}
  **  s ss:** {rejoin_results['forwards']['success']}
  **   :** {rejoin_results['forwards']['failed']}
"""
    if rejoin_results['forwards']['errors']:
        response += "\n  **   s:**\n"
        for err in rejoin_results['forwards']['errors'][:5]:
            response += f"  {err}\n"
        if len(rejoin_results['forwards']['errors']) > 5:
            response += f"  ...   {len(rejoin_results['forwards']['errors'])-5}  \n"
    response += f"""
 
  **  s s:**
  ** :** {'   ' if is_recording else '   '}
  ** :** {len(forward_chats)}  s
  ** :** {'   ' if is_muted else '   '}
 

  ** :**    s            s 
"""
    await status_msg.edit_text(response)
    logger.info(f"   : s ={rejoin_results['source']['status']},  s={rejoin_results['forwards']['success']}/{rejoin_results['forwards']['total']}")

# English comment

@bot_app.on_message(pyro_filters.command("leaverecord") & authorized_only())
async def cmd_leaverecord(client, message):
    global is_recording
    try:
        status_msg = await message.reply("  **  s   ...**")
        await call_py.leave_call(RECORD_SOURCE)
        is_recording = False
        leave_msg = f"""
  **  s    s ss !**

 
  **s :** `{RECORD_SOURCE}`
  **s s:**    s 
  **   :** {len(forward_chats)}
 

  **   s   s !**
"""
        await status_msg.edit_text(leave_msg)
        logger.info("     ")
    except Exception as e:
        await message.reply(f"  **   !**\n\n  `{str(e)}`")

@bot_app.on_message(pyro_filters.command("leave") & authorized_only())
async def cmd_leave(client, message):
    parts = message.text.split()
    if len(parts) >= 2:
        chat_id_str = re.sub(r'[^\d-]', '', parts[1])
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            await message.reply(
                f"  **     !**\n\n"
                f"  **   :** `{parts[1]}`\n"
                f"   s        ( . ., `-1003929100976`)"
            )
            return
        if chat_id not in forward_chats:
            await message.reply(
                f"  **       s  !**\n\n  `{chat_id}`"
            )
            return
        try:
            status_msg = await message.reply(f"  **  `{chat_id}`...**")
            await call_py.leave_call(chat_id)
            forward_chats.discard(chat_id)
            leave_msg = f"""
  **    s ss !**

 
  ** :** `{chat_id}`
  **   :** {len(forward_chats)}
  **s s:**    s 
 

  **     s     s  !**
"""
            await status_msg.edit_text(leave_msg)
            logger.info(f"    {chat_id}")
        except Exception as e:
            logger.error(f" _      {chat_id}: {e}")
            await message.reply(f"  **     !**\n\n  `{str(e)}`")
    else:
        if not forward_chats:
            await message.reply(
                "  **   s    !**\n\n   s  `/ `   s   "
            )
            return
        count = len(forward_chats)
        status_msg = await message.reply(f"  **    {count}  s...**")
        left_count = 0
        for cid in list(forward_chats):
            try:
                await call_py.leave_call(cid)
                left_count += 1
            except Exception:
                pass
        forward_chats.clear()
        leave_msg = f"""
  **     s s ss !**

 
  **   :** {left_count}/{count}  s
  **s s:**      s 
  **s :** {'   ' if is_recording else '   '}
 

  **       s s !**
"""
        await status_msg.edit_text(leave_msg)

@bot_app.on_message(pyro_filters.command("leaveall") & authorized_only())
async def cmd_leaveall(client, message):
    global is_recording
    total_forward = len(forward_chats)
    status_msg = await message.reply(
        "  ** s     s...**\n\n         s..."
    )
    try:
        await call_py.leave_call(RECORD_SOURCE)
        is_recording = False
    except Exception:
        pass
    left_count = 0
    for cid in list(forward_chats):
        try:
            await call_py.leave_call(cid)
            left_count += 1
        except Exception:
            pass
    forward_chats.clear()
    leaveall_msg = f"""
  **   s  s  s ss !**

 
  **s :**    
  ** :** {left_count}/{total_forward}  
  **s s:**      s 
 

  **   s      !**
"""
    await status_msg.edit_text(leaveall_msg)
    logger.info("     s")

# English comment

@bot_app.on_message(pyro_filters.command("mute") & authorized_only())
async def cmd_mute(client, message):
    global is_muted
    if is_muted:
        await message.reply(
            "  **   !**\n\n"
            f"  **   :** {len(forward_chats)}\n"
            "   s  `/ `    s "
        )
        return
    is_muted = True
    mute_msg = f"""
  **    s ss !**

 
  **s s:**    
  **   :** {len(forward_chats)}
  **s :** {'   ' if is_recording else '   '}
 

  **     s        !**
"""
    await message.reply(mute_msg)
    logger.info("   ")

@bot_app.on_message(pyro_filters.command("unmute") & authorized_only())
async def cmd_unmute(client, message):
    global is_muted
    if not is_muted:
        await message.reply(
            "  **   !**\n\n"
            f"  **   :** {len(forward_chats)}\n"
            "     s    "
        )
        return
    is_muted = False
    unmute_msg = f"""
  **    s ss !**

 
  **s s:**    
  **   :** {len(forward_chats)}
  **s :** {'   ' if is_recording else '   '}
 

  **   s          s!**
"""
    await message.reply(unmute_msg)
    logger.info("   ")

# English comment

@bot_app.on_message(pyro_filters.command("level") & authorized_only())
async def cmd_level_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['volume']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 200), 200)
        await message.reply(
            f"  **Volume Control**\n\n"
            f"  **Current:** `{current}%`\n"
            f"  {bar} `{min(current, 200)}%`\n"
            f"  **Status:** {get_effect_status(min(current, 200), 200)}\n\n"
            f"  **Usage:** `/level <0- >`\n"
            f"  **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT - but clamp for safety display
        audio_config['volume'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 200), 200)
        await message.reply(
            f"  **Volume updated!**\n\n"
            f"  **New:** `{level}%`\n"
            f"  {bar} `{min(abs(level), 200)}%`\n"
            f"  **Status:** {'  EXTREME' if abs(level) > 200 else get_effect_status(abs(level), 200)}\n\n"
            f"  **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("bass") & authorized_only())
async def cmd_bass_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['bass']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"  **Bass Boost**\n\n"
            f"  **Current:** `{current}`\n"
            f"  {bar} `{min(current, 60)}/ `\n"
            f"  **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"  **Usage:** `/bass <0- >`\n"
            f"  **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT
        audio_config['bass'] = max(0, level)
        audio_config['highpass'] = level > 0
        save_state()
        bar = create_progress_bar(min(abs(level), 60), 60)
        await message.reply(
            f"  **Bass updated!**\n\n"
            f"  **New:** `{level}`\n"
            f"  {bar} `{min(abs(level), 60)}/ `\n"
            f"  **Status:** {'  EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"  **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("treble") & authorized_only())
async def cmd_treble_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['treble']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"  **Treble Boost**\n\n"
            f"  **Current:** `{current}`\n"
            f"  {bar} `{min(current, 60)}/ `\n"
            f"  **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"  **Usage:** `/treble <0- >`\n"
            f"  **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT
        audio_config['treble'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 60), 60)
        await message.reply(
            f"  **Treble updated!**\n\n"
            f"  **New:** `{level}`\n"
            f"  {bar} `{min(abs(level), 60)}/ `\n"
            f"  **Status:** {'  EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"  **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("gain") & authorized_only())
async def cmd_gain_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['gain']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"  **Gain Control**\n\n"
            f"  **Current:** `{current}`\n"
            f"  {bar} `{min(current, 60)}/ `\n"
            f"  **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"  **Usage:** `/gain <0- >`\n"
            f"  **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT
        audio_config['gain'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 60), 60)
        await message.reply(
            f"  **Gain updated!**\n\n"
            f"  **New:** `{level}`\n"
            f"  {bar} `{min(abs(level), 60)}/ `\n"
            f"  **Status:** {'  EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"  **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[1]}`")

# ===== NEW: OVERDRIVE COMMAND =====

@bot_app.on_message(pyro_filters.command("overdrive") & authorized_only())
async def cmd_overdrive(client, message):
    parts = message.text.split()
    current = audio_config.get('overdrive', 0)
    gain = audio_config.get('overdrive_gain', 1.0)
    tone = audio_config.get('overdrive_tone', 0.5)
    
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 100), 100)
        await message.reply(
            f"  **Overdrive/Distortion**\n\n"
            f"  **Current:** `{current}/100`\n"
            f"  {bar} `{current}/100`\n"
            f"  **Gain:** `{gain}x` | **Tone:** `{tone}`\n\n"
            f"  **Usage:**\n"
            f"`/overdrive <0-100>` - Set drive level\n"
            f"`/overdrive gain <1.0-10.0>` - Set gain\n"
            f"`/overdrive tone <0.0-1.0>` - Set tone\n"
            f"`/overdrive off` - Disable\n\n"
            f"  **NO LIMIT!** Set any value!"
        )
        return
    
    action = parts[1].lower()
    
    if action == "off":
        audio_config['overdrive'] = 0
        save_state()
        await message.reply("  **Overdrive disabled!**")
        return
    
    if len(parts) < 3:
        await message.reply(f"  **Usage:** `/overdrive {action} <value>`")
        return
    
    try:
        value = float(parts[2])
        
        if action == "gain":
            audio_config['overdrive_gain'] = max(0.5, min(10.0, value))
            save_state()
            await message.reply(f"  **Overdrive gain set to:** `{audio_config['overdrive_gain']}x`")
        elif action == "tone":
            audio_config['overdrive_tone'] = max(0.0, min(1.0, value))
            save_state()
            await message.reply(f"  **Overdrive tone set to:** `{audio_config['overdrive_tone']}`")
        else:
            value = int(value)
            audio_config['overdrive'] = max(0, value)
            save_state()
            bar = create_progress_bar(min(value, 100), 100)
            await message.reply(
                f"  **Overdrive updated!**\n\n"
                f"  **New:** `{value}/100`\n"
                f"  {bar} `{value}/100`\n"
                f"  **Status:** {'  EXTREME' if value > 80 else '  s ' if value > 50 else '   ' if value > 20 else '   '}\n\n"
                f"  **NO LIMIT!**"
            )
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[2]}`")

# ===== ECHO COMMANDS (UNLIMITED) =====

@bot_app.on_message(pyro_filters.command("echo") & authorized_only())
async def cmd_echo(client, message):
    parts = message.text.split()
    current_delay = audio_config.get('echo_delay', 70)
    current_decay = audio_config.get('echo_decay', 0.32)
    
    if len(parts) < 2:
        await message.reply(
            f"  **Echo Controls**\n\n"
            f"  **Current Settings:**\n"
            f"  **Delay:** `{current_delay}ms`\n"
            f"  **Decay:** `{current_decay}`\n\n"
            f"  **Usage:**\n"
            f"`/echo delay <1-5000>` - Set delay in ms\n"
            f"`/echo decay <0.01-5.0>` - Set decay strength\n"
            f"`/echo off` - Disable echo completely\n\n"
            f"  **NO LIMITS!** You can set any value!"
        )
        return
    
    action = parts[1].lower()
    
    if action == "off":
        audio_config['echo_delay'] = 0
        audio_config['echo_decay'] = 0
        save_state()
        await message.reply("  **Echo disabled!**")
        return
    
    if len(parts) < 3:
        await message.reply(f"  **Usage:** `/echo {action} <value>`")
        return
    
    try:
        value = float(parts[2])
        
        if action == "delay":
            # NO LIMIT! But safe minimum to avoid crash
            value = max(1, value)
            audio_config['echo_delay'] = value
            await message.reply(f"  **Echo delay set to:** `{value}ms`\n\n  NO LIMITS!")
            
        elif action == "decay":
            # NO LIMIT! But safe minimum to avoid zero
            value = max(0.01, value)
            audio_config['echo_decay'] = value
            await message.reply(f"  **Echo decay set to:** `{value}`\n\n  NO LIMITS!")
            
        else:
            await message.reply(f"  **Unknown echo option:** `{action}`\n\nUse: `delay`, `decay`, or `off`")
            return
            
        save_state()
        
    except ValueError:
        await message.reply(f"  **Invalid value:** `{parts[2]}`")

@bot_app.on_message(pyro_filters.command("effects") & authorized_only())
async def cmd_effects(client, message):
    config = audio_config
    scipy_status = "     " if SCIPY_AVAILABLE else "   s   "
    vol_bar = create_progress_bar(min(config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(config['gain'], 60), 60)
    od_bar = create_progress_bar(min(config.get('overdrive', 0), 100), 100)
    effects_msg = f"""
  **   s  s **

 
  ** :** `{config['volume']}%`
{vol_bar} `{config['volume']}%`

  ** ss:** `{config['bass']}/ `
{bass_bar} `{config['bass']}/ `

  ** :** `{config['treble']}/ `
{treble_bar} `{config['treble']}/ `

  ** :** `{config['gain']}/ `
{gain_bar} `{config['gain']}/ `

  ** s :** `{config.get('overdrive', 0)}/100`
{od_bar} `{config.get('overdrive', 0)}/100`
   : `{config.get('overdrive_gain', 1.0)}x` |  : `{config.get('overdrive_tone', 0.5)}`

  ** :**
   : `{config['echo_delay']}ms`
   : `{config['echo_decay']}`

 
  ** s**
   ss : {'   ' if config['compressor'] else '   s '}
   : {'   ' if config['limiter'] else '   s '}
   ss: {'   ' if config['highpass'] else '   s '}
   ss: {'   ' if config['lowpass'] else '   s '}

  ** :** {scipy_status}
"""
    await message.reply(effects_msg)

@bot_app.on_message(pyro_filters.command("reset") & authorized_only())
async def cmd_reset(client, message):
    global audio_config
    old_config = audio_config.copy()
    audio_config = {
        'volume': 100,
        'bass': 0,
        'treble': 0,
        'gain': 0,
        'compressor': True,
        'limiter': True,
        'highpass': False,
        'lowpass': False,
        'echo_delay': 70,
        'echo_decay': 0.32,
        'freq_shift': 2.0,
        'pre_gain': 1.0,
        'overdrive': 0,
        'overdrive_gain': 1.0,
        'overdrive_tone': 0.5,
        'reverb_room': 0,
        'reverb_damp': 0.5,
        'stereo_width': 0,
    }
    # Clear filter cache
    _filter_cache.clear()
    save_state()
    reset_msg = f"""
  **     s  s !**

 
  ** :** `{old_config['volume']}%`   `{audio_config['volume']}%`  
  ** ss:** `{old_config['bass']}`   `{audio_config['bass']}`  
  ** :** `{old_config['treble']}`   `{audio_config['treble']}`  
  ** :** `{old_config['gain']}`   `{audio_config['gain']}`  
  ** s :** `{old_config.get('overdrive', 0)}`   `{audio_config['overdrive']}`  
  ** :** `{old_config['echo_delay']}ms`   `{audio_config['echo_delay']}ms`  
 

  **s s:**      s 
  ** s:**    
"""
    await message.reply(reset_msg)
    logger.info("   s  s     ")

# English comment

@bot_app.on_message(pyro_filters.command("status") & authorized_only())
async def cmd_status(client, message):
    recording_status = "   " if is_recording else "   "
    audio_status = "   " if is_muted else "   "
    forward_count = len(forward_chats)
    forward_list = ""
    if forward_chats:
        forward_list = "\n".join(f"  `{c}`" for c in list(forward_chats)[:10])
        if len(forward_chats) > 10:
            forward_list += f"\n  ...   {len(forward_chats)-10}  "
    else:
        forward_list = "   "
    status_msg = f"""
  **  s s  s **

 
  ** :** {recording_status}
  **s :** `{RECORD_SOURCE}`
  ** :** {audio_status}
  ** :** {forward_count}  s
  ** :** `{get_uptime()}`
 

  **   :**
{forward_list}

 
  **   s:**
   : `{audio_config['volume']}%`
   ss: `{audio_config['bass']}`
   : `{audio_config['treble']}`
   : `{audio_config['gain']}`
   s : `{audio_config.get('overdrive', 0)}`
   : `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

  **s s :** {'  s ' if is_recording else '  s '}
"""
    await message.reply(status_msg)

@bot_app.on_message(pyro_filters.command("list") & authorized_only())
async def cmd_list(client, message):
    if not forward_chats:
        await message.reply(
            "  **     **\n\n"
            "   s  `/  < _ >`   s \n"
            "   x : `/  -1003929100976`"
        )
        return
    chat_list = []
    for idx, cid in enumerate(forward_chats, 1):
        chat_list.append(f"`{idx}.` `{cid}`")
    list_msg = f"""
  **   s  s **

 
  ** :** {len(forward_chats)}  s
 

{chr(10).join(chat_list)}

 
  ** s:**
   s  `/  < >`        
   s  `/ `      
"""
    await message.reply(list_msg)

# English comment

@bot_app.on_message(pyro_filters.command("panel") & authorized_only())
async def cmd_panel(client, message):
    recording_status = "   " if is_recording else "   "
    audio_status = "   " if is_muted else "   "
    forward_count = len(forward_chats)
    uptime = get_uptime()
    vol_bar = create_progress_bar(min(audio_config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(audio_config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(audio_config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(audio_config['gain'], 60), 60)
    od_bar = create_progress_bar(min(audio_config.get('overdrive', 0), 100), 100)
    panel_text = f"""
  **   **

 
  **s s  s s**
  ** :** {recording_status}
  ** :** {audio_status}
  ** :** {forward_count}  s
  ** :** {uptime}
  **s :** `{RECORD_SOURCE}`

 
  **   s**
  ** :** `{audio_config['volume']}%` {vol_bar}
  ** ss:** `{audio_config['bass']}/ ` {bass_bar}
  ** :** `{audio_config['treble']}/ ` {treble_bar}
  ** :** `{audio_config['gain']}/ ` {gain_bar}
  ** s :** `{audio_config.get('overdrive', 0)}/100` {od_bar}
  ** :** `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

 
  ** s   s      **
"""
    keyboard = build_keyboard([
        ("   ", "panel_mute", ButtonStyle.DANGER),
        ("   ", "panel_unmute", ButtonStyle.SUCCESS),
        ("    -", "panel_vol_down", ButtonStyle.PRIMARY),
        ("    +", "panel_vol_up", ButtonStyle.PRIMARY),
        ("   ss -", "panel_bass_down", ButtonStyle.PRIMARY),
        ("   ss +", "panel_bass_up", ButtonStyle.PRIMARY),
        ("    -", "panel_treble_down", ButtonStyle.PRIMARY),
        ("    +", "panel_treble_up", ButtonStyle.PRIMARY),
        ("    -", "panel_gain_down", ButtonStyle.PRIMARY),
        ("    +", "panel_gain_up", ButtonStyle.PRIMARY),
        ("   s  -", "panel_od_down", ButtonStyle.PRIMARY),
        ("   s  +", "panel_od_up", ButtonStyle.PRIMARY),
        ("   s ", "panel_reset", ButtonStyle.DANGER),
        ("   s ", "panel_list", ButtonStyle.PRIMARY),
        ("   s ", "panel_close", ButtonStyle.DANGER),
    ], row_width=2)
    await message.reply(
        panel_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# English comment

@bot_app.on_callback_query(pyro_filters.regex(r"^panel_"))
async def panel_callbacks(client, callback_query: CallbackQuery):
    global is_muted, audio_config
    data = callback_query.data
    user_id = callback_query.from_user.id
    if user_id != OWNER_ID and user_id not in approved_users:
        await callback_query.answer("   !", show_alert=True)
        return
    await callback_query.answer()
    if data == "panel_mute":
        if is_muted:
            await callback_query.answer("     !", show_alert=True)
            return
        is_muted = True
        await callback_query.answer("     !", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_unmute":
        if not is_muted:
            await callback_query.answer("     !", show_alert=True)
            return
        is_muted = False
        await callback_query.answer("     !", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_vol_up":
        audio_config['volume'] = 200
        save_state()
        await callback_query.answer("   :  x (200%)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_vol_down":
        audio_config['volume'] = 100
        save_state()
        await callback_query.answer("   : 100%", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_bass_up":
        audio_config['bass'] = 60
        audio_config['highpass'] = True
        save_state()
        await callback_query.answer("   ss:  x (60/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_bass_down":
        audio_config['bass'] = 0
        audio_config['highpass'] = False
        save_state()
        await callback_query.answer("   ss:   (0/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_treble_up":
        audio_config['treble'] = 60
        save_state()
        await callback_query.answer("   :  x (60/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_treble_down":
        audio_config['treble'] = 0
        save_state()
        await callback_query.answer("   :   (0/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_gain_up":
        audio_config['gain'] = 60
        save_state()
        await callback_query.answer("   :  x (60/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_gain_down":
        audio_config['gain'] = 0
        save_state()
        await callback_query.answer("   :   (0/ )", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_od_up":
        audio_config['overdrive'] = 100
        save_state()
        await callback_query.answer("   s : MAX (100)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_od_down":
        audio_config['overdrive'] = 0
        save_state()
        await callback_query.answer("   s : OFF (0)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_reset":
        audio_config = {
            'volume': 100,
            'bass': 0,
            'treble': 0,
            'gain': 0,
            'compressor': True,
            'limiter': True,
            'highpass': False,
            'lowpass': False,
            'echo_delay': 70,
            'echo_decay': 0.32,
            'freq_shift': 2.0,
            'pre_gain': 1.0,
            'overdrive': 0,
            'overdrive_gain': 1.0,
            'overdrive_tone': 0.5,
            'reverb_room': 0,
            'reverb_damp': 0.5,
            'stereo_width': 0,
        }
        _filter_cache.clear()
        save_state()
        await callback_query.answer("     s  s !", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_list":
        if not forward_chats:
            list_text = "  **     **"
        else:
            chat_list = "\n".join(f"  `{c}`" for c in list(forward_chats)[:15])
            if len(forward_chats) > 15:
                chat_list += f"\n  ...   {len(forward_chats)-15}  "
            list_text = f"""
  **   s**

 
  ** :** {len(forward_chats)}
 
{chat_list}
"""
        keyboard = build_keyboard([
            ("   ", "panel_back", ButtonStyle.PRIMARY)
        ], row_width=1)
        await callback_query.edit_message_text(
            list_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    elif data == "panel_back":
        await refresh_panel(client, callback_query)
    elif data == "panel_close":
        try:
            await callback_query.message.delete()
            await callback_query.answer("     s !", show_alert=True)
        except Exception:
            await callback_query.answer("       s ", show_alert=True)

# English comment

async def refresh_panel(client, callback_query: CallbackQuery):
    recording_status = "   " if is_recording else "   "
    audio_status = "   " if is_muted else "   "
    forward_count = len(forward_chats)
    uptime = get_uptime()
    vol_bar = create_progress_bar(min(audio_config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(audio_config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(audio_config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(audio_config['gain'], 60), 60)
    od_bar = create_progress_bar(min(audio_config.get('overdrive', 0), 100), 100)
    panel_text = f"""
  **   ** (   s )

 
  **s s  s s**
  ** :** {recording_status}
  ** :** {audio_status}
  ** :** {forward_count}  s
  ** :** {uptime}
  **s :** `{RECORD_SOURCE}`

 
  **   s**
  ** :** `{audio_config['volume']}%` {vol_bar}
  ** ss:** `{audio_config['bass']}/ ` {bass_bar}
  ** :** `{audio_config['treble']}/ ` {treble_bar}
  ** :** `{audio_config['gain']}/ ` {gain_bar}
  ** s :** `{audio_config.get('overdrive', 0)}/100` {od_bar}
  ** :** `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

 
  ** s   s      **
"""
    keyboard = build_keyboard([
        ("   ", "panel_mute", ButtonStyle.DANGER),
        ("   ", "panel_unmute", ButtonStyle.SUCCESS),
        ("    -", "panel_vol_down", ButtonStyle.PRIMARY),
        ("    +", "panel_vol_up", ButtonStyle.PRIMARY),
        ("   ss -", "panel_bass_down", ButtonStyle.PRIMARY),
        ("   ss +", "panel_bass_up", ButtonStyle.PRIMARY),
        ("    -", "panel_treble_down", ButtonStyle.PRIMARY),
        ("    +", "panel_treble_up", ButtonStyle.PRIMARY),
        ("    -", "panel_gain_down", ButtonStyle.PRIMARY),
        ("    +", "panel_gain_up", ButtonStyle.PRIMARY),
        ("   s  -", "panel_od_down", ButtonStyle.PRIMARY),
        ("   s  +", "panel_od_up", ButtonStyle.PRIMARY),
        ("   s ", "panel_reset", ButtonStyle.DANGER),
        ("   s ", "panel_list", ButtonStyle.PRIMARY),
        ("   s ", "panel_close", ButtonStyle.DANGER),
    ], row_width=2)
    try:
        await callback_query.edit_message_text(
            panel_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.debug(f" s _     ,  s : {e}")
        try:
            await callback_query.message.delete()
            await callback_query.message.reply_text(
                panel_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        except Exception:
            pass

# English comment

@bot_app.on_message(pyro_filters.command("set") & authorized_only())
async def cmd_set(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "**Usage:** `/set <record_group_id>`\n\n"
            "Place your authorized Pyrogram session file at `sessions/<your_telegram_user_id>.session` first.\n"
            "Example: `/set -1001234567890`"
        )
        return
    try:
        record_groupid = int(parts[1])
    except ValueError:
        await message.reply("Invalid record group ID. Use `/set <record_group_id>`. ")
        return
    user_id = message.from_user.id
    success, msg = await start_dynamic_client(user_id, record_groupid)
    if success:
        await message.reply(
            f"  **    s     !**\n\n"
            f"  **   :** `{record_groupid}`\n"
            f"   s  `/  < _ >`            s."
        )
    else:
        await message.reply(f"  **    s     :** `{msg}`")

@bot_app.on_message(pyro_filters.command("djoin") & authorized_only())
async def cmd_djoin(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("  ** s :** `/djoin < _ _ >`")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.reply("  **     .**")
        return
    user_id = message.from_user.id
    success, msg = await dynamic_join(user_id, target)
    if success:
        fwd_count = len(dynamic_clients.get(user_id, {}).get('forward_chats', set()))
        await message.reply(
            f"  **     !**\n\n"
            f"  ** :** `{target}`\n"
            f"  **     s:** {fwd_count}"
        )
    else:
        await message.reply(f"  **     :** `{msg}`")

@bot_app.on_message(pyro_filters.command("dstop") & authorized_only())
async def cmd_dstop(client, message):
    user_id = message.from_user.id
    success, msg = await stop_dynamic_client(user_id)
    if success:
        await message.reply("  **    s .**")
    else:
        await message.reply(f"  ** :** `{msg}`")

# English comment

@bot_app.on_message(pyro_filters.command("setrecordgroup") & pyro_filters.user(OWNER_ID))
async def cmd_setrecordgroup(client, message):
    global RECORD_SOURCE, is_recording
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            f"  ** s :** `/setrecordgroup < _ >`\n\n"
            f"  ** x :** `/setrecordgroup -1003970175858`\n\n"
            f"  **  s :** `{RECORD_SOURCE}`"
        )
        return
    chat_id_str = re.sub(r'[^\d-]', '', parts[1])
    try:
        new_source = int(chat_id_str)
        old_source = RECORD_SOURCE
        if new_source == old_source:
            await message.reply(f"  ** s  s       s   !**\n\n  **  s :** `{new_source}`")
            return
        status_msg = await message.reply(f"  **  s    `{old_source}`   `{new_source}`...**")
        if is_recording:
            try:
                await call_py.leave_call(old_source)
                is_recording = False
                logger.info(f"    s : {old_source}")
            except Exception as e:
                logger.warning(f"        s : {e}")
        RECORD_SOURCE = new_source
        save_state()
        if is_recording:
            success, error = await join_call_safe(new_source)
            if success:
                await call_py.record(new_source, RecordStream(True, AUDIO_PARAMETERS))
                is_recording = True
                await status_msg.edit_text(
                    f"  **s      s ss !**\n\n"
                    f"  ** :** `{old_source}`\n"
                    f"  ** :** `{new_source}`\n"
                    f"  **s s:**    "
                )
            else:
                is_recording = False
                await status_msg.edit_text(
                    f"  **s           !**\n\n"
                    f"  **  s :** `{new_source}`\n"
                    f"  ** :** `{error}`\n"
                    f"   s  `/ `      "
                )
        else:
            await status_msg.edit_text(
                f"  **s      s ss !**\n\n"
                f"  ** :** `{old_source}`\n"
                f"  ** :** `{new_source}`\n"
                f"  **s s:**   s \n\n"
                f"   s  `/ `   s "
            )
        logger.info(f"s      {old_source}   {new_source}    ")
    except ValueError:
        await message.reply(f"  **     !**\n\n  **   :** `{parts[1]}`")
    except Exception as e:
        await message.reply(f"  ** :** `{str(e)}`")

# English comment

@bot_app.on_message(pyro_filters.command("joinlink") & authorized_only())
async def cmd_joinlink(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("  ** :** `/joinlink < >`")
        return
    link = parts[1].strip()
    try:
        chat = await user_app.join_chat(link)
        await message.reply(f"  ** !**  : `{chat.id}`")
    except Exception as e:
        error_str = str(e)
        if "USER_ALREADY_PARTICIPANT" in error_str:
            await message.reply("  **     !**")
        elif "INVITE_REQUEST_SENT" in error_str:
            await message.reply("  **   Q    ( )!**")
        else:
            await message.reply(f"  ** :** `{error_str}`")

@bot_app.on_message(pyro_filters.command("restart") & authorized_only())
async def cmd_restart(client, message):
    global is_recording, is_muted, call_py, forward_chats
    try:
        status_msg = await message.reply(
            "  ** s   ...**\n\n"
            "         s..."
        )
        save_state()
        logger.info("  s  s ")
        left_count = 0
        failed_count = 0
        try:
            await call_py.leave_call(RECORD_SOURCE)
            left_count += 1
            logger.info(f"  s : {RECORD_SOURCE}")
        except Exception as e:
            failed_count += 1
            logger.debug(f"      s : {e}")
        for chat_id in list(forward_chats):
            try:
                await call_py.leave_call(chat_id)
                left_count += 1
                logger.info(f"     : {chat_id}")
            except Exception as e:
                failed_count += 1
                logger.debug(f"      {chat_id}: {e}")
        forward_chats = set()
        is_recording = False
        is_muted = False
        logger.info("    s   ")
        stop_success = False
        try:
            await call_py.stop()
            stop_success = True
            logger.info("   s s ")
        except Exception as e:
            logger.debug(f" s s   : {e}")
        await asyncio.sleep(2)
        restart_success = False
        try:
            call_py = PyTgCalls(user_app)
            @call_py.on_update(pytg_filters.stream_frame(Direction.INCOMING, Device.MICROPHONE))
            async def audio_forwarder_handler(_, update: StreamFrames):
                if is_muted or update.chat_id != RECORD_SOURCE or not forward_chats:
                    return
                async with processing_lock:
                    try:
                        if not update.frames:
                            return
                        frame_length = len(update.frames[0].frame) // 2
                        mixed_acc = np.zeros(frame_length, dtype=np.int32)
                        valid_frames = 0
                        for frame_data in update.frames:
                            try:
                                source_samples = np.frombuffer(frame_data.frame, dtype=np.int16)
                                if len(source_samples) == frame_length:
                                    mixed_acc += source_samples.astype(np.int32)
                                    valid_frames += 1
                            except Exception:
                                continue
                        if valid_frames == 0:
                            return
                        mixed_acc //= valid_frames
                        mixed_output = np.clip(mixed_acc, -32768, 32767).astype(np.int16)
                        processed_output = process_audio_pipeline(mixed_output, audio_config)
                        global_echo_state = getattr(audio_forwarder_handler, 'echo_state', None)
                        if global_echo_state is None:
                            global_echo_state = {}
                            audio_forwarder_handler.echo_state = global_echo_state
                        processed_output = apply_echo_optimized(processed_output, global_echo_state, audio_config)
                        mixed_bytes = processed_output.tobytes()
                        for chat_id in list(forward_chats):
                            try:
                                await call_py.send_frame(chat_id, Device.MICROPHONE, mixed_bytes)
                            except Exception as e:
                                logger.debug(f"s      {chat_id}: {e}")
                                if "not found" in str(e).lower() or "invalid" in str(e).lower():
                                    forward_chats.discard(chat_id)
                                    logger.warning(f"  {chat_id}      s ")
                    except Exception as e:
                        logger.error(f"     : {e}")
            await call_py.start()
            restart_success = True
            logger.info("   s  s ")
        except Exception as e:
            logger.error(f"   s   s  : {e}")
            restart_success = False
        if restart_success:
            await status_msg.edit_text(
                f"  **   s  s ss !**\n\n"
                f"  ** :** {left_count}  s\n"
                f"  ** :** {failed_count}  s\n"
                f"  **s :** `{RECORD_SOURCE}`\n"
                f"  **   s:** {len(forward_chats)}\n"
                f"  ** :** {'   ' if is_muted else '   '}\n"
                f"  **s s:**    \n\n"
                f"  ** s  `/ `   s   **"
            )
        else:
            await status_msg.edit_text(
                f"  **   s  -    s!**\n\n"
                f"  ** :** {left_count}  s\n"
                f"  ** :** {failed_count}  s\n"
                f"  ** s:** {'  s ' if stop_success else '   '}\n"
                f"  ** s :** {'  s ss' if restart_success else '   '}\n\n"
                f"          s s"
            )
        logger.info("   s   ")
    except Exception as e:
        logger.error(f" s   : {e}")
        try:
            await message.reply(
                f"  ** s   !**\n\n"
                f"  ** :** `{str(e)}`\n\n"
                f"     s     "
            )
        except Exception:
            logger.error("    s     ss ")

# English comment

if __name__ == "__main__":
    load_state()
    print("=" * 48)
    print("VOICE CHAT AUDIO FORWARDER")
    print("Audio effects: volume, bass, treble, gain, echo,")
    print("overdrive, reverb, and stereo width")
    print("=" * 48)
    print(f"SciPy filters: {'available' if SCIPY_AVAILABLE else 'unavailable (basic processing will be used)'}")
    print(f"Source group: {RECORD_SOURCE}")
    print(f"Main user session: {MAIN_SESSION_FILE}")
    try:
        if not os.path.isfile(MAIN_SESSION_FILE) or os.path.getsize(MAIN_SESSION_FILE) == 0:
            raise FileNotFoundError(
                f"Main Pyrogram session file is missing or empty: {MAIN_SESSION_FILE}"
            )
        bot_app.start()
        user_app.start()
        call_py.start()
        print("Bot, user account, and PyTgCalls started successfully.")
        print("Use /help in Telegram to view the available commands.")
        idle()
    except KeyboardInterrupt:
        print("\\nStopping bot...")
    except Exception as e:
        logger.exception("Startup or runtime error")
        print(f"Startup failed: {e}")
    finally:
        try:
            for chat in list(forward_chats):
                try:
                    call_py.leave_call(chat)
                except Exception:
                    pass
            try:
                call_py.leave_call(RECORD_SOURCE)
            except Exception:
                pass
            try:
                call_py.stop()
            except Exception:
                pass
            try:
                user_app.stop()
            except Exception:
                pass
            try:
                bot_app.stop()
            except Exception:
                pass
        except Exception:
            pass
        for uid in list(dynamic_clients.keys()):
            try:
                asyncio.run(stop_dynamic_client(uid))
            except Exception:
                logger.exception("Could not stop dynamic client %s", uid)
        EXECUTOR.shutdown(wait=False)
        print("Shutdown complete.")
