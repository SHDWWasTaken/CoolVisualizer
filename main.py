import random
import sys
import threading
import platform
import subprocess
import asyncio
import hashlib
import urllib.request
import os
import tempfile
import time
import numpy as np
import pygame
import pygame_menu
import soundcard as sc
from pygame_menu import themes

system = platform.system()

# SETTINGS


# AUDIO ANALYSIS


# CHUNK is the number of audio samples analyzed at once.

# Smaller CHUNK:
#   - less frequency detail
#   - faster response

# Larger CHUNK:
#   - more frequency detail
#   - slightly slower response

CHUNK = 2046


# Number of vertical bars.

# More bars = more frequency detail.
# Fewer bars = larger, simpler bars.


N_BARS = 13


# Audio sample rate.

# Used by the FFT to figure out what frequencies
# the audio samples represent.
SAMPLE_RATE = 48000



# WINDOW




# normal window size.
# Fullscreen uses your monitor's resolution.

SCREEN_W = 700
SCREEN_H = 850


# Amount of space between bars.

# Smaller = bars closer together.
# Larger = more space between bars.

BAR_GAP = 18



# AUDIO RESPONSE


# Multiplies the captured audio before visualization.

# Higher = bars react more strongly.
# Lower = bars react less strongly.

AUDIO_GAIN = 1


# Controls how smoothly the bars move.

# 0.05 = very smooth and slow
# 0.10 = smooth
# 0.20 = more responsive
# 1.00 = immediate movement
SMOOTHING = 0.13


# Prevents the automatic scaling from becoming too small.

# Higher = quieter/smaller bars.
# Lower = more sensitive visualization.
MIN_SCALE = 300


# ------------------------------------------------------------
# VISUAL EFFECTS
# ------------------------------------------------------------

# Controls how quickly the trail fades.
# Higher = shorter trail.
# Lower = longer trail.
TRAIL_ALPHA = 50


# Controls when the bass screen shake starts.
# Lower = easier to trigger bass shake.
# Higher = harder to trigger bass shake.
BASS_THRESHOLD = 120


# Frames Per Second Number
FPS = 60



# FREQUENCY VISUAL BOOST

TREBLE_BOOST = 10


# Frequency where the treble boost starts.
TREBLE_START = 2500


# Frequency where the full treble boost is reached.
TREBLE_FULL = 12500



# AUDIO VARIABLES

# Array stores the most recent chunk of audio.
# It starts filled with zeroes because there is no audio
# before the recording thread gives some.
audio = np.zeros(
    CHUNK,
    dtype=np.float32
)


# The audio is being updated by one thread while the main
# program is reading it.

# A lock prevents both from accessing it at exactly the
# same time.
audio_lock = threading.Lock()


# This tells the audio thread whether it should continue.
audio_running = True



# FIND AUDIO DEVICE



def get_audio_device():


    # platform.system() shows what operating system
    # the program is running on.

    # Windows → "Windows"
    # macOS   → "Darwin"
    system = platform.system()



    # WINDOWS

    if system == "Windows":

        # Find the computer's default speaker.
        speaker = sc.default_speaker()


        # Use the speaker as a loopback recording device.

        # Loopback means we're capturing what the computer
        # itself is playing rather than using the microphone.
        return sc.get_microphone(
            id=str(speaker.id),
            include_loopback=True
        )



    # MACOS


    elif system == "Darwin":

        # Get all available microphones and loopback devices.
        microphones = sc.all_microphones(
            include_loopback=True
        )


        # Search for BlackHole.

        # BlackHole is used on macOS to route system
        # audio into an application.
        for mic in microphones:

            if "blackhole" in mic.name.lower():

                return mic


        # macOS does not expose a normal system-audio loopback device here.
        # Use BlackHole (or another virtual input) and route system output to it.
        raise RuntimeError(
            "System-audio capture on macOS needs BlackHole. Install BlackHole, "
            "route your Mac's audio output to it (or a Multi-Output Device), "
            "then restart this visualizer."
        )


    else:

        raise RuntimeError(
            "This program supports Windows and macOS only."
        )


def _save_artwork_bytes(data):
    """Save image bytes under a content-hashed name and return the file path."""
    if not data:
        return None

    data = bytes(data)
    digest = hashlib.sha256(data).hexdigest()[:20]
    suffix = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
    path = os.path.join(tempfile.gettempdir(), f"pygame_visualizer_art_{digest}{suffix}")

    # Reuse files for unchanged album art so we don't rewrite the same cover every poll.
    if not os.path.exists(path):
        try:
            with open(path, "wb") as file:
                file.write(data)
        except OSError as exc:
            print(f"Could not save album artwork: {exc}")
            return None
    return path


def _run_applescript(script):
    """Run AppleScript safely; this function is only used on macOS."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def get_mac_media_info():
    """Return (artist/title text, album-art path) for Music or Spotify on macOS."""
    # Apple Music embeds the cover artwork. Save it temporarily through AppleScript,
    # then hash it in Python so Pygame notices when the cover changes.
    music_script = r"""
    tell application "Music"
        if it is running then
            if player state is playing then
                set currentTrack to current track
                set trackText to (artist of currentTrack) & " - " & (name of currentTrack)
                try
                    set artObject to artwork 1 of currentTrack
                    set artBytes to raw data of artObject
                    set ext to ".jpg"
                    if format of artObject is «class PNG » then set ext to ".png"
                    set outputPath to "/tmp/pygame_visualizer_album_art" & ext
                    do shell script "touch " & quoted form of outputPath
                    set outputFile to open for access (POSIX file outputPath) with write permission
                    set eof outputFile to 0
                    write artBytes to outputFile
                    close access outputFile
                    return trackText & linefeed & outputPath
                on error
                    return trackText & linefeed
                end try
            end if
        end if
    end tell
    return ""
    """

    music_result = _run_applescript(music_script)
    if music_result:
        pieces = music_result.splitlines()
        track_text = pieces[0].strip() if pieces else ""
        if track_text:
            art_path = None
            if len(pieces) > 1 and pieces[1].strip() and os.path.isfile(pieces[1].strip()):
                try:
                    with open(pieces[1].strip(), "rb") as artwork_file:
                        art_path = _save_artwork_bytes(artwork_file.read())
                except OSError:
                    art_path = None
            return track_text, art_path

    # Spotify exposes its album cover as a URL through AppleScript.
    spotify_script = r"""
    tell application "Spotify"
        if it is running then
            if player state is playing then
                set currentTrack to current track
                set trackText to (artist of currentTrack) & " - " & (name of currentTrack)
                set artURL to artwork url of currentTrack
                return trackText & linefeed & artURL
            end if
        end if
    end tell
    return ""
    """
    spotify_result = _run_applescript(spotify_script)
    if not spotify_result:
        return None, None

    pieces = spotify_result.splitlines()
    track_text = pieces[0].strip() if pieces else ""
    artwork_url = pieces[1].strip() if len(pieces) > 1 else ""
    art_path = None
    if track_text and artwork_url.startswith(("https://", "http://")):
        try:
            request = urllib.request.Request(
                artwork_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                art_path = _save_artwork_bytes(response.read())
        except Exception:
            art_path = None
    return (track_text or None), art_path


async def _get_win_media_info_async():
    """Read current Windows media-session metadata and its album-art thumbnail."""
    try:
        import winsdk.windows.media.control as media_control
        from winsdk.windows.storage.streams import DataReader
    except ImportError:
        # Supports the newer split PyWinRT package naming as well.
        import winrt.windows.media.control as media_control
        from winrt.windows.storage.streams import DataReader

    manager = await media_control.GlobalSystemMediaTransportControlsSessionManager.request_async()
    session = manager.get_current_session()
    if session is None:
        return None, None

    props = await session.try_get_media_properties_async()
    title = (getattr(props, "title", None) or "").strip()
    artist = (getattr(props, "artist", None) or "").strip()
    track_text = f"{artist} - {title}".strip(" -")
    if not track_text:
        return None, None

    art_path = None
    thumbnail = getattr(props, "thumbnail", None)
    if thumbnail is not None:
        stream = None
        reader = None
        try:
            stream = await thumbnail.open_read_async()
            size = int(stream.size)
            if size > 0:
                reader = DataReader(stream)
                await reader.load_async(size)
                buffer = bytearray(size)
                reader.read_bytes(buffer)
                art_path = _save_artwork_bytes(buffer)
        except Exception as exc:
            print(f"Windows album-art retrieval failed: {exc}")
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    return track_text, art_path


def get_win_media_info():
    """Synchronous wrapper used by the background metadata thread."""
    try:
        return asyncio.run(_get_win_media_info_async())
    except Exception as exc:
        # Usually means the optional Windows media-session package is not installed.
        global media_error_reported
        if not media_error_reported:
            print(
                "Could not read Windows media information. Install the 'winsdk' "
                f"package to enable track names and album covers. Details: {exc}"
            )
            media_error_reported = True
        return None, None


now_playing_text = "No track"
artwork_path = None
media_error_reported = False


def get_media_info():
    """Choose the media metadata implementation for the current operating system."""
    if sys.platform == "darwin":
        return get_mac_media_info()
    if sys.platform == "win32":
        return get_win_media_info()
    return None, None


def now_playing_thread():
    global now_playing_text, artwork_path
    while audio_running:
        try:
            result, art = get_media_info()
            now_playing_text = result or "No track"
            # Clear old artwork when playback stops or the current track has no cover.
            artwork_path = art
        except Exception as exc:
            print(f"Now-playing update failed: {exc}")
            now_playing_text = "No track"
            artwork_path = None
        time.sleep(2)


np_thread = threading.Thread(target=now_playing_thread, daemon=True)
np_thread.start()

# AUDIO CAPTURE



def capture_audio():
    """Capture system audio in a background thread for the visualizer."""
    global audio
    try:
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
                data = np.clip(data * AUDIO_GAIN, -1.0, 1.0)
                with audio_lock:
                    audio[:] = data
    except Exception as exc:
        print(f"Audio capture unavailable: {exc}")



# Start the audio recording in a background thread.

# Without a separate thread, recording could block the
# Pygame window from updating.
audio_thread = threading.Thread(
    target=capture_audio,
    daemon=True
)

audio_thread.start()



# PYGAME SETUP



pygame.init()


# Create the normal window.
# RESIZABLE allows the user to drag the window larger/smaller.
screen = pygame.display.set_mode(
    (SCREEN_W, SCREEN_H),
    pygame.RESIZABLE
)


# Window title.
pygame.display.set_caption(
    "Audio Visualizer"
)


# Clock controls the FPS.
clock = pygame.time.Clock()


# Canvas is where we draw the visualizer.

# SRCALPHA allows transparency, which is needed for:

#   - glow
#   - trails
#   - fading
canvas = pygame.Surface(
    (SCREEN_W, SCREEN_H),
    pygame.SRCALPHA
)


# Keeps track of fullscreen mode.
fullscreen = False



# FFT SETUP


# The FFT is the part that turns the raw audio waveform into
# frequency information.


# FFT result:

# frequency → strength

# Example:
# 50 Hz     → strong
# 500 Hz    → medium
# 2000 Hz   → strong
# 10000 Hz  → weak

# Create frequency boundaries.

# geomspace creates logarithmically spaced frequencies.

# This is useful because audio frequencies are better
# represented logarithmically than with equal Hz steps.


def update_fft_bins():
    """Recomputes frequency distributions and resetting bars array when N_BARS changes."""
    global frequencies, bins, bars
    frequencies = np.geomspace(50, 12500, N_BARS + 1)
    bins = (frequencies * CHUNK / SAMPLE_RATE).astype(int)
    bins = np.clip(bins, 0, CHUNK // 2)
    bars = np.zeros(N_BARS, dtype=float)


update_fft_bins()


# Create a Hann window.

# This reduces the abrupt edges of each audio chunk and
# makes the FFT cleaner.
window = np.hanning(
    CHUNK
)


# Starting point for automatic scaling.
max_scale = MIN_SCALE



# COLOR FUNCTION


# This determines the color based on ACTUAL FREQUENCY.

# The spectrum is approximately:

#     BASS            MIDS             TREBLE

# 45 Hz -------- 500 Hz -------- 3000 Hz -------- 12.5 kHz

# BLUE               PURPLE               RED



def get_frequency_color(frequency):
    """
    Returns an RGB color based on the frequency.

    Bass:
        blue

    Low mids:
        blue → purple

    Mids/vocal area:
        purple

    Upper mids:
        purple → magenta

    Treble:
        magenta → red
    """


    # VERY LOW FREQUENCIES

    # 50 Hz - 250 Hz

    # This is primarily the bass region.

    # Keep it strongly blue.

    if frequency <= 250:

        return (
            0,
            80,
            255
        )



    # BASS → PURPLE

    # 250 Hz - 700 Hz

    # Gradually move from blue to purple.

    elif frequency <= 700:

        amount = (
            frequency - 250
        ) / (
            700 - 250
        )

        # Blue:
        #     (0, 80, 255)
        #
        # Purple:
        #     (180, 0, 255)

        red = int(
            180 * amount
        )

        green = int(
            80 * (1 - amount)
        )

        blue = 255

        return (
            red,
            green,
            blue
        )



    # MIDRANGE

    # 700 Hz - 3000 Hz

    # Keep this region purple.

    # this region gives the visualizer a clear purple midrange.

    elif frequency <= 3000:

        return (
            180,
            0,
            255
        )


    # PURPLE → MAGENTA

    # 3000 Hz - 5000 Hz

    # This is the transition from mids toward treble.

    elif frequency <= 5000:

        amount = (
            frequency - 3000
        ) / (
            5000 - 3000
        )

        # Purple:
        #     (180, 0, 255)

        # Magenta:
        #     (255, 0, 180)

        red = int(
            180
            + (255 - 180) * amount
        )

        green = 0

        blue = int(
            255
            - (255 - 180) * amount
        )

        return (
            red,
            green,
            blue
        )



    # MAGENTA → RED


    # 5000 Hz - 10000 Hz


    elif frequency <= 10000:

        amount = (
            frequency - 5000
        ) / (
            10000 - 5000
        )

        # Magenta:
        #     (255, 0, 180)
        #
        # Red:
        #     (255, 0, 0)

        red = 255

        green = 0

        blue = int(
            180 * (1 - amount)
        )

        return (
            red,
            green,
            blue
        )



    # VERY HIGH TREBLE


    # 10,000 Hz - 12,500 Hz

    # Keep these bars strongly red.

    else:

        return (
            255,
            0,
            0
        )



# DRAW BAR



def draw_bar(surface, rectangle, color):
    """
    Draws one bar and its glow.

    The glow is made from larger transparent rectangles
    behind the actual bar.
    """


    # Larger rectangles create wider glow.
    #
    # Increase these numbers for a larger glow.
    glow1 = rectangle.inflate(
        16,
        16
    )

    glow2 = rectangle.inflate(
        12,
        12
    )

    glow3 = rectangle.inflate(
        8,
        8
    )



    # BIG GLOW


    glow_surface = pygame.Surface(
        glow1.size,
        pygame.SRCALPHA
    )


    # RGBA:
    #
    # RGB = color
    # 35  = transparency
    #
    # Higher alpha makes the glow brighter.
    pygame.draw.rect(
        glow_surface,
        (*color, 60),
        glow_surface.get_rect()
    )


    surface.blit(
        glow_surface,
        glow1.topleft
    )



    # MEDIUM GLOW


    glow_surface = pygame.Surface(
        glow2.size,
        pygame.SRCALPHA
    )

    pygame.draw.rect(
        glow_surface,
        (*color, 80),
        glow_surface.get_rect()
    )

    surface.blit(
        glow_surface,
        glow2.topleft
    )



    # SMALL GLOW


    glow_surface = pygame.Surface(
        glow3.size,
        pygame.SRCALPHA
    )

    pygame.draw.rect(
        glow_surface,
        (*color, 100),
        glow_surface.get_rect()
    )

    surface.blit(
        glow_surface,
        glow3.topleft
    )



    # SOLID BAR


    pygame.draw.rect(
        surface,
        color,
        rectangle
    )


# ============================================================
# MENU CONFIGURATION & CALLBACKS
# ============================================================


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


# Build settings menu once outside the loop
font = pygame_menu.font.FONT_8BIT

mytheme = themes.Theme(
    background_color=(0, 0, 0, 200),
    title_background_color=(0, 0, 0),
    title_font_color=(255, 255, 255),
    widget_font_color=(255, 255, 255),
    selection_color=(255, 0, 255),
    title_font_shadow=True,
    widget_padding=25,
    widget_font=font,
    title_bar_style=pygame_menu.widgets.MENUBAR_STYLE_NONE,
    widget_alignment=pygame_menu.locals.ALIGN_LEFT
)

theme = mytheme
theme.title_font_size = 24
theme.widget_font_size = 18

settings_menu = pygame_menu.Menu(
    '',
    SCREEN_W,
    SCREEN_H,
    theme=mytheme
)


settings_menu.add.range_slider(
    'Number of Bars',
    default=N_BARS,
    range_values=(8, 128),
    increment=1,
    onchange=set_n_bars
)
settings_menu.add.range_slider(
    'Audio Gain',
    default=AUDIO_GAIN,
    range_values=(1, 10.0),
    increment=1,
    onchange=set_audio_gain,
)
settings_menu.add.range_slider(
    'Smoothing',
    default=SMOOTHING,
    range_values=(0.01, 1.0),
    increment=0.01,
    onchange=set_smoothing,
)
settings_menu.add.range_slider(
    'Bar Gap',
    default=BAR_GAP,
    range_values=(0, 50),
    increment=1,
    onchange=set_bar_gap
)
settings_menu.add.range_slider(
    'Trail Alpha',
    default=TRAIL_ALPHA,
    range_values=(10, 255),
    increment=1,
    onchange=set_trail_alpha
)
settings_menu.add.range_slider(
    'Bass Shake Threshold',
    default=BASS_THRESHOLD,
    range_values=(10, 500),
    increment=10,
    onchange=set_bass_threshold

)
settings_menu.add.range_slider(
    'Treble Boost',
    default=TREBLE_BOOST,
    range_values=(1.0, 10.0),
    increment=1,
    onchange=set_treble_boost

)

settings_menu.add.range_slider(
    'FPS',
    default=FPS,
    range_values=(1.0, 360.0),
    increment=1,
    onchange=set_fps

)

# --- NOW PLAYING RENDER (cached) ---
np_surface = None
np_last_text = None
np_last_width = None
ARTWORK_SIZE = 84
artwork_surface = None
artwork_last_path = None


def render_now_playing(track_text, max_width):
    """Render a readable track label that fits beside the album cover."""
    global np_surface, np_last_text, np_last_width
    max_width = max(1, int(max_width))
    cache_key = (track_text, max_width)
    if cache_key == (np_last_text, np_last_width):
        return np_surface

    label = f"♪ {track_text}"
    font = None
    rendered = None
    for size in range(34, 13, -1):
        candidate_font = pygame.font.SysFont("Arial", size, bold=True)
        candidate = candidate_font.render(label, True, (255, 255, 255)).convert_alpha()
        if candidate.get_width() <= max_width:
            font, rendered = candidate_font, candidate
            break

    if rendered is None:
        font = pygame.font.SysFont("Arial", 14, bold=True)
        shortened = label
        ellipsis = "…"
        while shortened and font.size(shortened + ellipsis)[0] > max_width:
            shortened = shortened[:-1]
        rendered = font.render((shortened + ellipsis) if shortened else ellipsis, True, (255, 255, 255)).convert_alpha()

    # Keep the original blue-to-red gradient style, with safe bounds for narrow labels.
    pixels = pygame.surfarray.pixels3d(rendered)
    alpha = pygame.surfarray.pixels_alpha(rendered)
    width = pixels.shape[0]
    if width > 0:
        gradient = np.linspace(0.0, 1.0, width, dtype=np.float32)[:, np.newaxis]
        pixels[:, :, 0] = np.where(alpha > 0, (255 * gradient).astype(np.uint8), 0)
        pixels[:, :, 1] = 0
        pixels[:, :, 2] = np.where(alpha > 0, (255 * (1.0 - gradient)).astype(np.uint8), 0)
    del pixels
    del alpha

    np_surface = rendered
    np_last_text = track_text
    np_last_width = max_width
    return np_surface


def load_artwork(path):
    """Load and resize current artwork; clear the cached image when no track art exists."""
    global artwork_surface, artwork_last_path
    if not path:
        artwork_surface = None
        artwork_last_path = None
        return None
    if path == artwork_last_path:
        return artwork_surface

    try:
        image = pygame.image.load(path).convert_alpha()
        artwork_surface = pygame.transform.smoothscale(image, (ARTWORK_SIZE, ARTWORK_SIZE))
        artwork_last_path = path
    except (pygame.error, OSError) as exc:
        print(f"Artwork load failed: {exc}")
        artwork_surface = None
        artwork_last_path = path
    return artwork_surface


settings_menu.disable()



# MAIN LOOP

#   EVENTS
#      ↓
#   GET AUDIO
#      ↓
#   FFT
#      ↓
#   MEASURE FREQUENCIES
#      ↓
#   CALCULATE BAR HEIGHTS
#      ↓
#   SMOOTH
#      ↓
#   DRAW
#      ↓
#   DISPLAY


running = True


while running:

    events = pygame.event.get()
    menu_events = []

    # Handle Escape ourselves before pygame_menu can consume it. This behaves the
    # same on Windows and macOS: Escape closes an open menu, or opens it otherwise.
    for event in events:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if settings_menu.is_enabled():
                settings_menu.disable()
            else:
                settings_menu.enable()
            continue

        menu_events.append(event)

        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            # F11 toggles fullscreen.
            fullscreen = not fullscreen
            if fullscreen:
                screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)

            screen_width, screen_height = screen.get_size()
            canvas = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
            settings_menu.resize(screen_width, screen_height)

        elif event.type == pygame.VIDEORESIZE and not fullscreen:
            screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            canvas = pygame.Surface((event.w, event.h), pygame.SRCALPHA)
            settings_menu.resize(event.w, event.h)

    # The menu needs both update() and draw() to be interactive and visible.
    if settings_menu.is_enabled():
        settings_menu.update(menu_events)



    # GET CURRENT SCREEN SIZE


    # This is why fullscreen and resizing work.
    # We never assume that the screen is still 700x850.


    screen_width, screen_height = screen.get_size()



    # GET AUDIO


    with audio_lock:

        # Make a copy so the recording thread can continue
        # working safely.
        samples = audio.copy()



    # PREPARE AUDIO FOR FFT


    # Apply the Hann window.
    samples *= window



    # FFT

    # Convert the audio waveform into frequency information.


    spectrum = np.abs(
        np.fft.rfft(samples)
    )



    # CREATE TARGET BAR VALUES


    target_bars = np.zeros(
        N_BARS,
        dtype=float
    )


    # Process each bar independently.
    for i in range(N_BARS):


        # Find which FFT bins belong to this bar.
        start = bins[i]
        end = bins[i + 1]


        # Make sure every bar has at least one FFT bin.
        if end <= start:

            end = start + 1


        # Don't go past the FFT array.
        end = min(
            end,
            len(spectrum)
        )


        # Find the strongest frequency inside this bar's range.

        # Using MAX means one strong frequency can make the
        # entire bar react.
        target_bars[i] = np.max(
            spectrum[start:end]
        )



        # TREBLE VISUAL BOOST

        # We calculate this bar's center frequency and give
        # frequencies above TREBLE_START a gradually increasing
        # visual boost.


        frequency = (
            frequencies[i]
            + frequencies[i + 1]
        ) / 2


        if frequency > TREBLE_START:

            # Calculate how far through the boost range we are.

            # At TREBLE_START:
            #     amount = 0

            # At TREBLE_FULL:
            #     amount = 1

            amount = (
                frequency - TREBLE_START
            ) / (
                TREBLE_FULL - TREBLE_START
            )


            # Prevent the value from going above 1.
            amount = min(
                1.0,
                amount
            )


            # Start at 1.0x and gradually approach TREBLE_BOOST.
            boost = (
                1.0
                + (
                    TREBLE_BOOST - 1.0
                ) * amount
            )


            target_bars[i] *= boost



    # AUTOMATIC SCALE


    # Find the strongest bar right now.
    current_max = np.max(
        target_bars
    )


    # max_scale determines how much audio is needed for
    # a bar to reach close to the top.

    # The 0.95 causes the scale to slowly fall when the music
    # becomes quieter instead of instantly changing.
    max_scale = max(
        MIN_SCALE,
        max_scale * 0.95,
        current_max
    )



    # SMOOTH BAR MOVEMENT


    for i in range(N_BARS):


        # Convert the audio value into pixels.

        # - target_bars[i] / max_scale gives approximately
        #   0 → 1.

        # - screen_height - 40 gives us the maximum visual
        #   height available.

        target_height = (
            target_bars[i]
            / max_scale
        ) * (
            screen_height - 40
        )


        # Instead of instantly jumping to target_height,
        # move a percentage of the distance every frame.

        # This is what makes the animation smooth.

        bars[i] += (
            target_height
            - bars[i]
        ) * SMOOTHING


        # Prevent negative heights.
        bars[i] = max(
            0,
            bars[i]
        )



    # TRAIL


    # The canvas isn't completely erased.

    # Instead, transparent black is drawn over it.

    # This makes old frames fade away.


    fade = pygame.Surface(
        (screen_width, screen_height),
        pygame.SRCALPHA
    )


    fade.fill(
        (
            0,
            0,
            0,
            TRAIL_ALPHA
        )
    )


    canvas.blit(
        fade,
        (0, 0)
    )



    # BAR WIDTH


    # Calculate this every frame so bars automatically fit
    # whatever screen size we're using.


    bar_width = (
        screen_width
        - (N_BARS - 1) * BAR_GAP
    ) / N_BARS



    # DRAW EVERY BAR


    for i in range(N_BARS):


        # X POSITION


        x = i * (
            bar_width
            + BAR_GAP
        )



        # BAR HEIGHT


        bar_height = bars[i]


        # Pygame's y=0 is at the TOP.

        # We want the bars to grow upward from the bottom.
        y = (
            screen_height
            - bar_height
        )


        # Create the rectangle Pygame will draw.
        rectangle = pygame.Rect(
            int(x),
            int(y),
            int(bar_width),
            int(bar_height)
        )



        # FIND THIS BAR'S FREQUENCY


        # Each bar represents a frequency range.

        # We use the middle of that range to decide its color.

        frequency = (
            frequencies[i]
            + frequencies[i + 1]
        ) / 2



        # GET COLOR


        color = get_frequency_color(
            frequency
        )


        def get_theme_color_at_x(x, width):
            """Map screen position to the bass-to-treble color spectrum."""
            position = x / max(width - 1, 1)
            position = max(0.0, min(1.0, position))

            # Logarithmic mapping, similar to the FFT frequency bands.
            frequency = 50 * ((12500 / 50) ** position)

            return get_frequency_color(frequency)

        # DRAW BAR + GLOW


        draw_bar(
            canvas,
            rectangle,
            color
        )


    # BASS SCREEN SHAKE

    # The first six bars are used as a rough measurement
    # of the low-frequency energy.

    bass_range = min(6, N_BARS)
    bass = bars[:bass_range].mean() if bass_range > 0 else 0


    # If bass is above the threshold, shake the screen.
    if bass > BASS_THRESHOLD:


        # Random horizontal movement.
        shake_x = random.randint(
            -4,
            4
        )


        # Random vertical movement.
        shake_y = random.randint(
            -4,
            4
        )


    else:

        # No bass shake.
        shake_x = 0
        shake_y = 0


    # DISPLAY


    # Clear the actual screen.
    screen.fill(
        (0, 0, 0)
    )

    # Put the finished canvas onto the screen.

    # The shake values move the entire visualizer.
    screen.blit(
        canvas,
        (
            shake_x,
            shake_y
        )
    )
    # NOW PLAYING: album cover and track label, drawn directly onto the Pygame window.
    if now_playing_text and now_playing_text != "No track":
        margin = 12
        art_size = min(ARTWORK_SIZE, max(48, screen_height // 8))
        label_x = margin + art_size + 12
        max_label_width = max(1, screen_width - label_x - margin)
        panel_height = max(art_size, 44)

        # Light translucent backing makes the cover and text readable over the bars.
        panel_width = min(screen_width - 2 * margin, art_size + 24 + max_label_width)
        panel = pygame.Surface((max(1, panel_width), panel_height + 8), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 150), panel.get_rect(), border_radius=10)
        screen.blit(panel, (margin - 4, margin - 4))

        art = load_artwork(artwork_path)
        art_rect = pygame.Rect(margin, margin, art_size, art_size)
        if art is not None:
            if art.get_size() != (art_size, art_size):
                art = pygame.transform.smoothscale(art, (art_size, art_size))
            screen.blit(art, art_rect)
            pygame.draw.rect(screen, (255, 255, 255, 140), art_rect, width=1, border_radius=6)
        else:
            pygame.draw.rect(screen, (35, 35, 45), art_rect, border_radius=6)
            placeholder_font = pygame.font.SysFont("Arial", max(24, art_size // 2), bold=True)
            placeholder = placeholder_font.render("♪", True, (180, 120, 255))
            screen.blit(placeholder, placeholder.get_rect(center=art_rect.center))

        np_surface = render_now_playing(now_playing_text, max_label_width)
        if np_surface:
            np_rect = np_surface.get_rect(midleft=(label_x, margin + art_size // 2))
            screen.blit(np_surface, np_rect)

    # Draw the settings menu after the visualizer so it appears above the animation.
    if settings_menu.is_enabled():
        settings_menu.draw(screen)

    pygame.display.flip()


    # Limit the program to the chosen FPS.
    clock.tick(max(1, int(FPS)))



# CLEANUP



# Tell the recording thread to stop.
audio_running = False


# Give the thread up to one second to finish.
audio_thread.join(
    timeout=1
)


# Shut down Pygame.
pygame.quit()


# Exit the Python program.
sys.exit()
