"""
Please try again. Please try again. Please try again. v7 - Please try again. Please try again.
Please try again.xPlease try again. Please try again. Please try again. Please try again. + Please try again. Please try again.
Please try again. Please try again. Please try again. Please try again.ssPlease try again. Please try again. ZERO-LATENCY
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
    print("Please try again. sPlease try again. Please try again. Please try again. - Please try again.sPlease try again. Please try again. Please try again. Please try again.")

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
API_ID = int(os.getenv("API_ID", "31157048"))
API_HASH = os.getenv("API_HASH", "ed0fea589fd64fe5985a373cb4ad9d84")
BOT_TOKEN = os.getenv("BOT_TOKEN", "9211524304:AAGTmAfAf4iJ3dLaNXHbK6r4fb39SRdq7fw")
OWNER_ID = int(os.getenv("OWNER_ID", "8300072133"))
RECORD_GROUP = int(os.getenv("RECORD_GROUP", "-1004459843210"))

# Session files (Pyrogram SQLite format). Put the main account file beside n.py.
MAIN_SESSION_FILE = "combined_bot.session"
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
bot_app = Client("botn_v7", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
# No session_string: Pyrogram reads useron_v7.session from the current folder.
user_app = Client("useron_v7", api_id=API_ID, api_hash=API_HASH)
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
        logger.error(f"sбіАбі†…™…і…Ґ sбіЫбіАбіЫбіЗ: {e}")

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
        logger.info(f" ЯбіПбіАбіЕбіЗбіЕ sбіЫбіАбіЫбіЗ: {len(approved_users)} біАбіШбіШ АбіПбі†біЗбіЕ біЬsбіЗ А(s), sбіПбіЬ АбіДбіЗ: {RECORD_SOURCE}")
    except FileNotFoundError:
        logger.info("Please try again. sPlease try again. sPlease try again. Please try again. - sPlease try again. Please try again.sPlease try again.")
    except Exception as e:
        logger.error(f"sбіАбі†…™…і…Ґ біЫбіП  ЯбіПбіАбіЕ sбіЫбіАбіЫбіЗ: {e}")

# English comment

async def _authorized_filter(_, __, message):
    user_id = message.from_user.id if message.from_user else None
    if user_id == OWNER_ID or user_id in approved_users:
        return True
    logger.info(f"біЬ…ібіАбіЬбіЫ ЬбіП А…™біҐбіЗбіЕ біАбіДбіДбіЗss “У АбіПбіН {user_id} - …™…Ґ…ібіП А…™…і…Ґ")
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
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    if days > 0:
        return f"{days}біЕ {hours} Ь {minutes}біН {seconds}s"
    elif hours > 0:
        return f"{hours} Ь {minutes}біН {seconds}s"
    elif minutes > 0:
        return f"{minutes}біН {seconds}s"
    else:
        return f"{seconds}s"

def create_progress_bar(value, max_val, length=12):
    filled = int((value / max_val) * length)
    return "Please try again." * filled + "Please try again." * (length - filled)

def get_effect_status(value, max_val):
    percentage = (value / max_val) * 100
    if percentage == 0:
        return "Please try again. Please try again."
    elif percentage <= 30:
        return "Please try again. Please try again."
    elif percentage <= 60:
        return "Please try again. Please try again."
    elif percentage <= 80:
        return "Please try again. sPlease try again."
    else:
        return "Please try again. Please try again.xPlease try again."

# ==================== OPTIMIZED AUDIO PROCESSING PIPELINE ====================

# Pre-computed filter coefficients cache
_filter_cache = {}

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
        logger.error(f"біАбіЕбі†біА…ібіДбіЗбіЕ  ЩбіАss біЗ А АбіП А: {e}")
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
        logger.error(f"біАбіЕбі†біА…ібіДбіЗбіЕ біЫ АбіЗ Щ ЯбіЗ біЗ А АбіП А: {e}")
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
        logger.error(f"біАбіЬбіЕ…™біП біШ АбіПбіДбіЗss…™…і…Ґ біЗ А АбіП А: {e}")
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
                    logger.debug(f"sбіЗ…ібіЕ біЗ А АбіП А біЫбіП {chat_id}: {e}")
                    if "not found" in str(e).lower() or "invalid" in str(e).lower():
                        forward_chats.discard(chat_id)
                        logger.warning(f" АбіЗбіНбіПбі†біЗбіЕ {chat_id} “У АбіПбіН “УбіП Абі°біА АбіЕ…™…і…Ґ  Я…™sбіЫ")
                        
        except Exception as e:
            logger.error(f"біАбіЬбіЕ…™біП  ЬбіА…ібіЕ ЯбіЗ А біЗ А АбіП А: {e}")

# English comment

async def cache_chat_info(chat_id):
    try:
        logger.info(f"біДбіАбіД Ь…™…і…Ґ біД ЬбіАбіЫ …™…і“УбіП “УбіП А {chat_id}...")
        try:
            chat = await user_app.get_chat(chat_id)
            chat_title = chat.title if hasattr(chat, 'title') else str(chat_id)
            logger.info(f"вЬЕ біДбіАбіД ЬбіЗбіЕ: {chat_id} - {chat_title}")
            return True
        except (PeerIdInvalid, ValueError) as e:
            logger.debug(f"біЕ…™ АбіЗбіДбіЫ …ҐбіЗбіЫ_біД ЬбіАбіЫ “УбіА…™ ЯбіЗбіЕ: {e}")
            try:
                async for dialog in user_app.get_dialogs(limit=50):
                    if dialog.chat.id == chat_id:
                        logger.info(f"вЬЕ “УбіПбіЬ…ібіЕ …™…і біЕ…™біА ЯбіП…Ґs: {chat_id}")
                        return True
            except Exception:
                pass
            logger.error(f"вЭМ біДбіА…і…ібіПбіЫ “У…™…ібіЕ біД ЬбіАбіЫ: {chat_id}")
            return False
    except Exception as e:
        logger.error(f"біДбіАбіД ЬбіЗ біЗ А АбіП А “УбіП А {chat_id}: {e}")
        return False

async def join_call_safe(chat_id, call_py_obj=None, user_app_obj=None):
    if call_py_obj is None:
        call_py_obj = call_py
    if user_app_obj is None:
        user_app_obj = user_app
    try:
        if not await cache_chat_info(chat_id):
            return False, "Please try again. Please try again. Please try again. Please try again. Please try again.ssPlease try again."
        try:
            await call_py_obj.play(
                chat_id,
                MediaStream(ExternalMedia.AUDIO, AUDIO_PARAMETERS),
            )
            return True, None
        except NoActiveGroupCall:
            return False, "Please try again. Please try again. Please try again. Please try again."
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
                        logger.debug(f"біЕ П…ібіАбіН…™біД sбіЗ…ібіЕ біЗ А АбіП А біЫбіП {chat_id}: {e}")
                        if "not found" in str(e).lower() or "invalid" in str(e).lower():
                            forward_chats_set.discard(chat_id)
                            logger.warning(f"біЕ П…ібіАбіН…™біД  АбіЗбіНбіПбі†біЗбіЕ {chat_id}")
            except Exception as e:
                logger.error(f"біЕ П…ібіАбіН…™біД  ЬбіА…ібіЕ ЯбіЗ А біЗ А АбіП А: {e}")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info(f"біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ біЫбіАsбіЛ біДбіА…ібіДбіЗ Я ЯбіЗбіЕ “УбіП А {client_data['user_id']}")
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
            logger.info(f"біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ {user_id} sбіЫбіА АбіЫбіЗбіЕ,  АбіЗбіДбіП АбіЕ…™…і…Ґ “У АбіПбіН {record_groupid}")
        else:
            logger.warning(f"біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ {user_id} біДбіПбіЬ ЯбіЕ …ібіПбіЫ біКбіП…™…і: {error}")

        return True, "Please try again. Please try again. sPlease try again."
    except Exception as e:
        logger.error(f"“УбіА…™ ЯбіЗбіЕ біЫбіП sбіЫбіА АбіЫ біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ {user_id}: {e}")
        return False, str(e)

async def stop_dynamic_client(user_id):
    async with dynamic_clients_lock:
        client_data = dynamic_clients.pop(user_id, None)
    if client_data is None:
        return False, "Please try again. Please try again."
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
        logger.info(f"біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ {user_id} sбіЫбіПбіШбіШбіЗбіЕ")
        return True, "sPlease try again."
    except Exception as e:
        logger.error(f"біЗ А АбіП А sбіЫбіПбіШбіШ…™…і…Ґ біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ {user_id}: {e}")
        return False, str(e)

async def dynamic_join(user_id, target_chat):
    async with dynamic_clients_lock:
        client_data = dynamic_clients.get(user_id)
    if client_data is None:
        return False, "Please try again. Please try again. Please try again. Please try again. Please try again.s Please try again.sPlease try again."
    if target_chat in client_data['forward_chats']:
        return False, "Please try again. Please try again. Please try again."
    if target_chat == client_data['record_source']:
        return False, "Please try again. Please try again. Please try again. sPlease try again."
    success, error = await join_call_safe(target_chat, client_data['call_py'], client_data['user_app'])
    if success:
        client_data['forward_chats'].add(target_chat)
        return True, "Please try again."
    else:
        return False, error

# English comment

# English comment

@bot_app.on_message(pyro_filters.command("approve") & pyro_filters.user(OWNER_ID))
async def cmd_approve(client, message):
    try:
        user_id = None
        user_mention = None
        username = None
        first_name = None
        if message.reply_to_message:
            user = message.reply_to_message.from_user
            user_id = user.id
            user_mention = user.mention
            username = user.username or "Please try again. Please try again.sPlease try again."
            first_name = user.first_name or "Please try again."
        else:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply(
                    "Please try again. **Please try again.sPlease try again.:** `/approve` (Please try again. Please try again. Please try again. Please try again.sPlease try again.)\n"
                    "Please try again.: `/approve <Please try again.sPlease try again._Please try again.>`"
                )
                return
            try:
                user_id = int(parts[1])
                try:
                    user = await client.get_users(user_id)
                    user_mention = user.mention
                    username = user.username or "Please try again. Please try again.sPlease try again."
                    first_name = user.first_name or "Please try again."
                except Exception:
                    user_mention = f"біЬsбіЗ А {user_id}"
                    username = "Please try again."
                    first_name = "Please try again."
            except ValueError:
                await message.reply("Please try again. **Please try again. Please try again.sPlease try again. Please try again. Please try again.!**")
                return
        if user_id in approved_users:
            await message.reply(
                f"вДєпЄП **біЬsбіЗ А біА Я АбіЗбіАбіЕ П біАбіШбіШ АбіПбі†біЗбіЕ!**\n\n"
                f"рЯС§ {user_mention}\n"
                f"рЯФҐ `{user_id}`"
            )
            return
        approved_users.add(user_id)
        save_state()
        approve_msg = f"""
вЬЕ **біЬsбіЗ А біАбіШбіШ АбіПбі†біЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯС§ **…ібіАбіНбіЗ:** {first_name} ({user_mention})
рЯФҐ **…™біЕ:** `{user_id}`
рЯУЭ **біЬsбіЗ А…ібіАбіНбіЗ:** @{username}
рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ біАбіШбіШ АбіПбі†біЗбіЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОѓ **біЫ ЬбіЗ П біДбіА…і …ібіПбі° біЬsбіЗ біЫ ЬбіЗ  ЩбіПбіЫ біДбіПбіНбіНбіА…ібіЕs!**
"""
        await message.reply(approve_msg)
        logger.info(f"біЬsбіЗ А {user_id} біАбіШбіШ АбіПбі†біЗбіЕ  Щ П біПбі°…ібіЗ А")
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А:** `{str(e)}`")

@bot_app.on_message(pyro_filters.command("disapprove") & pyro_filters.user(OWNER_ID))
async def cmd_disapprove(client, message):
    try:
        user_id = None
        user_mention = None
        if message.reply_to_message:
            user = message.reply_to_message.from_user
            user_id = user.id
            user_mention = user.mention
        else:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply(
                    "Please try again. **Please try again.sPlease try again.:** `/disapprove` (Please try again. Please try again. Please try again. Please try again.sPlease try again.)\n"
                    "Please try again.: `/disapprove <Please try again.sPlease try again._Please try again.>`"
                )
                return
            try:
                user_id = int(parts[1])
                try:
                    user = await client.get_users(user_id)
                    user_mention = user.mention
                except Exception:
                    user_mention = f"біЬsбіЗ А {user_id}"
            except ValueError:
                await message.reply("Please try again. **Please try again. Please try again.sPlease try again. Please try again. Please try again.!**")
                return
        if user_id not in approved_users:
            await message.reply(
                f"вДєпЄП **біЬsбіЗ А …ібіПбіЫ “УбіПбіЬ…ібіЕ …™…і біАбіШбіШ АбіПбі†біЗбіЕ  Я…™sбіЫ!**\n\n"
                f"рЯС§ {user_mention}\n"
                f"рЯФҐ `{user_id}`"
            )
            return
        approved_users.discard(user_id)
        save_state()
        disapprove_msg = f"""
вЭМ **біЬsбіЗ А біЕ…™sбіАбіШбіШ АбіПбі†біЗбіЕ!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯС§ **…ібіАбіНбіЗ:** {user_mention}
рЯФҐ **…™біЕ:** `{user_id}`
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі  АбіЗбіНбіПбі†біЗбіЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯЪЂ **біЫ ЬбіЗ П біДбіА…і …ібіП біЬsбіЗ біЫ ЬбіЗ  ЩбіПбіЫ біДбіПбіНбіНбіА…ібіЕs!**
"""
        await message.reply(disapprove_msg)
        logger.info(f"біЬsбіЗ А {user_id} біЕ…™sбіАбіШбіШ АбіПбі†біЗбіЕ  Щ П біПбі°…ібіЗ А")
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А:** `{str(e)}`")

@bot_app.on_message(pyro_filters.command("userlist") & pyro_filters.user(OWNER_ID))
async def cmd_userlist(client, message):
    try:
        if not approved_users:
            await message.reply(
                "Please try again. **Please try again. Please try again.sPlease try again.s Please try again. Please try again. Please try again..**\n\n"
                "Please try again.sPlease try again. `/approve` Please try again. Please try again. Please try again.sPlease try again.s."
            )
            return
        user_list = []
        total = len(approved_users)
        processed = 0
        for user_id in approved_users:
            processed += 1
            try:
                user = await client.get_users(user_id)
                username = f"@{user.username}" if user.username else "Please try again. Please try again.sPlease try again."
                mention = user.mention
                user_list.append(f"вАҐ {mention}\n  рЯФҐ `{user_id}` | {username}")
            except Exception:
                user_list.append(f"вАҐ біЬsбіЗ А `{user_id}` (вЪ†пЄП біДбіПбіЬ ЯбіЕ …ібіПбіЫ “УбіЗбіЫбіД Ь)")
        response = f"""
рЯФ• **біАбіШбіШ АбіПбі†біЗбіЕ біЬsбіЗ Аs**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **біЫбіПбіЫбіА Я:** {total} біЬsбіЗ Аs
рЯУМ **біШ АбіПбіДбіЗss…™…і…Ґ:** {processed}/{total}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

"""
        response += "\n\n".join(user_list)
        response += f"\n\nвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА\nвЬЕ **біЫбіПбіЫбіА Я:** {total}"
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Please try again. Please try again.sPlease try again.", callback_data="refresh_userlist"),
                InlineKeyboardButton("Please try again. sPlease try again.s", callback_data="userlist_stats"),
            ],
            [
                InlineKeyboardButton("Please try again. Please try again.", callback_data="back_start"),
            ]
        ])
        if len(response) > 4000:
            parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    await message.reply(part, reply_markup=buttons)
                else:
                    await message.reply(part)
        else:
            await message.reply(response, reply_markup=buttons)
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А:** `{str(e)}`")

# English comment

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
        await callback_query.answer("Please try again. Please try again.!", show_alert=True)
        return
    await callback_query.answer()
    if data == "refresh_userlist":
        if not approved_users:
            keyboard = build_keyboard([
                ("Please try again. Please try again.", "help_info", ButtonStyle.SUCCESS),
                ("Please try again. Please try again.", "back_start", ButtonStyle.PRIMARY)
            ], row_width=2)
            await callback_query.edit_message_text(
                "Please try again. **Please try again. Please try again.sPlease try again.s Please try again. Please try again. Please try again..**",
                reply_markup=keyboard
            )
            return
        user_list = []
        for uid in approved_users:
            try:
                user = await client.get_users(uid)
                username = f"@{user.username}" if user.username else "Please try again. Please try again.sPlease try again."
                mention = user.mention
                user_list.append(f"вАҐ {mention}\n  рЯФҐ `{uid}` | {username}")
            except Exception:
                user_list.append(f"вАҐ біЬsбіЗ А `{uid}` (вЪ†пЄП біДбіПбіЬ ЯбіЕ …ібіПбіЫ “УбіЗбіЫбіД Ь)")
        response = f"""
рЯФ• **біАбіШбіШ АбіПбі†біЗбіЕ біЬsбіЗ Аs** (рЯФД  АбіЗ“У АбіЗs ЬбіЗбіЕ)
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **біЫбіПбіЫбіА Я:** {len(approved_users)} біЬsбіЗ Аs
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
"""
        response += "\n\n".join(user_list)
        response += f"\n\nвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА\nвЬЕ **біЫбіПбіЫбіА Я:** {len(approved_users)}"
        keyboard = build_keyboard([
            ("Please try again. Please try again.sPlease try again.", "refresh_userlist", ButtonStyle.PRIMARY),
            ("Please try again. sPlease try again.s", "userlist_stats", ButtonStyle.PRIMARY),
            ("Please try again. Please try again.", "back_start", ButtonStyle.SUCCESS)
        ], row_width=2)
        await callback_query.edit_message_text(response, reply_markup=keyboard)
    elif data == "userlist_stats":
        total = len(approved_users)
        stats_msg = f"""
рЯУК **біЬsбіЗ А sбіЫбіАбіЫ…™sбіЫ…™біДs**
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯФ• **біЫбіПбіЫбіА Я:** {total}
рЯУМ **sбіЫбіАбіЫбіЬs:** {'Please try again. Please try again.' if total > 0 else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУИ **біШ АбіП…Ґ АбіЗss**
{('Please try again.' * min(total, 10)) + ('Please try again.' * (10 - min(total, 10))) if total > 0 else 'Please try again.'}
вЪ° **біЬsбіА…ҐбіЗ:** {'Please try again.' if total < 50 else 'Please try again.' if total < 100 else 'Please try again.x'}
"""
        keyboard = build_keyboard([
            ("Please try again. Please try again.", "back_userlist", ButtonStyle.PRIMARY)
        ], row_width=1)
        await callback_query.edit_message_text(stats_msg, reply_markup=keyboard)
    elif data == "back_userlist":
        if not approved_users:
            keyboard = build_keyboard([
                ("Please try again. Please try again.", "help_info", ButtonStyle.SUCCESS),
                ("Please try again. Please try again.", "back_start", ButtonStyle.PRIMARY)
            ], row_width=2)
            await callback_query.edit_message_text(
                "Please try again. **Please try again. Please try again.sPlease try again.s Please try again. Please try again.**\n\nPlease try again.sPlease try again. `/approve` Please try again. Please try again.",
                reply_markup=keyboard
            )
            return
        user_list = []
        for uid in approved_users:
            try:
                user = await client.get_users(uid)
                username = f"@{user.username}" if user.username else "Please try again. Please try again.sPlease try again."
                mention = user.mention
                user_list.append(f"вАҐ {mention}\n  рЯФҐ `{uid}` | {username}")
            except Exception:
                user_list.append(f"вАҐ біЬsбіЗ А `{uid}` (вЪ†пЄП біДбіПбіЬ ЯбіЕ …ібіПбіЫ “УбіЗбіЫбіД Ь)")
        response = f"""
рЯФ• **біАбіШбіШ АбіПбі†біЗбіЕ біЬsбіЗ Аs**
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **біЫбіПбіЫбіА Я:** {len(approved_users)}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
"""
        response += "\n\n".join(user_list)
        response += f"\n\nвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА\nвЬЕ **біЫбіПбіЫбіА Я:** {len(approved_users)}"
        keyboard = build_keyboard([
            ("Please try again. Please try again.sPlease try again.", "refresh_userlist", ButtonStyle.PRIMARY),
            ("Please try again. sPlease try again.s", "userlist_stats", ButtonStyle.PRIMARY),
            ("Please try again. Please try again.", "back_start", ButtonStyle.SUCCESS)
        ], row_width=2)
        await callback_query.edit_message_text(response, reply_markup=keyboard)
    elif data == "help_info":
        help_text = """
Please try again. **Please try again. Please try again.**
Please try again.
Please try again. **Please try again. Please try again.s**
/record - sPlease try again. Please try again.
/join <Please try again.> - Please try again. Please try again. Please try again.
/rejoin - Please try again. Please try again.
/leave <Please try again.> - sPlease try again. Please try again.
/leaveall - sPlease try again. Please try again.
/leaverecord - Please try again. sPlease try again.
/mute - Please try again.
/unmute - Please try again.
Please try again.
Please try again. **Please try again.s** (Please try again. Please try again.s!)
/level <0-Please try again.> - Please try again.
/bass <0-Please try again.> - Please try again.ss
/treble <0-Please try again.> - Please try again.
/gain <0-Please try again.> - Please try again.
/overdrive <0-Please try again.> - Please try again.sPlease try again./Please try again.
/echo <Please try again./Please try again./Please try again.> - Please try again.
/effects - sPlease try again. Please try again.s
/reset - Please try again.sPlease try again. Please try again.
Please try again.
Please try again. **Please try again.**
/ping - Please try again. Please try again.
/stats - Please try again. sPlease try again.s
/status - sPlease try again.sPlease try again. sPlease try again.s
/list - Please try again. Please try again.sPlease try again.
/id - Please try again. Please try again. Please try again.
/panel - Please try again. Please try again.
Please try again.
Please try again. **Please try again.sPlease try again. Please try again.** (Please try again.)
/approve - Please try again. Please try again.sPlease try again.
/disapprove - Please try again.
/userlist - Please try again.sPlease try again. Please try again.sPlease try again.s
/setrecordgroup <Please try again.> - Please try again. sPlease try again.
/restart - Please try again.sPlease try again. Please try again.
"""
        keyboard = build_keyboard([
            ("Please try again. Please try again.", "back_start", ButtonStyle.SUCCESS)
        ], row_width=1)
        await callback_query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    elif data == "back_start":
        user = callback_query.from_user
        first_name = escape_markdown(user.first_name or "Please try again.sPlease try again.")
        last_name = escape_markdown(user.last_name or "")
        username = f"@{user.username}" if user.username else ""
        welcome_text = f"""
вЬ® **бі°біЗ ЯбіДбіПбіНбіЗ біЫбіП біАбіЬбіЕ…™біП “УбіП Абі°біА АбіЕбіЗ А** вЬ®
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯСЛ ** ЬбіЗ Я ЯбіП, {first_name}!**
{last_name}
{username}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОµ ** АбіЗбіА Я-біЫ…™біНбіЗ біАбіЬбіЕ…™біП “УбіП Абі°біА АбіЕ…™…і…Ґ**
рЯУК **s ПsбіЫбіЗбіН:** вЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИ 100% вЬЕ
вЪ° **“УбіЗбіАбіЫбіЬ АбіЗs:**
вАҐ  АбіЗбіА Я-біЫ…™біНбіЗ “УбіП Абі°біА АбіЕ…™…і…Ґ
вАҐ біАбіЕбі†біА…ібіДбіЗбіЕ біЗ“У“УбіЗбіДбіЫs
вАҐ бі†біП ЯбіЬбіНбіЗ біДбіП…ібіЫ АбіП Я
вАҐ біНбіЬ ЯбіЫ…™-біД ЬбіАбіЫ “УбіП Абі°біА АбіЕ…™…і…Ґ
вАҐ  ЩбіАss/біЫ АбіЗ Щ ЯбіЗ  ЩбіПбіПsбіЫ
вАҐ біЬ…і Я…™біН…™біЫбіЗбіЕ біЗбіД ЬбіП
вАҐ біЕ…™sбіЫбіП АбіЫ…™П…і/…ҐбіА…™…і  ЩбіП“У“УбіЗбіДбіЫ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУМ **біЬsбіЗ / ЬбіЗ ЯбіШ “УбіП А біДбіПбіНбіНбіА…ібіЕs**
"""
        keyboard = build_keyboard([
            ("Please try again. Please try again.", "owner", ButtonStyle.PRIMARY),
            ("Please try again. Please try again.", "help_info", ButtonStyle.PRIMARY)
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
            logger.error(f" ЩбіАбіДбіЛ_sбіЫбіА АбіЫ біЗ А АбіП А: {e}")
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
            ("Please try again. Please try again.", "back_start", ButtonStyle.SUCCESS)
        ], row_width=1)
        await callback_query.edit_message_text(
            "Please try again. **Please try again.**\n\n"
            "Please try again. @RAJAJIBOLOJI\n"
            "Please try again. [Please try again.](t.me/RAJAJIBOLOJI)",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

# English comment

@bot_app.on_message(pyro_filters.command("start"))
async def cmd_start(client, message):
    user_id = message.from_user.id if message.from_user else None
    if user_id != OWNER_ID and user_id not in approved_users:
        logger.info(f"біЬ…ібіАбіЬбіЫ ЬбіП А…™біҐбіЗбіЕ /sбіЫбіА АбіЫ “У АбіПбіН {user_id}")
        return
    user = message.from_user
    first_name = escape_markdown(user.first_name or "Please try again.sPlease try again.")
    last_name = escape_markdown(user.last_name or "")
    username = f"@{user.username}" if user.username else ""
    welcome_text = f"""
вЬ® **бі°біЗ ЯбіДбіПбіНбіЗ біЫбіП біАбіЬбіЕ…™біП “УбіП Абі°біА АбіЕбіЗ А** вЬ®
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯСЛ ** ЬбіЗ Я ЯбіП, {first_name}!**
{last_name}
{username}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОµ ** АбіЗбіА Я-біЫ…™біНбіЗ біАбіЬбіЕ…™біП “УбіП Абі°біА АбіЕ…™…і…Ґ**
рЯУК **s ПsбіЫбіЗбіН:** вЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИвЦИ 100% вЬЕ
вЪ° **“УбіЗбіАбіЫбіЬ АбіЗs:**
вАҐ  АбіЗбіА Я-біЫ…™біНбіЗ “УбіП Абі°біА АбіЕ…™…і…Ґ
вАҐ біАбіЕбі†біА…ібіДбіЗбіЕ біЗ“У“УбіЗбіДбіЫs
вАҐ бі†біП ЯбіЬбіНбіЗ біДбіП…ібіЫ АбіП Я
вАҐ біНбіЬ ЯбіЫ…™-біД ЬбіАбіЫ “УбіП Абі°біА АбіЕ…™…і…Ґ
вАҐ  ЩбіАss/біЫ АбіЗ Щ ЯбіЗ  ЩбіПбіПsбіЫ
вАҐ біЬ…і Я…™біН…™біЫбіЗбіЕ біЗбіД ЬбіП
вАҐ біЕ…™sбіЫбіП АбіЫ…™П…і/…ҐбіА…™…і  ЩбіП“У“УбіЗбіДбіЫ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУМ **біЬsбіЗ / ЬбіЗ ЯбіШ “УбіП А біДбіПбіНбіНбіА…ібіЕs**
"""
    keyboard = build_keyboard([
        ("Please try again. Please try again.", "owner", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.", "help_info", ButtonStyle.PRIMARY)
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
        logger.debug(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ …ҐбіЗбіЫ біШ АбіП“У…™ ЯбіЗ біШ ЬбіПбіЫбіП: {e}")
    await message.reply(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# English comment

@bot_app.on_message(pyro_filters.command("help") & authorized_only())
async def cmd_help(client, message):
    help_text = """
Please try again. **Please try again. Please try again.**
Please try again.
Please try again. **Please try again. Please try again.s**
/record - sPlease try again. Please try again.
/join <Please try again.> - Please try again. Please try again. Please try again.
/rejoin - Please try again. Please try again.
/leave <Please try again.> - sPlease try again. Please try again.
/leaveall - sPlease try again. Please try again.
/leaverecord - Please try again. sPlease try again.
/mute - Please try again.
/unmute - Please try again.
Please try again.
Please try again. **Please try again.s** (Please try again. Please try again.s!)
/level <0-Please try again.> - Please try again.
/bass <0-Please try again.> - Please try again.ss
/treble <0-Please try again.> - Please try again.
/gain <0-Please try again.> - Please try again.
/overdrive <0-Please try again.> - Please try again.sPlease try again./Please try again.
/echo <Please try again./Please try again./Please try again.> - Please try again.
/effects - sPlease try again. Please try again.s
/reset - Please try again.sPlease try again. Please try again.
Please try again.
Please try again. **Please try again.**
/ping - Please try again. Please try again.
/stats - Please try again. sPlease try again.s
/status - sPlease try again.sPlease try again. sPlease try again.s
/list - Please try again. Please try again.sPlease try again.
/id - Please try again. Please try again. Please try again.
/panel - Please try again. Please try again.
Please try again.
Please try again. **Please try again.sPlease try again. Please try again.** (Please try again.)
/approve - Please try again. Please try again.sPlease try again.
/disapprove - Please try again.
/userlist - Please try again.sPlease try again. Please try again.sPlease try again.s
/setrecordgroup <Please try again.> - Please try again. sPlease try again.
/restart - Please try again.sPlease try again. Please try again.
"""
    keyboard = build_keyboard([
        ("Please try again. Please try again.", "back_start", ButtonStyle.SUCCESS),
        ("Please try again. Please try again.", "owner", ButtonStyle.PRIMARY)
    ], row_width=2)
    await message.reply(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

# English comment

@bot_app.on_message(pyro_filters.command("id") & pyro_filters.user(OWNER_ID))
async def cmd_id(client, message):
    chat_type = "Please try again." if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else "Please try again."
    id_msg = f"""
рЯУ± **біД ЬбіАбіЫ …™…і“УбіП АбіНбіАбіЫ…™біП…і**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯФҐ **біД ЬбіАбіЫ …™біЕ:** `{message.chat.id}`
рЯУМ **біЫ ПбіШбіЗ:** {chat_type}
рЯУЭ **біЫ…™біЫ ЯбіЗ:** {message.chat.title or 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

вЬЕ **біДбіПбіШ П біЫ Ь…™s …™біЕ “УбіП А біЬsбіЗ …™…і біДбіПбіНбіНбіА…ібіЕs**
"""
    await message.reply(id_msg)

@bot_app.on_message(pyro_filters.command("ping") & authorized_only())
async def cmd_ping(client, message):
    start = time.time()
    msg = await message.reply("Please try again. Please try again....")
    end = time.time()
    ping = round((end - start) * 1000)
    await msg.edit_text(
        f"рЯПУ **біШбіП…і…Ґ!**\n\n"
        f"рЯУ° **біШ…™…і…Ґ:** `{ping}біНs`\n"
        f"вП±пЄП **біЬбіШбіЫ…™біНбіЗ:** `{get_uptime()}`"
    )

@bot_app.on_message(pyro_filters.command("stats") & pyro_filters.user(OWNER_ID))
async def cmd_stats(client, message):
    stats_msg = f"""
рЯУК ** ЩбіПбіЫ sбіЫбіАбіЫ…™sбіЫ…™біДs**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
вП±пЄП **біЬбіШбіЫ…™біНбіЗ:** `{get_uptime()}`
рЯФ• **біАбіШбіШ АбіПбі†біЗбіЕ біЬsбіЗ Аs:** {len(approved_users)}
рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕs:** {len(forward_chats)}
рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`
рЯФК **біАбіЬбіЕ…™біП:** {'Please try again. Please try again.' if is_muted else 'Please try again. Please try again.'}
рЯОµ ** АбіЗбіДбіП АбіЕ…™…і…Ґ:** {'Please try again. Please try again.' if is_recording else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОЫпЄП **біАбіДбіЫ…™бі†біЗ біЗ“У“УбіЗбіДбіЫs**
вАҐ бі†біП ЯбіЬбіНбіЗ: `{audio_config['volume']}%`
вАҐ  ЩбіАss: `{audio_config['bass']}`
вАҐ біЫ АбіЗ Щ ЯбіЗ: `{audio_config['treble']}`
вАҐ …ҐбіА…™…і: `{audio_config['gain']}`
вАҐ біЕ…™sбіЫбіП АбіЫ…™П…і: `{audio_config['overdrive']}`
вАҐ біЗбіД ЬбіП біЕбіЗ ЯбіА П: `{audio_config['echo_delay']}ms`
вАҐ біЗбіД ЬбіП біЕбіЗбіДбіА П: `{audio_config['echo_decay']}`
"""
    await message.reply(stats_msg)

# English comment

@bot_app.on_message(pyro_filters.command("record") & authorized_only())
async def cmd_record(client, message):
    global is_recording
    if is_recording:
        await message.reply(
            "Please try again. **Please try again. Please try again.!**\n\n"
            f"рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`\n"
            f"рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)} біД ЬбіАбіЫs"
        )
        return
    try:
        status_msg = await message.reply(
            "Please try again. **sPlease try again. Please try again....**\n\n"
            "Please try again. Please try again. Please try again. sPlease try again...."
        )
        success, error = await join_call_safe(RECORD_SOURCE)
        if success:
            await call_py.record(RECORD_SOURCE, RecordStream(True, AUDIO_PARAMETERS))
            is_recording = True
            record_msg = f"""
вЬЕ ** АбіЗбіДбіП АбіЕ…™…і…Ґ sбіЫбіА АбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`
рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)} біД ЬбіАбіЫs
рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ  Я…™бі†біЗ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ **біАбіЬбіЕ…™біП …™s …ібіПбі° “У ЯбіПбі°…™…і…Ґ!**
"""
            await status_msg.edit_text(record_msg)
            logger.info("Please try again. sPlease try again.")
        else:
            await status_msg.edit_text(
                f"вЭМ **“УбіА…™ ЯбіЗбіЕ біЫбіП sбіЫбіА АбіЫ  АбіЗбіДбіП АбіЕ…™…і…Ґ!**\n\n"
                f"вЪ†пЄП **біЗ А АбіП А:** `{error}`\n\n"
                f"рЯТ° біНбіАбіЛбіЗ sбіЬ АбіЗ біД ЬбіАбіЫ …™s біАбіДбіЫ…™бі†біЗ"
            )
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А біПбіДбіДбіЬ А АбіЗбіЕ!**\n\nвЪ†пЄП `{str(e)}`")

@bot_app.on_message(pyro_filters.command("join") & authorized_only())
async def cmd_join(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        join_help = """
Please try again. **Please try again.sPlease try again.:** `/join <Please try again._Please try again.>`

Please try again.
Please try again. **Please try again.xPlease try again.:**
`/join -1003929100976`

Please try again. **Please try again. Please try again. Please try again. Please try again. Please try again.:**
Please try again. Please try again. Please try again. Please try again.ssPlease try again. Please try again. @sPlease try again.sPlease try again.
Please try again. Please try again. Please try again.sPlease try again. `/Please try again.` Please try again. Please try again. Please try again. (Please try again.)
Please try again.

Please try again. **Please try again.:** Please try again. Please try again. Please try again.sPlease try again. Please try again. Please try again.
"""
        await message.reply(join_help)
        return
    chat_id_str = re.sub(r'[^\d-]', '', parts[1])
    try:
        chat_id = int(chat_id_str)
        if chat_id in forward_chats:
            await message.reply(
                f"вЪ†пЄП **біА Я АбіЗбіАбіЕ П “УбіП Абі°біА АбіЕ…™…і…Ґ біЫбіП біЫ Ь…™s біД ЬбіАбіЫ!**\n\n"
                f"рЯОѓ `{chat_id}`\n"
                f"рЯУ§ **біЫбіПбіЫбіА Я:** {len(forward_chats)} біД ЬбіАбіЫs"
            )
            return
        if chat_id == RECORD_SOURCE:
            await message.reply(
                "Please try again. **Please try again. Please try again. Please try again. sPlease try again. Please try again.!**\n\n"
                f"рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`\n"
                "Please try again. Please try again.sPlease try again. Please try again. Please try again. Please try again. Please try again. Please try again."
            )
            return
        status_msg = await message.reply(
            f"рЯФД **біДбіП…і…ібіЗбіДбіЫ…™…і…Ґ біЫбіП `{chat_id}`...**\n\n"
            "Please try again. Please try again.sPlease try again.sPlease try again. Please try again. Please try again...."
        )
        success, error = await join_call_safe(chat_id)
        if success:
            forward_chats.add(chat_id)
            join_msg = f"""
вЬЕ **“УбіП Абі°біА АбіЕ…™…і…Ґ sбіЫбіА АбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОѓ **біЫбіА А…ҐбіЗбіЫ:** `{chat_id}`
рЯУ§ **біЫбіПбіЫбіА Я біДбіП…і…ібіЗбіДбіЫ…™біП…іs:** {len(forward_chats)}
рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ біДбіП…і…ібіЗбіДбіЫбіЗбіЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ **біАбіЬбіЕ…™біП …™s …ібіПбі° “У ЯбіПбі°…™…і…Ґ біЫбіП біЫ Ь…™s біД ЬбіАбіЫ!**
"""
            await status_msg.edit_text(join_msg)
            logger.info(f"біКбіП…™…ібіЗбіЕ {chat_id}")
        else:
            await status_msg.edit_text(
                f"вЭМ **“УбіА…™ ЯбіЗбіЕ біЫбіП біКбіП…™…і біД ЬбіАбіЫ!**\n\n"
                f"вЪ†пЄП **біЗ А АбіП А:** `{error}`\n\n"
                f"рЯТ° **біЫ АбіПбіЬ Щ ЯбіЗs ЬбіПбіПбіЫ…™…і…Ґ:**\n"
                f"вАҐ біЗ…іsбіЬ АбіЗ біД ЬбіАбіЫ …™s біАбіДбіЫ…™бі†біЗ\n"
                f"вАҐ біД ЬбіЗбіДбіЛ …™“У  ЩбіПбіЫ …™s біАбіЕбіН…™…і\n"
                f"вАҐ бі†біЗ А…™“У П біД ЬбіАбіЫ …™біЕ …™s біДбіП А АбіЗбіДбіЫ"
            )
    except ValueError:
        await message.reply(
            f"вЭМ **…™…ібі†біА Я…™біЕ біД ЬбіАбіЫ …™біЕ “УбіП АбіНбіАбіЫ!**\n\n"
            f"рЯУМ ** ПбіПбіЬ біЗ…ібіЫбіЗ АбіЗбіЕ:** `{parts[1]}`\n"
            f"рЯТ° біЬsбіЗ біА …ібіЬбіНбіЗ А…™біД …™біЕ (біЗ.…Ґ., `-1003929100976`)"
        )
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А біПбіДбіДбіЬ А АбіЗбіЕ!**\n\nвЪ†пЄП `{str(e)}`")

# English comment

@bot_app.on_message(pyro_filters.command("rejoin") & authorized_only())
async def cmd_rejoin(client, message):
    global is_recording
    status_msg = await message.reply(
        "Please try again. **Please try again. Please try again. Please try again.s...**\n\n"
        "Please try again. Please try again.sPlease try again. Please try again. Please try again. Please try again. Please try again.s..."
    )
    rejoin_results = {
        "source": {"status": "Please try again.", "error": None},
        "forwards": {"total": 0, "success": 0, "failed": 0, "errors": []}
    }
    was_recording = is_recording
    source_chat = RECORD_SOURCE
    if was_recording:
        try:
            await call_py.leave_call(source_chat)
            logger.info(f" ЯбіЗ“УбіЫ sбіПбіЬ АбіДбіЗ {source_chat} “УбіП А  АбіЗбіКбіП…™…і")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ  ЯбіЗбіАбі†біЗ sбіПбіЬ АбіДбіЗ: {e}")
        try:
            success, error = await join_call_safe(source_chat)
            if success:
                await call_py.record(source_chat, RecordStream(True, AUDIO_PARAMETERS))
                is_recording = True
                rejoin_results["source"]["status"] = "Please try again."
                logger.info(f" АбіЗбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ sбіПбіЬ АбіДбіЗ {source_chat} sбіЬбіДбіДбіЗss“УбіЬ Я Я П")
            else:
                is_recording = False
                rejoin_results["source"]["status"] = "Please try again."
                rejoin_results["source"]["error"] = error
                logger.error(f"“УбіА…™ ЯбіЗбіЕ біЫбіП  АбіЗбіДбіП…і…ібіЗбіДбіЫ sбіПбіЬ АбіДбіЗ: {error}")
        except Exception as e:
            is_recording = False
            rejoin_results["source"]["status"] = "Please try again."
            rejoin_results["source"]["error"] = str(e)
            logger.error(f"біЗ А АбіП А  АбіЗбіДбіП…і…ібіЗбіДбіЫ…™…і…Ґ sбіПбіЬ АбіДбіЗ: {e}")
    else:
        rejoin_results["source"]["status"] = "Please try again."
        rejoin_results["source"]["error"] = "Please try again. Please try again."
    forward_list = list(forward_chats)
    rejoin_results["forwards"]["total"] = len(forward_list)
    if forward_list:
        for chat_id in forward_list:
            try:
                await call_py.leave_call(chat_id)
                logger.info(f" ЯбіЗ“УбіЫ “УбіП Абі°біА АбіЕ біД ЬбіАбіЫ {chat_id} “УбіП А  АбіЗбіКбіП…™…і")
            except Exception as e:
                logger.debug(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ  ЯбіЗбіАбі†біЗ {chat_id}: {e}")
        await asyncio.sleep(1.5)
        for chat_id in forward_list:
            try:
                success, error = await join_call_safe(chat_id)
                if success:
                    rejoin_results["forwards"]["success"] += 1
                    logger.info(f" АбіЗбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ “УбіП Абі°біА АбіЕ біД ЬбіАбіЫ {chat_id} sбіЬбіДбіДбіЗss“УбіЬ Я Я П")
                else:
                    rejoin_results["forwards"]["failed"] += 1
                    rejoin_results["forwards"]["errors"].append(f"`{chat_id}`: {error[:50]}")
                    logger.error(f"“УбіА…™ ЯбіЗбіЕ біЫбіП  АбіЗбіДбіП…і…ібіЗбіДбіЫ {chat_id}: {error}")
                    forward_chats.discard(chat_id)
            except Exception as e:
                rejoin_results["forwards"]["failed"] += 1
                rejoin_results["forwards"]["errors"].append(f"`{chat_id}`: {str(e)[:50]}")
                forward_chats.discard(chat_id)
                logger.error(f"біЗ А АбіП А  АбіЗбіДбіП…і…ібіЗбіДбіЫ…™…і…Ґ {chat_id}: {e}")
    else:
        rejoin_results["forwards"]["status"] = "Please try again."
        rejoin_results["forwards"]["error"] = "Please try again. Please try again. Please try again.s"
    response = f"""
рЯФД ** АбіЗбіДбіП…і…ібіЗбіДбіЫ біДбіПбіНбіШ ЯбіЗбіЫбіЗ!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ° **sбіПбіЬ АбіДбіЗ біД ЬбіАбіЫ:** `{source_chat}`
{'Please try again. Please try again.' if rejoin_results['source']['status'] == 'Please try again.' else 'Please try again. Please try again.' if rejoin_results['source']['status'] == 'Please try again.' else 'Please try again. Please try again. Please try again.'}
"""
    if rejoin_results['source']['error']:
        response += f"вЪ†пЄП **біЗ А АбіП А:** `{rejoin_results['source']['error']}`\n"
    response += f"""
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ§ **“УбіП Абі°біА АбіЕ sбіЫбіАбіЫбіЬs:**
вАҐ **біЫбіПбіЫбіА Я:** {rejoin_results['forwards']['total']}
вАҐ **вЬЕ sбіЬбіДбіДбіЗss:** {rejoin_results['forwards']['success']}
вАҐ **вЭМ “УбіА…™ ЯбіЗбіЕ:** {rejoin_results['forwards']['failed']}
"""
    if rejoin_results['forwards']['errors']:
        response += "\nPlease try again. **Please try again. Please try again.s:**\n"
        for err in rejoin_results['forwards']['errors'][:5]:
            response += f"вАҐ {err}\n"
        if len(rejoin_results['forwards']['errors']) > 5:
            response += f"вАҐ ... біА…ібіЕ {len(rejoin_results['forwards']['errors'])-5} біНбіП АбіЗ\n"
    response += f"""
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **“У…™…ібіА Я sбіЫбіАбіЫбіЬs:**
вАҐ ** АбіЗбіДбіП АбіЕ…™…і…Ґ:** {'Please try again. Please try again.' if is_recording else 'Please try again. Please try again.'}
вАҐ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)} біД ЬбіАбіЫs
вАҐ **біАбіЬбіЕ…™біП:** {'Please try again. Please try again.' if is_muted else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯТ° **…ібіПбіЫбіЗ:** “УбіА…™ ЯбіЗбіЕ біД ЬбіАбіЫs бі°біЗ АбіЗ біАбіЬбіЫбіПбіНбіАбіЫ…™біДбіА Я Я П  АбіЗбіНбіПбі†біЗбіЕ “У АбіПбіН “УбіП Абі°біА АбіЕ…™…і…Ґ  Я…™sбіЫ
"""
    await status_msg.edit_text(response)
    logger.info(f" АбіЗбіДбіП…і…ібіЗбіДбіЫ біДбіПбіНбіШ ЯбіЗбіЫбіЗбіЕ: sбіПбіЬ АбіДбіЗ={rejoin_results['source']['status']}, “УбіП Абі°біА АбіЕs={rejoin_results['forwards']['success']}/{rejoin_results['forwards']['total']}")

# English comment

@bot_app.on_message(pyro_filters.command("leaverecord") & authorized_only())
async def cmd_leaverecord(client, message):
    global is_recording
    try:
        status_msg = await message.reply("Please try again. **Please try again. sPlease try again. Please try again....**")
        await call_py.leave_call(RECORD_SOURCE)
        is_recording = False
        leave_msg = f"""
вЬЕ ** ЯбіЗ“УбіЫ sбіПбіЬ АбіДбіЗ біД ЬбіАбіЫ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі біЕ…™sбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ
рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ ** АбіЗбіДбіП АбіЕ…™…і…Ґ  ЬбіАs  ЩбіЗбіЗ…і sбіЫбіПбіШбіШбіЗбіЕ!**
"""
        await status_msg.edit_text(leave_msg)
        logger.info("Please try again. Please try again. Please try again.")
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А біПбіДбіДбіЬ А АбіЗбіЕ!**\n\nвЪ†пЄП `{str(e)}`")

@bot_app.on_message(pyro_filters.command("leave") & authorized_only())
async def cmd_leave(client, message):
    parts = message.text.split()
    if len(parts) >= 2:
        chat_id_str = re.sub(r'[^\d-]', '', parts[1])
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            await message.reply(
                f"вЭМ **…™…ібі†біА Я…™біЕ біД ЬбіАбіЫ …™біЕ!**\n\n"
                f"рЯУМ ** ПбіПбіЬ біЗ…ібіЫбіЗ АбіЗбіЕ:** `{parts[1]}`\n"
                f"рЯТ° біЬsбіЗ біА …ібіЬбіНбіЗ А…™біД …™біЕ (біЗ.…Ґ., `-1003929100976`)"
            )
            return
        if chat_id not in forward_chats:
            await message.reply(
                f"вЪ†пЄП **…ібіПбіЫ “УбіП Абі°біА АбіЕ…™…і…Ґ біЫбіП біЫ Ь…™s біД ЬбіАбіЫ!**\n\nрЯОѓ `{chat_id}`"
            )
            return
        try:
            status_msg = await message.reply(f"рЯФД ** ЯбіЗбіАбі†…™…і…Ґ `{chat_id}`...**")
            await call_py.leave_call(chat_id)
            forward_chats.discard(chat_id)
            leave_msg = f"""
вЬЕ ** ЯбіЗ“УбіЫ біД ЬбіАбіЫ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОѓ **біД ЬбіАбіЫ:** `{chat_id}`
рЯУ§ ** АбіЗбіНбіА…™…і…™…і…Ґ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі біЕ…™sбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯУМ **біАбіЬбіЕ…™біП …ібіП біЬsбіЗ біЫбіП біЫ Ь…™s біД ЬбіАбіЫ!**
"""
            await status_msg.edit_text(leave_msg)
            logger.info(f" ЯбіЗ“УбіЫ біД ЬбіАбіЫ {chat_id}")
        except Exception as e:
            logger.error(f"біДбіНбіЕ_ ЯбіЗбіАбі†біЗ біЗ А АбіП А “УбіП А {chat_id}: {e}")
            await message.reply(f"вЭМ **біЗ А АбіП А  ЯбіЗбіАбі†…™…і…Ґ біД ЬбіАбіЫ!**\n\nвЪ†пЄП `{str(e)}`")
    else:
        if not forward_chats:
            await message.reply(
                "Please try again. **Please try again. Please try again.s Please try again. Please try again.!**\n\nPlease try again. Please try again.sPlease try again. `/Please try again.` Please try again. sPlease try again. Please try again."
            )
            return
        count = len(forward_chats)
        status_msg = await message.reply(f"рЯФД ** ЯбіЗбіАбі†…™…і…Ґ біА Я Я {count} біД ЬбіАбіЫs...**")
        left_count = 0
        for cid in list(forward_chats):
            try:
                await call_py.leave_call(cid)
                left_count += 1
            except Exception:
                pass
        forward_chats.clear()
        leave_msg = f"""
вЬЕ ** ЯбіЗ“УбіЫ біА Я Я біД ЬбіАбіЫs sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ§ **біЫбіПбіЫбіА Я  ЯбіЗ“УбіЫ:** {left_count}/{count} біД ЬбіАбіЫs
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі біА Я Я біЕ…™sбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ
рЯУ° **sбіПбіЬ АбіДбіЗ:** {'Please try again. Please try again.' if is_recording else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ **біА Я Я біАбіЬбіЕ…™біП “УбіП Абі°біА АбіЕ…™…і…Ґ  ЬбіАs sбіЫбіПбіШбіШбіЗбіЕ!**
"""
        await status_msg.edit_text(leave_msg)

@bot_app.on_message(pyro_filters.command("leaveall") & authorized_only())
async def cmd_leaveall(client, message):
    global is_recording
    total_forward = len(forward_chats)
    status_msg = await message.reply(
        "Please try again. **Please try again.sPlease try again. Please try again. Please try again.s...**\n\nPlease try again. Please try again. Please try again. Please try again. Please try again.s..."
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
вЬЕ **біА Я Я біД ЬбіАбіЫs біЕ…™sбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУ° **sбіПбіЬ АбіДбіЗ:** вЬЕ  ЯбіЗ“УбіЫ
рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {left_count}/{total_forward}  ЯбіЗ“УбіЫ
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі біА Я Я біЕ…™sбіДбіП…і…ібіЗбіДбіЫбіЗбіЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ **біЗбі†біЗ А ПбіЫ Ь…™…і…Ґ  ЬбіАs  ЩбіЗбіЗ…і біД ЯбіЗбіА…ібіЗбіЕ біЬбіШ!**
"""
    await status_msg.edit_text(leaveall_msg)
    logger.info("Please try again. Please try again. Please try again.s")

# English comment

@bot_app.on_message(pyro_filters.command("mute") & authorized_only())
async def cmd_mute(client, message):
    global is_muted
    if is_muted:
        await message.reply(
            "Please try again. **Please try again. Please try again.!**\n\n"
            f"рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}\n"
            "Please try again. Please try again.sPlease try again. `/Please try again.` Please try again. Please try again.sPlease try again."
        )
        return
    is_muted = True
    mute_msg = f"""
рЯФЗ **біАбіЬбіЕ…™біП біНбіЬбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **sбіЫбіАбіЫбіЬs:** рЯФЗ біНбіЬбіЫбіЗбіЕ
рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}
рЯУ° **sбіПбіЬ АбіДбіЗ:** {'Please try again. Please try again.' if is_recording else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯФК **…ібіП біАбіЬбіЕ…™біП …™s  ЩбіЗ…™…і…Ґ “УбіП Абі°біА АбіЕбіЗбіЕ  А…™…Ґ ЬбіЫ …ібіПбі°!**
"""
    await message.reply(mute_msg)
    logger.info("Please try again. Please try again.")

@bot_app.on_message(pyro_filters.command("unmute") & authorized_only())
async def cmd_unmute(client, message):
    global is_muted
    if not is_muted:
        await message.reply(
            "Please try again. **Please try again. Please try again.!**\n\n"
            f"рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}\n"
            "Please try again. Please try again. Please try again.s Please try again. Please try again."
        )
        return
    is_muted = False
    unmute_msg = f"""
рЯФК **біАбіЬбіЕ…™біП біЬ…ібіНбіЬбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ  Я…™бі†біЗ
рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:** {len(forward_chats)}
рЯУ° **sбіПбіЬ АбіДбіЗ:** {'Please try again. Please try again.' if is_recording else 'Please try again. Please try again.'}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯОµ **біАбіЬбіЕ…™біП …™s …ібіПбі° “У ЯбіПбі°…™…і…Ґ біЫбіП біА Я Я біД ЬбіАбіЫs!**
"""
    await message.reply(unmute_msg)
    logger.info("Please try again. Please try again.")

# English comment

@bot_app.on_message(pyro_filters.command("level") & authorized_only())
async def cmd_level_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['volume']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 200), 200)
        await message.reply(
            f"рЯФК **Volume Control**\n\n"
            f"рЯУК **Current:** `{current}%`\n"
            f"рЯУИ {bar} `{min(current, 200)}%`\n"
            f"рЯУМ **Status:** {get_effect_status(min(current, 200), 200)}\n\n"
            f"рЯТ° **Usage:** `/level <0-вИЮ>`\n"
            f"вЪ†пЄП **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT - but clamp for safety display
        audio_config['volume'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 200), 200)
        await message.reply(
            f"вЬЕ **Volume updated!**\n\n"
            f"рЯУК **New:** `{level}%`\n"
            f"рЯУИ {bar} `{min(abs(level), 200)}%`\n"
            f"рЯУМ **Status:** {'Please try again. EXTREME' if abs(level) > 200 else get_effect_status(abs(level), 200)}\n\n"
            f"вЪ†пЄП **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("bass") & authorized_only())
async def cmd_bass_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['bass']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"рЯОЄ **Bass Boost**\n\n"
            f"рЯУК **Current:** `{current}`\n"
            f"рЯУИ {bar} `{min(current, 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"рЯТ° **Usage:** `/bass <0-вИЮ>`\n"
            f"вЪ†пЄП **NO LIMIT!** Set any value!"
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
            f"вЬЕ **Bass updated!**\n\n"
            f"рЯУК **New:** `{level}`\n"
            f"рЯУИ {bar} `{min(abs(level), 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {'Please try again. EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"вЪ†пЄП **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("treble") & authorized_only())
async def cmd_treble_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['treble']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"рЯОµ **Treble Boost**\n\n"
            f"рЯУК **Current:** `{current}`\n"
            f"рЯУИ {bar} `{min(current, 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"рЯТ° **Usage:** `/treble <0-вИЮ>`\n"
            f"вЪ†пЄП **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT
        audio_config['treble'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 60), 60)
        await message.reply(
            f"вЬЕ **Treble updated!**\n\n"
            f"рЯУК **New:** `{level}`\n"
            f"рЯУИ {bar} `{min(abs(level), 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {'Please try again. EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"вЪ†пЄП **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[1]}`")

@bot_app.on_message(pyro_filters.command("gain") & authorized_only())
async def cmd_gain_unlimited(client, message):
    parts = message.text.split()
    current = audio_config['gain']
    if len(parts) < 2:
        bar = create_progress_bar(min(current, 60), 60)
        await message.reply(
            f"рЯУИ **Gain Control**\n\n"
            f"рЯУК **Current:** `{current}`\n"
            f"рЯУИ {bar} `{min(current, 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {get_effect_status(min(current, 60), 60)}\n\n"
            f"рЯТ° **Usage:** `/gain <0-вИЮ>`\n"
            f"вЪ†пЄП **NO LIMIT!** Set any value!"
        )
        return
    try:
        level = int(parts[1])
        # NO LIMIT
        audio_config['gain'] = max(0, level)
        save_state()
        bar = create_progress_bar(min(abs(level), 60), 60)
        await message.reply(
            f"вЬЕ **Gain updated!**\n\n"
            f"рЯУК **New:** `{level}`\n"
            f"рЯУИ {bar} `{min(abs(level), 60)}/вИЮ`\n"
            f"рЯУМ **Status:** {'Please try again. EXTREME' if abs(level) > 60 else get_effect_status(abs(level), 60)}\n\n"
            f"вЪ†пЄП **NO LIMIT!**"
        )
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[1]}`")

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
            f"рЯФ• **Overdrive/Distortion**\n\n"
            f"рЯУК **Current:** `{current}/100`\n"
            f"рЯУИ {bar} `{current}/100`\n"
            f"рЯУМ **Gain:** `{gain}x` | **Tone:** `{tone}`\n\n"
            f"рЯТ° **Usage:**\n"
            f"`/overdrive <0-100>` - Set drive level\n"
            f"`/overdrive gain <1.0-10.0>` - Set gain\n"
            f"`/overdrive tone <0.0-1.0>` - Set tone\n"
            f"`/overdrive off` - Disable\n\n"
            f"вЪ†пЄП **NO LIMIT!** Set any value!"
        )
        return
    
    action = parts[1].lower()
    
    if action == "off":
        audio_config['overdrive'] = 0
        save_state()
        await message.reply("Please try again. **Overdrive disabled!**")
        return
    
    if len(parts) < 3:
        await message.reply(f"вЭМ **Usage:** `/overdrive {action} <value>`")
        return
    
    try:
        value = float(parts[2])
        
        if action == "gain":
            audio_config['overdrive_gain'] = max(0.5, min(10.0, value))
            save_state()
            await message.reply(f"вЬЕ **Overdrive gain set to:** `{audio_config['overdrive_gain']}x`")
        elif action == "tone":
            audio_config['overdrive_tone'] = max(0.0, min(1.0, value))
            save_state()
            await message.reply(f"вЬЕ **Overdrive tone set to:** `{audio_config['overdrive_tone']}`")
        else:
            value = int(value)
            audio_config['overdrive'] = max(0, value)
            save_state()
            bar = create_progress_bar(min(value, 100), 100)
            await message.reply(
                f"вЬЕ **Overdrive updated!**\n\n"
                f"рЯУК **New:** `{value}/100`\n"
                f"рЯУИ {bar} `{value}/100`\n"
                f"рЯУМ **Status:** {'Please try again. EXTREME' if value > 80 else 'Please try again. sPlease try again.' if value > 50 else 'Please try again. Please try again.' if value > 20 else 'Please try again. Please try again.'}\n\n"
                f"вЪ†пЄП **NO LIMIT!**"
            )
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[2]}`")

# ===== ECHO COMMANDS (UNLIMITED) =====

@bot_app.on_message(pyro_filters.command("echo") & authorized_only())
async def cmd_echo(client, message):
    parts = message.text.split()
    current_delay = audio_config.get('echo_delay', 70)
    current_decay = audio_config.get('echo_decay', 0.32)
    
    if len(parts) < 2:
        await message.reply(
            f"рЯОµ **Echo Controls**\n\n"
            f"рЯУК **Current Settings:**\n"
            f"вАҐ **Delay:** `{current_delay}ms`\n"
            f"вАҐ **Decay:** `{current_decay}`\n\n"
            f"рЯТ° **Usage:**\n"
            f"`/echo delay <1-5000>` - Set delay in ms\n"
            f"`/echo decay <0.01-5.0>` - Set decay strength\n"
            f"`/echo off` - Disable echo completely\n\n"
            f"вЪ†пЄП **NO LIMITS!** You can set any value!"
        )
        return
    
    action = parts[1].lower()
    
    if action == "off":
        audio_config['echo_delay'] = 0
        audio_config['echo_decay'] = 0
        save_state()
        await message.reply("Please try again. **Echo disabled!**")
        return
    
    if len(parts) < 3:
        await message.reply(f"вЭМ **Usage:** `/echo {action} <value>`")
        return
    
    try:
        value = float(parts[2])
        
        if action == "delay":
            # NO LIMIT! But safe minimum to avoid crash
            value = max(1, value)
            audio_config['echo_delay'] = value
            await message.reply(f"вЬЕ **Echo delay set to:** `{value}ms`\n\nвЪ†пЄП NO LIMITS!")
            
        elif action == "decay":
            # NO LIMIT! But safe minimum to avoid zero
            value = max(0.01, value)
            audio_config['echo_decay'] = value
            await message.reply(f"вЬЕ **Echo decay set to:** `{value}`\n\nвЪ†пЄП NO LIMITS!")
            
        else:
            await message.reply(f"вЭМ **Unknown echo option:** `{action}`\n\nUse: `delay`, `decay`, or `off`")
            return
            
        save_state()
        
    except ValueError:
        await message.reply(f"вЭМ **Invalid value:** `{parts[2]}`")

@bot_app.on_message(pyro_filters.command("effects") & authorized_only())
async def cmd_effects(client, message):
    config = audio_config
    scipy_status = "Please try again. Please try again. Please try again." if SCIPY_AVAILABLE else "Please try again. Please try again.sPlease try again. Please try again."
    vol_bar = create_progress_bar(min(config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(config['gain'], 60), 60)
    od_bar = create_progress_bar(min(config.get('overdrive', 0), 100), 100)
    effects_msg = f"""
рЯОЫпЄП **біАбіЬбіЕ…™біП біЗ“У“УбіЗбіДбіЫs біЕбіАs Ь ЩбіПбіА АбіЕ**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯФК **бі†біП ЯбіЬбіНбіЗ:** `{config['volume']}%`
{vol_bar} `{config['volume']}%`

рЯОЄ ** ЩбіАss:** `{config['bass']}/вИЮ`
{bass_bar} `{config['bass']}/вИЮ`

рЯОµ **біЫ АбіЗ Щ ЯбіЗ:** `{config['treble']}/вИЮ`
{treble_bar} `{config['treble']}/вИЮ`

рЯУИ **…ҐбіА…™…і:** `{config['gain']}/вИЮ`
{gain_bar} `{config['gain']}/вИЮ`

рЯФ• **біЕ…™sбіЫбіП АбіЫ…™П…і:** `{config.get('overdrive', 0)}/100`
{od_bar} `{config.get('overdrive', 0)}/100`
вАҐ …ҐбіА…™…і: `{config.get('overdrive_gain', 1.0)}x` | біЫбіП…ібіЗ: `{config.get('overdrive_tone', 0.5)}`

рЯФД **біЗбіД ЬбіП:**
вАҐ біЕбіЗ ЯбіА П: `{config['echo_delay']}ms`
вАҐ біЕбіЗбіДбіА П: `{config['echo_decay']}`

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
вЪЩпЄП **“УбіЗбіАбіЫбіЬ АбіЗs**
вАҐ біДбіПбіНбіШ АбіЗssбіП А: {'Please try again. Please try again.' if config['compressor'] else 'Please try again. Please try again.sPlease try again.'}
вАҐ  Я…™біН…™біЫбіЗ А: {'Please try again. Please try again.' if config['limiter'] else 'Please try again. Please try again.sPlease try again.'}
вАҐ  Ь…™…Ґ ЬбіШбіАss: {'Please try again. Please try again.' if config['highpass'] else 'Please try again. Please try again.sPlease try again.'}
вАҐ  ЯбіПбі°біШбіАss: {'Please try again. Please try again.' if config['lowpass'] else 'Please try again. Please try again.sPlease try again.'}

рЯУ¶ **біЗ…і…Ґ…™…ібіЗ:** {scipy_status}
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
вЬЕ **біА Я Я біАбіЬбіЕ…™біП біЗ“У“УбіЗбіДбіЫs  АбіЗsбіЗбіЫ!**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯФК **бі†біП ЯбіЬбіНбіЗ:** `{old_config['volume']}%` вЖТ `{audio_config['volume']}%` вЬЕ
рЯОЄ ** ЩбіАss:** `{old_config['bass']}` вЖТ `{audio_config['bass']}` вЬЕ
рЯОµ **біЫ АбіЗ Щ ЯбіЗ:** `{old_config['treble']}` вЖТ `{audio_config['treble']}` вЬЕ
рЯУИ **…ҐбіА…™…і:** `{old_config['gain']}` вЖТ `{audio_config['gain']}` вЬЕ
рЯФ• **біЕ…™sбіЫбіП АбіЫ…™П…і:** `{old_config.get('overdrive', 0)}` вЖТ `{audio_config['overdrive']}` вЬЕ
рЯФД **біЗбіД ЬбіП:** `{old_config['echo_delay']}ms` вЖТ `{audio_config['echo_delay']}ms` вЬЕ
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ “УбіАбіДбіЫбіП А П  АбіЗsбіЫбіП АбіЗбіЕ
рЯОѓ **біЗ“У“УбіЗбіДбіЫs:** біА Я Я біД ЯбіЗбіА АбіЗбіЕ
"""
    await message.reply(reset_msg)
    logger.info("Please try again. Please try again.s Please try again.sPlease try again. Please try again. Please try again.")

# English comment

@bot_app.on_message(pyro_filters.command("status") & authorized_only())
async def cmd_status(client, message):
    recording_status = "Please try again. Please try again." if is_recording else "Please try again. Please try again."
    audio_status = "Please try again. Please try again." if is_muted else "Please try again. Please try again."
    forward_count = len(forward_chats)
    forward_list = ""
    if forward_chats:
        forward_list = "\n".join(f"вАҐ `{c}`" for c in list(forward_chats)[:10])
        if len(forward_chats) > 10:
            forward_list += f"\nвАҐ ... біА…ібіЕ {len(forward_chats)-10} біНбіП АбіЗ"
    else:
        forward_list = "Please try again. Please try again."
    status_msg = f"""
рЯУК ** ЩбіПбіЫ sбіЫбіАбіЫбіЬs біЕбіАs Ь ЩбіПбіА АбіЕ**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯФі ** АбіЗбіДбіП АбіЕ…™…і…Ґ:** {recording_status}
рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`
рЯФК **біАбіЬбіЕ…™біП:** {audio_status}
рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {forward_count} біД ЬбіАбіЫs
вП±пЄП **біЬбіШбіЫ…™біНбіЗ:** `{get_uptime()}`
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕ…™…і…Ґ:**
{forward_list}

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОЫпЄП **біАбіДбіЫ…™бі†біЗ біЗ“У“УбіЗбіДбіЫs:**
вАҐ бі†біП ЯбіЬбіНбіЗ: `{audio_config['volume']}%`
вАҐ  ЩбіАss: `{audio_config['bass']}`
вАҐ біЫ АбіЗ Щ ЯбіЗ: `{audio_config['treble']}`
вАҐ …ҐбіА…™…і: `{audio_config['gain']}`
вАҐ біЕ…™sбіЫбіП АбіЫ…™П…і: `{audio_config.get('overdrive', 0)}`
вАҐ біЗбіД ЬбіП: `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

рЯУК **s ПsбіЫбіЗбіН:** {'Please try again. sPlease try again.' if is_recording else 'Please try again. sPlease try again.'}
"""
    await message.reply(status_msg)

@bot_app.on_message(pyro_filters.command("list") & authorized_only())
async def cmd_list(client, message):
    if not forward_chats:
        await message.reply(
            "Please try again. **Please try again. Please try again. Please try again.**\n\n"
            "Please try again. Please try again.sPlease try again. `/Please try again. <Please try again._Please try again.>` Please try again. sPlease try again.\n"
            "Please try again. Please try again.xPlease try again.: `/Please try again. -1003929100976`"
        )
        return
    chat_list = []
    for idx, cid in enumerate(forward_chats, 1):
        chat_list.append(f"`{idx}.` `{cid}`")
    list_msg = f"""
рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ біД ЬбіАбіЫs  Я…™sбіЫ**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **біЫбіПбіЫбіА Я:** {len(forward_chats)} біД ЬбіАбіЫs
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА

{chr(10).join(chat_list)}

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯТ° **біЫ…™біШs:**
вАҐ біЬsбіЗ `/ ЯбіЗбіАбі†біЗ <…™біЕ>` біЫбіП  АбіЗбіНбіПбі†біЗ біА біД ЬбіАбіЫ
вАҐ біЬsбіЗ `/ ЯбіЗбіАбі†біЗбіА Я Я` біЫбіП  АбіЗбіНбіПбі†біЗ біА Я Я
"""
    await message.reply(list_msg)

# English comment

@bot_app.on_message(pyro_filters.command("panel") & authorized_only())
async def cmd_panel(client, message):
    recording_status = "Please try again. Please try again." if is_recording else "Please try again. Please try again."
    audio_status = "Please try again. Please try again." if is_muted else "Please try again. Please try again."
    forward_count = len(forward_chats)
    uptime = get_uptime()
    vol_bar = create_progress_bar(min(audio_config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(audio_config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(audio_config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(audio_config['gain'], 60), 60)
    od_bar = create_progress_bar(min(audio_config.get('overdrive', 0), 100), 100)
    panel_text = f"""
рЯОЫпЄП **біДбіП…ібіЫ АбіП Я біШбіА…ібіЗ Я**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **s ПsбіЫбіЗбіН sбіЫбіАбіЫбіЬs**
вАҐ ** АбіЗбіДбіП АбіЕ…™…і…Ґ:** {recording_status}
вАҐ **біАбіЬбіЕ…™біП:** {audio_status}
вАҐ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {forward_count} біД ЬбіАбіЫs
вАҐ **біЬбіШбіЫ…™біНбіЗ:** {uptime}
вАҐ **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОµ **біАбіЬбіЕ…™біП біЗ“У“УбіЗбіДбіЫs**
вАҐ **бі†біП ЯбіЬбіНбіЗ:** `{audio_config['volume']}%` {vol_bar}
вАҐ ** ЩбіАss:** `{audio_config['bass']}/вИЮ` {bass_bar}
вАҐ **біЫ АбіЗ Щ ЯбіЗ:** `{audio_config['treble']}/вИЮ` {treble_bar}
вАҐ **…ҐбіА…™…і:** `{audio_config['gain']}/вИЮ` {gain_bar}
вАҐ **біЕ…™sбіЫбіП АбіЫ…™П…і:** `{audio_config.get('overdrive', 0)}/100` {od_bar}
вАҐ **біЗбіД ЬбіП:** `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУМ **біЬsбіЗ  ЩбіЬбіЫбіЫбіП…іs  ЩбіЗ ЯбіПбі° біЫбіП біДбіП…ібіЫ АбіП Я**
"""
    keyboard = build_keyboard([
        ("Please try again. Please try again.", "panel_mute", ButtonStyle.DANGER),
        ("Please try again. Please try again.", "panel_unmute", ButtonStyle.SUCCESS),
        ("Please try again. Please try again. -", "panel_vol_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_vol_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.ss -", "panel_bass_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.ss +", "panel_bass_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. -", "panel_treble_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_treble_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. -", "panel_gain_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_gain_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again. -", "panel_od_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again. +", "panel_od_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again.", "panel_reset", ButtonStyle.DANGER),
        ("Please try again. Please try again.sPlease try again.", "panel_list", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again.", "panel_close", ButtonStyle.DANGER),
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
        await callback_query.answer("Please try again. Please try again.!", show_alert=True)
        return
    await callback_query.answer()
    if data == "panel_mute":
        if is_muted:
            await callback_query.answer("Please try again. Please try again. Please try again.!", show_alert=True)
            return
        is_muted = True
        await callback_query.answer("Please try again. Please try again. Please try again.!", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_unmute":
        if not is_muted:
            await callback_query.answer("Please try again. Please try again. Please try again.!", show_alert=True)
            return
        is_muted = False
        await callback_query.answer("Please try again. Please try again. Please try again.!", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_vol_up":
        audio_config['volume'] = 200
        save_state()
        await callback_query.answer("Please try again. Please try again.: Please try again.x (200%)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_vol_down":
        audio_config['volume'] = 100
        save_state()
        await callback_query.answer("Please try again. Please try again.: 100%", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_bass_up":
        audio_config['bass'] = 60
        audio_config['highpass'] = True
        save_state()
        await callback_query.answer("Please try again. Please try again.ss: Please try again.x (60/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_bass_down":
        audio_config['bass'] = 0
        audio_config['highpass'] = False
        save_state()
        await callback_query.answer("Please try again. Please try again.ss: Please try again. (0/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_treble_up":
        audio_config['treble'] = 60
        save_state()
        await callback_query.answer("Please try again. Please try again.: Please try again.x (60/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_treble_down":
        audio_config['treble'] = 0
        save_state()
        await callback_query.answer("Please try again. Please try again.: Please try again. (0/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_gain_up":
        audio_config['gain'] = 60
        save_state()
        await callback_query.answer("Please try again. Please try again.: Please try again.x (60/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_gain_down":
        audio_config['gain'] = 0
        save_state()
        await callback_query.answer("Please try again. Please try again.: Please try again. (0/Please try again.)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_od_up":
        audio_config['overdrive'] = 100
        save_state()
        await callback_query.answer("Please try again. Please try again.sPlease try again.: MAX (100)", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_od_down":
        audio_config['overdrive'] = 0
        save_state()
        await callback_query.answer("Please try again. Please try again.sPlease try again.: OFF (0)", show_alert=True)
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
        await callback_query.answer("Please try again. Please try again. Please try again.s Please try again.sPlease try again.!", show_alert=True)
        await refresh_panel(client, callback_query)
    elif data == "panel_list":
        if not forward_chats:
            list_text = "Please try again. **Please try again. Please try again. Please try again.**"
        else:
            chat_list = "\n".join(f"вАҐ `{c}`" for c in list(forward_chats)[:15])
            if len(forward_chats) > 15:
                chat_list += f"\nвАҐ ... біА…ібіЕ {len(forward_chats)-15} біНбіП АбіЗ"
            list_text = f"""
рЯУ§ **“УбіП Абі°біА АбіЕ…™…і…Ґ біД ЬбіАбіЫs**

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **біЫбіПбіЫбіА Я:** {len(forward_chats)}
вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
{chat_list}
"""
        keyboard = build_keyboard([
            ("Please try again. Please try again.", "panel_back", ButtonStyle.PRIMARY)
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
            await callback_query.answer("Please try again. Please try again. Please try again.sPlease try again.!", show_alert=True)
        except Exception:
            await callback_query.answer("Please try again. Please try again. Please try again. Please try again.sPlease try again.", show_alert=True)

# English comment

async def refresh_panel(client, callback_query: CallbackQuery):
    recording_status = "Please try again. Please try again." if is_recording else "Please try again. Please try again."
    audio_status = "Please try again. Please try again." if is_muted else "Please try again. Please try again."
    forward_count = len(forward_chats)
    uptime = get_uptime()
    vol_bar = create_progress_bar(min(audio_config['volume'], 200), 200)
    bass_bar = create_progress_bar(min(audio_config['bass'], 60), 60)
    treble_bar = create_progress_bar(min(audio_config['treble'], 60), 60)
    gain_bar = create_progress_bar(min(audio_config['gain'], 60), 60)
    od_bar = create_progress_bar(min(audio_config.get('overdrive', 0), 100), 100)
    panel_text = f"""
рЯОЫпЄП **біДбіП…ібіЫ АбіП Я біШбіА…ібіЗ Я** (рЯФД  АбіЗ“У АбіЗs ЬбіЗбіЕ)

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУК **s ПsбіЫбіЗбіН sбіЫбіАбіЫбіЬs**
вАҐ ** АбіЗбіДбіП АбіЕ…™…і…Ґ:** {recording_status}
вАҐ **біАбіЬбіЕ…™біП:** {audio_status}
вАҐ **“УбіП Абі°біА АбіЕ…™…і…Ґ:** {forward_count} біД ЬбіАбіЫs
вАҐ **біЬбіШбіЫ…™біНбіЗ:** {uptime}
вАҐ **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯОµ **біАбіЬбіЕ…™біП біЗ“У“УбіЗбіДбіЫs**
вАҐ **бі†біП ЯбіЬбіНбіЗ:** `{audio_config['volume']}%` {vol_bar}
вАҐ ** ЩбіАss:** `{audio_config['bass']}/вИЮ` {bass_bar}
вАҐ **біЫ АбіЗ Щ ЯбіЗ:** `{audio_config['treble']}/вИЮ` {treble_bar}
вАҐ **…ҐбіА…™…і:** `{audio_config['gain']}/вИЮ` {gain_bar}
вАҐ **біЕ…™sбіЫбіП АбіЫ…™П…і:** `{audio_config.get('overdrive', 0)}/100` {od_bar}
вАҐ **біЗбіД ЬбіП:** `{audio_config['echo_delay']}ms @ {audio_config['echo_decay']}`

вФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФАвФА
рЯУМ **біЬsбіЗ  ЩбіЬбіЫбіЫбіП…іs  ЩбіЗ ЯбіПбі° біЫбіП біДбіП…ібіЫ АбіП Я**
"""
    keyboard = build_keyboard([
        ("Please try again. Please try again.", "panel_mute", ButtonStyle.DANGER),
        ("Please try again. Please try again.", "panel_unmute", ButtonStyle.SUCCESS),
        ("Please try again. Please try again. -", "panel_vol_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_vol_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.ss -", "panel_bass_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.ss +", "panel_bass_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. -", "panel_treble_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_treble_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. -", "panel_gain_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again. +", "panel_gain_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again. -", "panel_od_down", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again. +", "panel_od_up", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again.", "panel_reset", ButtonStyle.DANGER),
        ("Please try again. Please try again.sPlease try again.", "panel_list", ButtonStyle.PRIMARY),
        ("Please try again. Please try again.sPlease try again.", "panel_close", ButtonStyle.DANGER),
    ], row_width=2)
    try:
        await callback_query.edit_message_text(
            panel_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.debug(f" АбіЗ“У АбіЗs Ь_біШбіА…ібіЗ Я біЗбіЕ…™біЫ “УбіА…™ ЯбіЗбіЕ,  АбіЗsбіЗ…ібіЕ…™…і…Ґ: {e}")
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
            f"вЬЕ **біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ sбіЫбіА АбіЫбіЗбіЕ “УбіП А  ПбіПбіЬ!**\n\n"
            f"рЯУ° ** АбіЗбіДбіП АбіЕ …Ґ АбіПбіЬбіШ:** `{record_groupid}`\n"
            f"рЯТ° біЬsбіЗ `/біЕбіКбіП…™…і <біЫбіА А…ҐбіЗбіЫ_…™біЕ>` біЫбіП “УбіП Абі°біА АбіЕ біАбіЬбіЕ…™біП біЫбіП біПбіЫ ЬбіЗ А біД ЬбіАбіЫs."
        )
    else:
        await message.reply(f"вЭМ **“УбіА…™ ЯбіЗбіЕ біЫбіП sбіЫбіА АбіЫ біЕ П…ібіАбіН…™біД біД Я…™біЗ…ібіЫ:** `{msg}`")

@bot_app.on_message(pyro_filters.command("djoin") & authorized_only())
async def cmd_djoin(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Please try again. **Please try again.sPlease try again.:** `/djoin <Please try again._Please try again._Please try again.>`")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.reply("Please try again. **Please try again. Please try again. Please try again..**")
        return
    user_id = message.from_user.id
    success, msg = await dynamic_join(user_id, target)
    if success:
        fwd_count = len(dynamic_clients.get(user_id, {}).get('forward_chats', set()))
        await message.reply(
            f"вЬЕ **біКбіП…™…ібіЗбіЕ біЫбіА А…ҐбіЗбіЫ біД ЬбіАбіЫ!**\n\n"
            f"рЯОѓ **біЫбіА А…ҐбіЗбіЫ:** `{target}`\n"
            f"рЯУ§ ** ПбіПбіЬ А біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕs:** {fwd_count}"
        )
    else:
        await message.reply(f"вЭМ **“УбіА…™ ЯбіЗбіЕ біЫбіП біКбіП…™…і:** `{msg}`")

@bot_app.on_message(pyro_filters.command("dstop") & authorized_only())
async def cmd_dstop(client, message):
    user_id = message.from_user.id
    success, msg = await stop_dynamic_client(user_id)
    if success:
        await message.reply("Please try again. **Please try again. Please try again. sPlease try again..**")
    else:
        await message.reply(f"вЭМ **“УбіА…™ ЯбіЗбіЕ:** `{msg}`")

# English comment

@bot_app.on_message(pyro_filters.command("setrecordgroup") & pyro_filters.user(OWNER_ID))
async def cmd_setrecordgroup(client, message):
    global RECORD_SOURCE, is_recording
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            f"вЭМ **біЬsбіА…ҐбіЗ:** `/setrecordgroup <біД ЬбіАбіЫ_…™біЕ>`\n\n"
            f"рЯУМ **біЗxбіАбіНбіШ ЯбіЗ:** `/setrecordgroup -1003970175858`\n\n"
            f"рЯУК **біДбіЬ А АбіЗ…ібіЫ sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`"
        )
        return
    chat_id_str = re.sub(r'[^\d-]', '', parts[1])
    try:
        new_source = int(chat_id_str)
        old_source = RECORD_SOURCE
        if new_source == old_source:
            await message.reply(f"вДєпЄП **біЫ Ь…™s …™s біА Я АбіЗбіАбіЕ П біЫ ЬбіЗ біДбіЬ А АбіЗ…ібіЫ sбіПбіЬ АбіДбіЗ біД ЬбіАбіЫ!**\n\nрЯУ° **біДбіЬ А АбіЗ…ібіЫ sбіПбіЬ АбіДбіЗ:** `{new_source}`")
            return
        status_msg = await message.reply(f"рЯФД **біД ЬбіА…і…Ґ…™…і…Ґ sбіПбіЬ АбіДбіЗ “У АбіПбіН `{old_source}` біЫбіП `{new_source}`...**")
        if is_recording:
            try:
                await call_py.leave_call(old_source)
                is_recording = False
                logger.info(f" ЯбіЗ“УбіЫ біП ЯбіЕ sбіПбіЬ АбіДбіЗ: {old_source}")
            except Exception as e:
                logger.warning(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ  ЯбіЗбіАбі†біЗ біП ЯбіЕ sбіПбіЬ АбіДбіЗ: {e}")
        RECORD_SOURCE = new_source
        save_state()
        if is_recording:
            success, error = await join_call_safe(new_source)
            if success:
                await call_py.record(new_source, RecordStream(True, AUDIO_PARAMETERS))
                is_recording = True
                await status_msg.edit_text(
                    f"вЬЕ **sбіПбіЬ АбіДбіЗ біД ЬбіАбіЫ біД ЬбіА…і…ҐбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**\n\n"
                    f"рЯУ° **біП ЯбіЕ:** `{old_source}`\n"
                    f"рЯОѓ **…ібіЗбі°:** `{new_source}`\n"
                    f"рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ  АбіЗбіДбіП АбіЕ…™…і…Ґ"
                )
            else:
                is_recording = False
                await status_msg.edit_text(
                    f"вЪ†пЄП **sбіПбіЬ АбіДбіЗ біД ЬбіА…і…ҐбіЗбіЕ  ЩбіЬбіЫ “УбіА…™ ЯбіЗбіЕ біЫбіП біКбіП…™…і!**\n\n"
                    f"рЯУ° **…ібіЗбі° sбіПбіЬ АбіДбіЗ:** `{new_source}`\n"
                    f"вЪ†пЄП **біЗ А АбіП А:** `{error}`\n"
                    f"рЯТ° біЬsбіЗ `/ АбіЗбіДбіП АбіЕ` біЫбіП біЫ А П біА…ҐбіА…™…і"
                )
        else:
            await status_msg.edit_text(
                f"вЬЕ **sбіПбіЬ АбіДбіЗ біД ЬбіАбіЫ біД ЬбіА…і…ҐбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**\n\n"
                f"рЯУ° **біП ЯбіЕ:** `{old_source}`\n"
                f"рЯОѓ **…ібіЗбі°:** `{new_source}`\n"
                f"рЯУК **sбіЫбіАбіЫбіЬs:** рЯФі sбіЫбіА…ібіЕ Щ П\n\n"
                f"рЯТ° біЬsбіЗ `/ АбіЗбіДбіП АбіЕ` біЫбіП sбіЫбіА АбіЫ"
            )
        logger.info(f"sбіПбіЬ АбіДбіЗ біД ЬбіА…і…ҐбіЗбіЕ “У АбіПбіН {old_source} біЫбіП {new_source}  Щ П біПбі°…ібіЗ А")
    except ValueError:
        await message.reply(f"вЭМ **…™…ібі†біА Я…™біЕ біД ЬбіАбіЫ …™біЕ!**\n\nрЯУМ ** ПбіПбіЬ біЗ…ібіЫбіЗ АбіЗбіЕ:** `{parts[1]}`")
    except Exception as e:
        await message.reply(f"вЭМ **біЗ А АбіП А:** `{str(e)}`")

# English comment

@bot_app.on_message(pyro_filters.command("joinlink") & authorized_only())
async def cmd_joinlink(client, message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Please try again. **Please try again.:** `/joinlink <Please try again.>`")
        return
    link = parts[1].strip()
    try:
        chat = await user_app.join_chat(link)
        await message.reply(f"–≤“£вА¶ **–±“Щ“†–±“Щ“Є–Щ”Ш–Щ“Щ–±“Щ“Ѓ–±“ЩвА¶!** –Щ”Ш–±“ЩвА¶: `{chat.id}`")
    except Exception as e:
        error_str = str(e)
        if "USER_ALREADY_PARTICIPANT" in error_str:
            await message.reply("Please try again. **Please try again. Please try again. Please try again.!**")
        elif "INVITE_REQUEST_SENT" in error_str:
            await message.reply("Please try again. **Please try again. Please try again.QPlease try again. Please try again. (Please try again.)!**")
        else:
            await message.reply(f"–≤“Ы“Ґ **–Ї“£¬∞–±“Щ“Ц–Щ”Ш–Ъ“є–±“Щ“Ѓ–±“ЩвА¶:** `{error_str}`")

@bot_app.on_message(pyro_filters.command("restart") & authorized_only())
async def cmd_restart(client, message):
    global is_recording, is_muted, call_py, forward_chats
    try:
        status_msg = await message.reply(
            "Please try again. **Please try again.sPlease try again. Please try again....**\n\n"
            "Please try again. Please try again. Please try again. Please try again. Please try again.s..."
        )
        save_state()
        logger.info("Please try again. sPlease try again. sPlease try again.")
        left_count = 0
        failed_count = 0
        try:
            await call_py.leave_call(RECORD_SOURCE)
            left_count += 1
            logger.info(f" ЯбіЗ“УбіЫ sбіПбіЬ АбіДбіЗ: {RECORD_SOURCE}")
        except Exception as e:
            failed_count += 1
            logger.debug(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ  ЯбіЗбіАбі†біЗ sбіПбіЬ АбіДбіЗ: {e}")
        for chat_id in list(forward_chats):
            try:
                await call_py.leave_call(chat_id)
                left_count += 1
                logger.info(f" ЯбіЗ“УбіЫ “УбіП Абі°біА АбіЕ біД ЬбіАбіЫ: {chat_id}")
            except Exception as e:
                failed_count += 1
                logger.debug(f"біДбіПбіЬ ЯбіЕ …ібіПбіЫ  ЯбіЗбіАбі†біЗ {chat_id}: {e}")
        forward_chats = set()
        is_recording = False
        is_muted = False
        logger.info("Please try again. Please try again. sPlease try again. Please try again.")
        stop_success = False
        try:
            await call_py.stop()
            stop_success = True
            logger.info("Please try again. Please try again.s sPlease try again.")
        except Exception as e:
            logger.debug(f"біШ ПбіЫ…ҐбіДбіА Я Яs sбіЫбіПбіШ біЗ А АбіП А: {e}")
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
                                logger.debug(f"sбіЗ…ібіЕ біЗ А АбіП А біЫбіП {chat_id}: {e}")
                                if "not found" in str(e).lower() or "invalid" in str(e).lower():
                                    forward_chats.discard(chat_id)
                                    logger.warning(f" АбіЗбіНбіПбі†біЗбіЕ {chat_id} “У АбіПбіН “УбіП Абі°біА АбіЕ…™…і…Ґ  Я…™sбіЫ")
                    except Exception as e:
                        logger.error(f"біАбіЬбіЕ…™біП  ЬбіА…ібіЕ ЯбіЗ А біЗ А АбіП А: {e}")
            await call_py.start()
            restart_success = True
            logger.info("Please try again. Please try again.s Please try again.sPlease try again.")
        except Exception as e:
            logger.error(f"біА“УбіЫбіЗ А  АбіЗsбіЫбіА АбіЫ біШ ПбіЫ…ҐбіДбіА Я Яs “УбіА…™ ЯбіЗбіЕ: {e}")
            restart_success = False
        if restart_success:
            await status_msg.edit_text(
                f"вЬЕ ** ЩбіПбіЫ  АбіЗsбіЫбіА АбіЫбіЗбіЕ sбіЬбіДбіДбіЗss“УбіЬ Я Я П!**\n\n"
                f"рЯУК **біД ЯбіЗбіА…ібіЗбіЕ:** {left_count} біД ЬбіАбіЫs\n"
                f"вЪ†пЄП **“УбіА…™ ЯбіЗбіЕ:** {failed_count} біД ЬбіАбіЫs\n"
                f"рЯУ° **sбіПбіЬ АбіДбіЗ:** `{RECORD_SOURCE}`\n"
                f"рЯУ§ **біАбіДбіЫ…™бі†біЗ “УбіП Абі°біА АбіЕs:** {len(forward_chats)}\n"
                f"рЯФК **біАбіЬбіЕ…™біП:** {'Please try again. Please try again.' if is_muted else 'Please try again. Please try again.'}\n"
                f"рЯУК **sбіЫбіАбіЫбіЬs:** рЯЯҐ  АбіЗбіАбіЕ П\n\n"
                f"рЯТ° **біЬsбіЗ `/ АбіЗбіДбіП АбіЕ` біЫбіП sбіЫбіА АбіЫ біА…ҐбіА…™…і**"
            )
        else:
            await status_msg.edit_text(
                f"вЪ†пЄП **біШбіА АбіЫ…™біА Я  АбіЗsбіЫбіА АбіЫ - біД ЬбіЗбіДбіЛ  ЯбіП…Ґs!**\n\n"
                f"рЯУК **біД ЯбіЗбіА…ібіЗбіЕ:** {left_count} біД ЬбіАбіЫs\n"
                f"вЪ†пЄП **“УбіА…™ ЯбіЗбіЕ:** {failed_count} біД ЬбіАбіЫs\n"
                f"рЯЫС **біШ ПбіЫ…ҐбіДбіА Я Яs:** {'Please try again. sPlease try again.' if stop_success else 'Please try again. Please try again.'}\n"
                f"рЯФД ** АбіЗsбіЫбіА АбіЫ:** {'Please try again. sPlease try again.ss' if restart_success else 'Please try again. Please try again.'}\n\n"
                f"рЯТ° біНбіА…ібіЬбіА Я Я П біД ЬбіЗбіДбіЛ біЫ ЬбіЗ  ЩбіПбіЫ sбіЫбіАбіЫбіЬs"
            )
        logger.info("Please try again. Please try again.sPlease try again. Please try again.")
    except Exception as e:
        logger.error(f" АбіЗsбіЫбіА АбіЫ біЗ А АбіП А: {e}")
        try:
            await message.reply(
                f"вЭМ ** АбіЗsбіЫбіА АбіЫ “УбіА…™ ЯбіЗбіЕ!**\n\n"
                f"вЪ†пЄП **біЗ А АбіП А:** `{str(e)}`\n\n"
                f"рЯТ° біНбіА…ібіЬбіА Я Я П  АбіЗsбіЫбіА АбіЫ біЫ ЬбіЗ  ЩбіПбіЫ"
            )
        except Exception:
            logger.error("Please try again. Please try again. sPlease try again. Please try again. Please try again.ssPlease try again.")

# English comment

if __name__ == "__main__":
    load_state()
    print("Please try again. Please try again. Please try again. Please try again.7 - Please try again. Please try again.")
    print("Please try again. Please try again. Please try again. Please try again.ssPlease try again. Please try again. ZERO-LATENCY")
    print("Please try again. Please try again. Please try again.sPlease try again. Please try again.")
    print("Please try again. Please try again.xPlease try again.sPlease try again. Please try again. Please try again.s Please try again.sPlease try again.")
    print("Please try again. NEW: Overdrive/Distortion, Reverb, Stereo Width")
    print("Please try again. Please try again. Please try again. Please try again. Please try again.ssPlease try again. Please try again. <2.5ms Please try again.\n")
    if SCIPY_AVAILABLE:
        print("Please try again. sPlease try again. Please try again. - Please try again. Please try again. Please try again.ssPlease try again.")
    else:
        print("Please try again. sPlease try again. Please try again. Please try again. - Please try again.sPlease try again. Please try again.ssPlease try again. Please try again.")
        print("   Please try again.sPlease try again. Please try again.: Please try again. Please try again.sPlease try again. sPlease try again.\n")
    try:
        if not os.path.isfile(MAIN_SESSION_FILE) or os.path.getsize(MAIN_SESSION_FILE) == 0:
            raise FileNotFoundError(
                f"Main Pyrogram session file is missing or empty: {MAIN_SESSION_FILE}"
            )
        bot_app.start()
        call_py.start()
        print("Please try again. Please try again.! Please try again.sPlease try again. /Please try again. Please try again. /Please try again.")
        print("Please try again. Please try again. Please try again.s: /echo delay <ms>, /echo decay <value>")
        print("Please try again. Please try again.: /level, /bass, /treble, /gain, /overdrive - NO LIMITS!")
        idle()
    except KeyboardInterrupt:
        print("\nPlease try again. sPlease try again. Please try again....")
    except Exception as e:
        print(f"вЭМ “УбіАбіЫбіА Я біЗ А АбіП А: {e}")
    finally:
        # Cleanup main
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
                bot_app.stop()
            except Exception:
                pass
        except Exception:
            pass
        # Cleanup dynamic clients
        for uid in list(dynamic_clients.keys()):
            asyncio.run(stop_dynamic_client(uid))
        print("Please try again. Please try again. Please try again.")