import random
import sys
import threading
import platform
import subprocess
import asyncio
import os
import time
import tempfile
import numpy as np
import pygame
import pygame_menu
import soundcard as sc
from pygame_menu import themes

# Conditional imports for macOS artwork and media center
if platform.system() == "Darwin":
    from MediaPlayer import MPNowPlayingInfoCenter, MPMediaItemPropertyArtwork
    from AppKit import NSImage, NSBitmapImageRep, NSPNGFileType

# SETTINGS
CHUNK = 2046
N_BARS = 13
SAMPLE_RATE = 48000

# WINDOW
SCREEN_W = 700
SCREEN_H = 850
BAR_GAP = 18

# AUDIO RESPONSE
AUDIO_GAIN = 1
SMOOTHING = 0.13
MIN_SCALE = 300

# VISUAL EFFECTS
TRAIL_ALPHA = 50
BASS_THRESHOLD = 120
FPS = 60

# FREQUENCY VISUAL BOOST
TREBLE_BOOST = 2
TREBLE_START = 2500
TREBLE_FULL = 12500

# AUDIO VARIABLES
audio = np.zeros(CHUNK, dtype=np.float32)
audio_lock = threading.Lock()
audio_running = True

ARTWORK_DIR = tempfile.gettempdir()
ARTWORK_PNG = os.path.join(ARTWORK_DIR, "now_playing_art.png")

now_playing_text = "No track"
artwork_path = None


# FIND AUDIO DEVICE
def get_audio_device():
    system = platform.system()
    if system == "Windows":
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.id), include_loopback=True)
    elif system == "Darwin":
        microphones = sc.all_microphones(include_loopback=True)
        for mic in microphones:
            if "blackhole" in mic.name.lower():
                return mic
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.id), include_loopback=True)
    else:
        raise RuntimeError("This program supports Windows and macOS only.")


def get_mac_now_playing():
    script = '''
    tell application "Music"
        if player state is playing then
            set track_name to name of current track
            set artist_name to artist of current track
            return artist_name & " - " & track_name
        end if
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip() or None


def get_mac_artwork():
    if platform.system() != "Darwin":
        return None
    script = '''
    tell application "Music"
        if player state is playing then
            try
                if (count of artworks of current track) > 0 then
                    set rawData to raw data of artwork 1 of current track
                    return rawData
                end if
            end try
        end if
        return ""
    end tell
    '''
    # Use AppleScript to output binary data via base64 to avoid file lock issues in PyCharm
    b64_script = 'osascript -e \'tell application "Music" to set d to raw data of artwork 1 of current track\' -e \'do shell script "echo " & quoted form of (d as text) ...'''

    # Simpler, robust implementation using standard temporary file writing via Foundation/NSData
    applescript_code = '''
    on run
        tell application "Music"
            if player state is playing then
                try
                    if (count of artworks of current track) > 0 then
                        set imageData to raw data of artwork 1 of current track
                        set targetPath to "%s"
                        set fileRef to open for access POSIX file targetPath with write permission
                        set eof fileRef to 0
                        write imageData to fileRef
                        close access fileRef
                        return "SUCCESS"
                    end try
                end try
            end if
            return "NO_ART"
        end tell
    end run
    ''' % ARTWORK_PNG

    try:
        result = subprocess.run(["osascript", "-e", applescript_code], capture_output=True, text=True)
        if "SUCCESS" in result.stdout and os.path.exists(ARTWORK_PNG):
            return ARTWORK_PNG
    except Exception as e:
        print(f"Artwork error: {e}")

    return None



def get_win_now_playing():
    """Uses SMTC — works with Spotify, Apple Music, VLC, etc."""
    try:
        import winsdk.windows.media.control as mct
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        manager = loop.run_until_complete(
            mct.GlobalSystemMediaTransportControlsSessionManager.request_async()
        )
        session = manager.get_current_session()
        if session:
            props = loop.run_until_complete(session.try_get_media_properties_async())
            loop.close()
            if props.title:
                artist = props.artist or ""
                title = props.title
                return f"{artist} - {title}".strip(' -')
        loop.close()
    except Exception:
        pass
    return None


def get_now_playing():
    if sys.platform == "darwin":
        return get_mac_now_playing()
    elif sys.platform == "win32":
        return get_win_now_playing()
    return None


def now_playing_thread():
    global now_playing_text, artwork_path
    while audio_running:
        result = get_now_playing()
        if result:
            now_playing_text = result
            if sys.platform == "darwin":
                art = get_mac_artwork()
                if art:
                    artwork_path = art
        else:
            now_playing_text = "No track"
            artwork_path = None
        time.sleep(2)


np_thread = threading.Thread(target=now_playing_thread, daemon=True)
np_thread.start()


# AUDIO CAPTURE
def capture_audio():
    global audio
    device = get_audio_device()
    with device.recorder(samplerate=SAMPLE_RATE, channels=2) as recorder:
        while audio_running:
            data = recorder.record(numframes=CHUNK)
            if data.ndim > 1:
                data = data.mean(axis=1)
            if len(data) < CHUNK:
                data = np.pad(data, (0, CHUNK - len(data)))
            else:
                data = data[:CHUNK]
            data = data * AUDIO_GAIN
            data = np.clip(data, -1.0, 1.0)
            with audio_lock:
                audio[:] = data


audio_thread = threading.Thread(target=capture_audio, daemon=True)
audio_thread.start()

# PYGAME SETUP
pygame.init()
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
pygame.display.set_caption("Audio Visualizer")
clock = pygame.time.Clock()
canvas = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
fullscreen = False


# FFT SETUP
frequencies = np.array([], dtype=float)
bins = np.array([], dtype=int)
bars = np.array([], dtype=float)


def update_fft_bins():
    global frequencies, bins, bars
    frequencies = np.geomspace(50, 12500, N_BARS + 1)
    bins = (frequencies * CHUNK / SAMPLE_RATE).astype(int)
    bins = np.clip(bins, 0, CHUNK // 2)
    bars = np.zeros(N_BARS, dtype=float)


update_fft_bins()
window = np.hanning(CHUNK)
max_scale = MIN_SCALE


def get_frequency_color(freq_val):
    if freq_val <= 250:
        return (0, 80, 255)
    elif freq_val <= 700:
        amt = (freq_val - 250) / (700 - 250)
        red = int(180 * amt)
        green = int(80 * (1 - amt))
        blue = 255
        return (red, green, blue)
    elif freq_val <= 3000:
        return (180, 0, 255)
    elif freq_val <= 5000:
        amt = (freq_val - 3000) / (5000 - 3000)
        red = int(180 + (255 - 180) * amt)
        green = 0
        blue = int(255 - (255 - 180) * amt)
        return (red, green, blue)
    elif freq_val <= 10000:
        amt = (freq_val - 5000) / (10000 - 5000)
        red = 255
        green = 0
        blue = int(180 * (1 - amt))
        return (red, green, blue)
    else:
        return (255, 0, 0)


def draw_bar(surface, rect_obj, bar_color):
    glow1 = rect_obj.inflate(16, 16)
    glow2 = rect_obj.inflate(12, 12)
    glow3 = rect_obj.inflate(8, 8)

    for glow_rect, alpha in [(glow1, 60), (glow2, 80), (glow3, 100)]:
        glow_surface = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(glow_surface, (*bar_color, alpha), glow_surface.get_rect())
        surface.blit(glow_surface, glow_rect.topleft)

    pygame.draw.rect(surface, bar_color, rect_obj)


# MENU CONFIGURATION
def set_n_bars(val):
    global N_BARS
    N_BARS = int(val)
    update_fft_bins()


def set_audio_gain(val):
    global AUDIO_GAIN
    AUDIO_GAIN = float(val)


def set_smoothing(val):
    global SMOOTHING
    SMOOTHING = float(val)


def set_bar_gap(val):
    global BAR_GAP
    BAR_GAP = int(val)


def set_trail_alpha(val):
    global TRAIL_ALPHA
    TRAIL_ALPHA = int(val)


def set_bass_threshold(val):
    global BASS_THRESHOLD
    BASS_THRESHOLD = int(val)


def set_treble_boost(val):
    global TREBLE_BOOST
    TREBLE_BOOST = float(val)


def set_fps(val):
    global FPS
    FPS = float(val)


font = pygame_menu.font.FONT_8BIT
mytheme = themes.Theme(
    background_color=(0, 0, 0, 255),
    title_background_color=(255, 255, 255),
    title_font_shadow=True,
    widget_padding=25,
    widget_font=font,
    title_bar_style=pygame_menu.widgets.MENUBAR_STYLE_NONE,
    widget_alignment=pygame_menu.locals.ALIGN_LEFT
)
mytheme.title_font_size = 24
mytheme.widget_font_size = 18

settings_menu = pygame_menu.Menu('Visualizer Settings', SCREEN_W, SCREEN_H, theme=mytheme)
settings_menu.add.range_slider('Number of Bars', default=N_BARS, range_values=(8, 128), increment=1,
                               onchange=set_n_bars)
settings_menu.add.range_slider('Audio Gain', default=AUDIO_GAIN, range_values=(1, 10.0), increment=1,
                               onchange=set_audio_gain)
settings_menu.add.range_slider('Smoothing', default=SMOOTHING, range_values=(0.01, 1.0), increment=0.01,
                               onchange=set_smoothing)
settings_menu.add.range_slider('Bar Gap', default=BAR_GAP, range_values=(0, 50), increment=1, onchange=set_bar_gap)
settings_menu.add.range_slider('Trail Alpha', default=TRAIL_ALPHA, range_values=(10, 255), increment=1,
                               onchange=set_trail_alpha)
settings_menu.add.range_slider('Bass Shake Threshold', default=BASS_THRESHOLD, range_values=(10, 500), increment=10,
                               onchange=set_bass_threshold)
settings_menu.add.range_slider('Treble Boost', default=TREBLE_BOOST, range_values=(1.0, 10.0), increment=1,
                               onchange=set_treble_boost)
settings_menu.add.range_slider('FPS', default=FPS, range_values=(1.0, 360.0), increment=1, onchange=set_fps)

settings_menu.disable()

# --- NOW PLAYING RENDER (cached with gradient) ---
np_font = pygame.font.SysFont("Arial", 22, bold=True)
np_surface = None
np_last_text = None


def render_now_playing(text):
    global np_surface, np_last_text
    if text == np_last_text and np_surface is not None:
        return np_surface

    base_surface = np_font.render(f"♪ {text}", True, (255, 255, 255))
    w, h = base_surface.get_size()
    np_surface = pygame.Surface((w, h), pygame.SRCALPHA)
    np_surface.blit(base_surface, (0, 0))

    array = pygame.surfarray.pixels3d(np_surface)
    alpha = pygame.surfarray.pixels_alpha(np_surface)

    if w > 0:
        m = np.clip(np.arange(w) / w, 0, 1)[:, np.newaxis]
        for j in range(3):
            if j == 0:
                c = 0 * (1 - m) + 255 * m
            elif j == 1:
                c = 80 * (1 - m) + 20 * m
            else:
                c = 255 * (1 - m) + 0 * m
            array[:, :, j] = np.where(alpha > 0, c, 0).astype(np.uint8)

    del array
    del alpha
    np_last_text = text
    return np_surface


cached_artwork_surface = None
last_artwork_path = None

running = True
while running:
    events = pygame.event.get()

    if settings_menu.is_enabled():
        settings_menu.update(events)

    for event in events:
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F11:
                fullscreen = not fullscreen
                if fullscreen:
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                else:
                    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
                screen_width, screen_height = screen.get_size()
                canvas = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
                settings_menu.resize(screen_width, screen_height)
            elif event.key == pygame.K_ESCAPE:
                if settings_menu.is_enabled():
                    settings_menu.disable()
                else:
                    settings_menu.enable()
        elif event.type == pygame.VIDEORESIZE:
            if not fullscreen:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                canvas = pygame.Surface((event.w, event.h), pygame.SRCALPHA)
                settings_menu.resize(event.w, event.h)

    screen_width, screen_height = screen.get_size()

    with audio_lock:
        samples = audio.copy()

    samples *= window
    spectrum = np.abs(np.fft.rfft(samples))

    target_bars = np.zeros(N_BARS, dtype=float)
    for i in range(N_BARS):
        start = bins[i]
        end = max(start + 1, min(bins[i + 1], len(spectrum)))
        target_bars[i] = np.max(spectrum[start:end])

        frequency = (frequencies[i] + frequencies[i + 1]) / 2
        if frequency > TREBLE_START:
            amount = min(1.0, (frequency - TREBLE_START) / (TREBLE_FULL - TREBLE_START))
            boost = 1.0 + (TREBLE_BOOST - 1.0) * amount
            target_bars[i] *= boost

    current_max = np.max(target_bars)
    max_scale = max(MIN_SCALE, max_scale * 0.95, current_max)

    for i in range(N_BARS):
        target_height = (target_bars[i] / max_scale) * (screen_height - 40)
        bars[i] += (target_height - bars[i]) * SMOOTHING
        bars[i] = max(0, bars[i])

    fade = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
    fade.fill((0, 0, 0, TRAIL_ALPHA))
    canvas.blit(fade, (0, 0))

    bar_width = (screen_width - (N_BARS - 1) * BAR_GAP) / N_BARS
    for i in range(N_BARS):
        x = i * (bar_width + BAR_GAP)
        bar_height = bars[i]
        y = screen_height - bar_height
        rectangle = pygame.Rect(int(x), int(y), int(bar_width), int(bar_height))
        frequency = (frequencies[i] + frequencies[i + 1]) / 2
        color = get_frequency_color(frequency)
        draw_bar(canvas, rectangle, color)

    bass_range = min(6, N_BARS)
    bass = bars[:bass_range].mean() if bass_range > 0 else 0
    shake_x = random.randint(-4, 4) if bass > BASS_THRESHOLD else 0
    shake_y = random.randint(-4, 4) if bass > BASS_THRESHOLD else 0

    screen.fill((0, 0, 0))
    screen.blit(canvas, (shake_x, shake_y))

    if settings_menu.is_enabled():
        settings_menu.draw(screen)
    else:
        if now_playing_text and now_playing_text != "No track":
            np_surface = render_now_playing(now_playing_text)
            if np_surface:
                np_rect = np_surface.get_rect(midright=(screen_width - 15, 30))

                if artwork_path and os.path.exists(artwork_path):
                    if artwork_path != last_artwork_path:
                        try:
                            cached_artwork_surface = pygame.image.load(artwork_path).convert()
                            cached_artwork_surface = pygame.transform.smoothscale(cached_artwork_surface, (30, 30))
                            last_artwork_path = artwork_path
                        except Exception:
                            cached_artwork_surface = None

                    if cached_artwork_surface:
                        art_rect = cached_artwork_surface.get_rect(midright=(np_rect.left - 10, np_rect.centery))
                        screen.blit(cached_artwork_surface, art_rect)

                screen.blit(np_surface, np_rect)

    pygame.display.flip()
    clock.tick(FPS)

audio_running = False
audio_thread.join(timeout=1)
pygame.quit()
sys.exit()