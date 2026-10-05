import random
import sys
import threading
import platform

import numpy as np
import pygame
import pygame_menu
import soundcard as sc


# ============================================================
# SETTINGS
# ============================================================
#
# These variables are the easiest way to customize the
# visualizer.
#
# ============================================================


# ------------------------------------------------------------
# AUDIO ANALYSIS
# ------------------------------------------------------------

# CHUNK is the number of audio samples analyzed at once.
#
# Smaller CHUNK:
#   - reacts faster
#   - less frequency detail
#
# Larger CHUNK:
#   - more frequency detail
#   - slightly slower response
#
CHUNK = 2046


# Number of vertical bars.
#
# More bars = more frequency detail.
# Fewer bars = larger, simpler bars.
N_BARS = 36


# Audio sample rate.
#
# 48000 means 48,000 samples are captured every second.
#
# This is also used by the FFT to figure out what frequencies
# the audio samples represent.
SAMPLE_RATE = 48000


# ------------------------------------------------------------
# WINDOW
# ------------------------------------------------------------

# Starting size of the normal window.
#
# This is only the normal window size.
# Fullscreen automatically uses your monitor's resolution.
SCREEN_W = 700
SCREEN_H = 850


# Amount of space between bars.
#
# Smaller = bars closer together.
# Larger = more space between bars.
BAR_GAP = 18


# ------------------------------------------------------------
# AUDIO RESPONSE
# ------------------------------------------------------------

# Multiplies the captured audio before visualization.
#
# Higher = bars react more strongly.
# Lower = bars react less strongly.
#
# This does NOT make your speakers louder.
AUDIO_GAIN = 2.5


# Controls how smoothly the bars move.
#
# 0.05 = very smooth and slow
# 0.10 = smooth
# 0.20 = more responsive
# 1.00 = immediate movement
SMOOTHING = 0.15


# Prevents the automatic scaling from becoming too small.
#
# Higher = quieter/smaller bars.
# Lower = more sensitive visualization.
MIN_SCALE = 500


# ------------------------------------------------------------
# VISUAL EFFECTS
# ------------------------------------------------------------

# Controls how quickly the trail fades.
# Higher = shorter trail.
# Lower = longer trail.
TRAIL_ALPHA = 100


# Controls when the bass screen shake starts.
# Lower = easier to trigger bass shake.
# Higher = harder to trigger bass shake.
BASS_THRESHOLD = 150


# Frames Per Second Number
FPS = 60


# ------------------------------------------------------------
# FREQUENCY VISUAL BOOST
# ------------------------------------------------------------
# Treble can be hard to see in visualizer, so the higher the value is,
# the stronger the boost in treble is in the visualizer without changing the treble in the song
#
TREBLE_BOOST = 2


# Frequency where the treble boost starts.
TREBLE_START = 3000


# Frequency where the full treble boost is reached.
TREBLE_FULL = 12000


# ============================================================
# AUDIO VARIABLES
# ============================================================
# This array stores the most recent chunk of audio.
# It starts filled with zeroes because there is no audio
# before the recording thread gives some.
audio = np.zeros(
    CHUNK,
    dtype=np.float32
)


# The audio is being updated by one thread while the main
# program is reading it.
#
# A lock prevents both from accessing it at exactly the
# same time.
audio_lock = threading.Lock()


# This tells the audio thread whether it should continue.
audio_running = True


# ============================================================
# FIND AUDIO DEVICE
# ============================================================


def get_audio_device():
    """
    Finds the computer's system audio.

    Windows:
        Uses the default speaker's loopback.

    macOS:
        Looks for BlackHole first.
        If BlackHole isn't available, it tries the
        default speaker's loopback.
    """

    # platform.system() tells us which operating system
    # the program is running on.
    #
    # Windows → "Windows"
    # macOS   → "Darwin"
    system = platform.system()


    # --------------------------------------------------------
    # WINDOWS
    # --------------------------------------------------------

    if system == "Windows":

        # Find the computer's default speaker.
        speaker = sc.default_speaker()


        # Use the speaker as a loopback recording device.
        #
        # Loopback means we're capturing what the computer
        # itself is playing rather than using the microphone.
        return sc.get_microphone(
            id=str(speaker.id),
            include_loopback=True
        )


    # --------------------------------------------------------
    # MACOS
    # --------------------------------------------------------

    elif system == "Darwin":

        # Get all available microphones and loopback devices.
        microphones = sc.all_microphones(
            include_loopback=True
        )


        # Search for BlackHole.
        #
        # BlackHole is commonly used on macOS to route system
        # audio into an application.
        for mic in microphones:

            if "blackhole" in mic.name.lower():

                return mic


        # If BlackHole wasn't found, try the default speaker.
        speaker = sc.default_speaker()

        return sc.get_microphone(
            id=str(speaker.id),
            include_loopback=True
        )


    # --------------------------------------------------------
    # UNSUPPORTED OPERATING SYSTEM
    # --------------------------------------------------------

    else:

        raise RuntimeError(
            "This program only supports Windows and macOS."
        )


# ============================================================
# AUDIO CAPTURE
# ============================================================


def capture_audio():
    """
    Continuously records system audio and stores it in
    the shared audio array.

    This runs in a separate thread so the audio recording
    doesn't stop Pygame from drawing.
    """

    global audio


    # Find the correct audio device.
    device = get_audio_device()


    # Open the recorder.
    #
    # channels=2 means stereo:
    #
    # channel 1 = left
    # channel 2 = right
    with device.recorder(
        samplerate=SAMPLE_RATE,
        channels=2
    ) as recorder:


        # Continue recording until the program closes.
        while audio_running:


            # Record one chunk of audio.
            data = recorder.record(
                numframes=CHUNK
            )


            # ------------------------------------------------
            # STEREO → MONO
            # ------------------------------------------------
            #
            # The FFT doesn't need separate left/right data
            # for this visualization.
            #
            # Averaging the two channels gives us one signal.

            if data.ndim > 1:

                data = data.mean(
                    axis=1
                )


            # ------------------------------------------------
            # MAKE SURE THE CHUNK IS THE CORRECT SIZE
            # ------------------------------------------------

            if len(data) < CHUNK:

                # If there aren't enough samples, add zeroes.
                data = np.pad(
                    data,
                    (0, CHUNK - len(data))
                )

            else:

                # If there are too many, cut the extra samples.
                data = data[:CHUNK]


            # ------------------------------------------------
            # AUDIO GAIN
            # ------------------------------------------------
            #
            # Makes the visualization more sensitive.
            #
            # This doesn't increase the actual volume coming
            # from the speakers.

            data = data * AUDIO_GAIN


            # ------------------------------------------------
            # KEEP AUDIO IN NORMAL RANGE
            # ------------------------------------------------

            data = np.clip(
                data,
                -1.0,
                1.0
            )


            # ------------------------------------------------
            # UPDATE THE SHARED AUDIO ARRAY
            # ------------------------------------------------

            with audio_lock:

                audio[:] = data


# Start the audio recording in a background thread.
#
# Without a separate thread, recording could block the
# Pygame window from updating.
audio_thread = threading.Thread(
    target=capture_audio,
    daemon=True
)

audio_thread.start()


# ============================================================
# PYGAME SETUP
# ============================================================


pygame.init()


# Create the normal window.
#
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
#
# SRCALPHA allows transparency, which is needed for:
#
#   - glow
#   - trails
#   - fading
canvas = pygame.Surface(
    (SCREEN_W, SCREEN_H),
    pygame.SRCALPHA
)


# Keeps track of fullscreen mode.
fullscreen = False


# ============================================================
# FFT SETUP
# ============================================================
#
# The FFT is the part that turns the raw audio waveform into
# frequency information.
#
#
# FFT result:
#
# frequency → strength
#
# Example:
# 50 Hz     → strong
# 500 Hz    → medium
# 2000 Hz   → strong
# 10000 Hz  → weak
#
# Create frequency boundaries.
#
# 20 Hz = low end of human hearing
# 20,000 Hz = high end of human hearing
#
# geomspace creates logarithmically spaced frequencies.
#
# This is useful because audio frequencies are better
# represented logarithmically than with equal Hz steps.


def update_fft_bins():
    """Recomputes frequency distributions and resetting bars array when N_BARS changes."""
    global frequencies, bins, bars
    frequencies = np.geomspace(20, 20000, N_BARS + 1)
    bins = (frequencies * CHUNK / SAMPLE_RATE).astype(int)
    bins = np.clip(bins, 0, CHUNK // 2)
    bars = np.zeros(N_BARS, dtype=float)


update_fft_bins()


# Create a Hann window.
#
# This reduces the abrupt edges of each audio chunk and
# makes the FFT cleaner.
window = np.hanning(
    CHUNK
)


# Starting point for automatic scaling.
max_scale = MIN_SCALE


# ============================================================
# COLOR FUNCTION
# ============================================================
#
# This determines the color based on ACTUAL FREQUENCY.
#
# The spectrum is approximately:
#
#     BASS            MIDS             TREBLE
#
# 20 Hz -------- 500 Hz -------- 3000 Hz -------- 20 kHz
#
# BLUE               PURPLE               RED
#


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


    # --------------------------------------------------------
    # VERY LOW FREQUENCIES
    # --------------------------------------------------------
    #
    # 20 Hz - 250 Hz
    #
    # This is primarily the bass region.
    #
    # Keep it strongly blue.

    if frequency <= 250:

        return (
            0,
            80,
            255
        )


    # --------------------------------------------------------
    # BASS → PURPLE
    # --------------------------------------------------------
    #
    # 250 Hz - 700 Hz
    #
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


    # --------------------------------------------------------
    # MIDRANGE
    # --------------------------------------------------------
    #
    # 700 Hz - 3000 Hz
    #
    # Keep this region purple.
    #
    # this region gives the visualizer a clear purple midrange.

    elif frequency <= 3000:

        return (
            180,
            0,
            255
        )


    # --------------------------------------------------------
    # PURPLE → MAGENTA
    # --------------------------------------------------------
    #
    # 3000 Hz - 5000 Hz
    #
    # This is the transition from mids toward treble.

    elif frequency <= 5000:

        amount = (
            frequency - 3000
        ) / (
            5000 - 3000
        )

        # Purple:
        #     (180, 0, 255)
        #
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


    # --------------------------------------------------------
    # MAGENTA → RED
    # --------------------------------------------------------
    #
    # 5000 Hz - 10000 Hz
    #
    # Now we're clearly entering treble.

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


    # --------------------------------------------------------
    # VERY HIGH TREBLE
    # --------------------------------------------------------
    #
    # 10,000 Hz - 20,000 Hz
    #
    # Keep these bars strongly red.

    else:

        return (
            255,
            0,
            0
        )


# ============================================================
# DRAW BAR
# ============================================================


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


    # --------------------------------------------------------
    # BIG GLOW
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # MEDIUM GLOW
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # SMALL GLOW
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # SOLID BAR
    # --------------------------------------------------------

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
theme = pygame_menu.themes.THEME_DARK.copy()
theme.title_font_size = 24
theme.widget_font_size = 18

settings_menu = pygame_menu.Menu(
    'Settings',
    SCREEN_W,
    SCREEN_H,
    theme=theme
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
    range_values=(0.5, 10.0),
    increment=0.5,
    onchange=set_audio_gain
)
settings_menu.add.range_slider(
    'Smoothing',
    default=SMOOTHING,
    range_values=(0.01, 1.0),
    increment=0.01,
    onchange=set_smoothing
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
    increment=5,
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
    increment=0.5,
    onchange=set_treble_boost
)

settings_menu.add.range_slider(
    'FPS',
    default=FPS,
    range_values=(1.0, 360.0),
    increment=1,
    onchange=set_fps
)

settings_menu.disable()


# ============================================================
# MAIN LOOP
# ============================================================
#
# The main loop is the heart of the program.
#
# It repeats hundreds of times per second:
#
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
# ============================================================


running = True


while running:

    events = pygame.event.get()

    # Pass event handling to pygame_menu when enabled
    if settings_menu.is_enabled():
        settings_menu.update(events)

    # ========================================================
    # HANDLE EVENTS
    # ========================================================

    for event in events:


        # ----------------------------------------------------
        # CLOSE WINDOW
        # ----------------------------------------------------

        if event.type == pygame.QUIT:

            running = False


        # ----------------------------------------------------
        # KEYBOARD
        # ----------------------------------------------------

        if event.type == pygame.KEYDOWN:


            # F11 toggles fullscreen.
            if event.key == pygame.K_F11:

                fullscreen = not fullscreen


                if fullscreen:

                    # (0, 0) tells Pygame to use the monitor's
                    # full resolution.
                    screen = pygame.display.set_mode(
                        (0, 0),
                        pygame.FULLSCREEN
                    )


                else:

                    # Return to normal window.
                    screen = pygame.display.set_mode(
                        (SCREEN_W, SCREEN_H),
                        pygame.RESIZABLE
                    )


                # Find the new dimensions.
                screen_width, screen_height = screen.get_size()


                # Recreate the canvas at the new size.
                canvas = pygame.Surface(
                    (screen_width, screen_height),
                    pygame.SRCALPHA
                )

                settings_menu.resize(screen_width, screen_height)

            elif event.key == pygame.K_ESCAPE:
                if settings_menu.is_enabled():
                    settings_menu.disable()
                else:
                    settings_menu.enable()


        # ----------------------------------------------------
        # MANUAL RESIZING
        # ----------------------------------------------------

        if event.type == pygame.VIDEORESIZE:

            if not fullscreen:

                # Create the window using its new dimensions.
                screen = pygame.display.set_mode(
                    (event.w, event.h),
                    pygame.RESIZABLE
                )


                # Make the drawing canvas match it.
                canvas = pygame.Surface(
                    (event.w, event.h),
                    pygame.SRCALPHA
                )

                settings_menu.resize(event.w, event.h)


    # ========================================================
    # GET CURRENT SCREEN SIZE
    # ========================================================
    #
    # This is why fullscreen and resizing work.
    #
    # We never assume that the screen is still 700x850.
    # ========================================================

    screen_width, screen_height = screen.get_size()


    # ========================================================
    # GET AUDIO
    # ========================================================

    with audio_lock:

        # Make a copy so the recording thread can continue
        # working safely.
        samples = audio.copy()


    # ========================================================
    # PREPARE AUDIO FOR FFT
    # ========================================================

    # Apply the Hann window.
    samples *= window


    # ========================================================
    # FFT
    # ========================================================
    #
    # Convert the audio waveform into frequency information.
    # ========================================================

    spectrum = np.abs(
        np.fft.rfft(samples)
    )


    # ========================================================
    # CREATE TARGET BAR VALUES
    # ========================================================

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
        #
        # Using MAX means one strong frequency can make the
        # entire bar react.
        target_bars[i] = np.max(
            spectrum[start:end]
        )


        # ====================================================
        # TREBLE VISUAL BOOST
        # ====================================================
        #
        # Higher frequencies naturally tend to look weaker.
        #
        # We calculate this bar's center frequency and give
        # frequencies above TREBLE_START a gradually increasing
        # visual boost.
        #
        # IMPORTANT:
        #
        # This does NOT change the music.
        # It only changes how tall the treble looks.

        frequency = (
            frequencies[i]
            + frequencies[i + 1]
        ) / 2


        if frequency > TREBLE_START:

            # Calculate how far through the boost range we are.
            #
            # At TREBLE_START:
            #     amount = 0
            #
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


    # ========================================================
    # AUTOMATIC SCALE
    # ========================================================

    # Find the strongest bar right now.
    current_max = np.max(
        target_bars
    )


    # max_scale determines how much audio is needed for
    # a bar to reach close to the top.
    #
    # The 0.95 causes the scale to slowly fall when the music
    # becomes quieter instead of instantly changing.
    max_scale = max(
        MIN_SCALE,
        max_scale * 0.95,
        current_max
    )


    # ========================================================
    # SMOOTH BAR MOVEMENT
    # ========================================================

    for i in range(N_BARS):


        # Convert the audio value into pixels.
        #
        # - target_bars[i] / max_scale gives approximately
        #   0 → 1.
        #
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
        #
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


    # ========================================================
    # TRAIL
    # ========================================================
    #
    # The canvas isn't completely erased.
    #
    # Instead, transparent black is drawn over it.
    #
    # This makes old frames fade away.
    # ========================================================

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


    # ========================================================
    # BAR WIDTH
    # ========================================================
    #
    # Calculate this every frame so bars automatically fit
    # whatever screen size we're using.
    # ========================================================

    bar_width = (
        screen_width
        - (N_BARS - 1) * BAR_GAP
    ) / N_BARS


    # ========================================================
    # DRAW EVERY BAR
    # ========================================================

    for i in range(N_BARS):


        # ----------------------------------------------------
        # X POSITION
        # ----------------------------------------------------

        x = i * (
            bar_width
            + BAR_GAP
        )


        # ----------------------------------------------------
        # BAR HEIGHT
        # ----------------------------------------------------

        bar_height = bars[i]


        # Pygame's y=0 is at the TOP.
        #
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


        # ----------------------------------------------------
        # FIND THIS BAR'S FREQUENCY
        # ----------------------------------------------------
        #
        # Each bar represents a frequency range.
        #
        # We use the middle of that range to decide its color.

        frequency = (
            frequencies[i]
            + frequencies[i + 1]
        ) / 2


        # ----------------------------------------------------
        # GET COLOR
        # ----------------------------------------------------

        color = get_frequency_color(
            frequency
        )


        # ----------------------------------------------------
        # DRAW BAR + GLOW
        # ----------------------------------------------------

        draw_bar(
            canvas,
            rectangle,
            color
        )


    # ========================================================
    # BASS SCREEN SHAKE
    # ========================================================
    #
    # The first six bars are used as a rough measurement
    # of the low-frequency energy.
    # ========================================================

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


    # ========================================================
    # DISPLAY
    # ========================================================


    # Clear the actual screen.
    screen.fill(
        (0, 0, 0)
    )

    # Put the finished canvas onto the screen.
    #
    # The shake values move the entire visualizer.
    screen.blit(
        canvas,
        (
            shake_x,
            shake_y
        )
    )

    if settings_menu.is_enabled():
        settings_menu.draw(screen)


    # Show the newly rendered frame.
    pygame.display.flip()


    # Limit the program to the chosen FPS.
    clock.tick(FPS)


# ============================================================
# CLEANUP
# ============================================================


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