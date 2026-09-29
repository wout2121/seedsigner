#!/usr/bin/env python3
"""
SeedSigner desktop emulator (for development / testing only)

Runs the unmodified SeedSigner code on a regular Linux/macOS desktop by
swapping out the Raspberry Pi specific hardware at runtime:

  * RPi.GPIO buttons  -> keyboard + on-screen buttons (Tkinter)
  * SPI display       -> Tkinter window
  * Pi camera         -> USB/laptop webcam via OpenCV (optional)

No SeedSigner source files are modified; everything is patched in this
launcher before the Controller starts.

    python tools/desktop_emulator/seedsigner_desktop.py [--scale 2] [--camera 0]

Keyboard:
    Arrow keys      joystick up/down/left/right
    Enter / Space   joystick press
    1 / 2 / 3       KEY1 / KEY2 / KEY3 (right-hand buttons)
    Esc             quit

WARNING: a desktop computer is NOT air-gapped. Only use test seeds
(e.g. "abandon abandon ... about"); never enter a seed that holds real funds.
"""
import argparse
import logging
import os
import sys
import threading
import time
import types
from unittest.mock import MagicMock


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

logger = logging.getLogger("seedsigner_desktop")



# ---------------------------------------------------------------------------
# 1. Fake RPi.GPIO
# ---------------------------------------------------------------------------
class _VirtualGPIO(types.ModuleType):
    """ Minimal RPi.GPIO stand-in. Buttons are active-LOW (pull-ups). """
    BOARD = 10
    BCM = 11
    IN = 1
    OUT = 0
    PUD_UP = 22
    PUD_DOWN = 21
    PUD_OFF = 20
    LOW = 0
    HIGH = 1
    RISING = 31
    FALLING = 32
    BOTH = 33
    RPI_INFO = {"P1_REVISION": 3}   # 40-pin header layout

    # A tap from the keyboard can be shorter than SeedSigner's 10ms polling
    # interval; keep each press visible for at least this long.
    MIN_PRESS_S = 0.08

    def __init__(self):
        super().__init__("RPi.GPIO")
        self._held = set()
        self._press_time = {}
        self._lock = threading.Lock()

    # --- RPi.GPIO API ---
    def setmode(self, *a, **kw): pass
    def setwarnings(self, *a, **kw): pass
    def setup(self, *a, **kw): pass
    def output(self, *a, **kw): pass
    def cleanup(self, *a, **kw): pass
    def add_event_detect(self, *a, **kw): pass
    def remove_event_detect(self, *a, **kw): pass
    def PWM(self, *a, **kw): return MagicMock()

    def input(self, pin):
        with self._lock:
            if pin in self._held:
                return self.LOW
            if time.time() - self._press_time.get(pin, 0) < self.MIN_PRESS_S:
                return self.LOW
            return self.HIGH

    # --- emulator API ---
    def press(self, pin):
        with self._lock:
            if pin not in self._held:
                self._press_time[pin] = time.time()
            self._held.add(pin)

    def release(self, pin):
        with self._lock:
            self._held.discard(pin)


GPIO = _VirtualGPIO()
_rpi = types.ModuleType("RPi")
_rpi.GPIO = GPIO
sys.modules["RPi"] = _rpi
sys.modules["RPi.GPIO"] = GPIO

# Pi-only modules that may be imported in the background; not needed here
for _mod in ["spidev", "picamera", "picamera.array"]:
    sys.modules.setdefault(_mod, MagicMock())

try:
    import numpy  # noqa: F401  (only needed for the webcam)
except ImportError:
    sys.modules["numpy"] = MagicMock()



# ---------------------------------------------------------------------------
# 2. Desktop display driver
# ---------------------------------------------------------------------------
from seedsigner.hardware.displays import display_driver                 # noqa: E402
from seedsigner.hardware.displays.display_driver import BaseDisplayDriver  # noqa: E402


class DesktopDisplay(BaseDisplayDriver):
    """ Receives frames from the Renderer; the Tk main loop picks them up. """
    latest_frame = None
    frame_lock = threading.Lock()
    frame_counter = 0

    def show_image(self, image, x_start: int = 0, y_start: int = 0):
        with DesktopDisplay.frame_lock:
            DesktopDisplay.latest_frame = image.copy()
            DesktopDisplay.frame_counter += 1


def _instantiate_desktop_display(cls, display_type="st7789", width=None, height=None):
    if display_type not in display_driver.ALL_DISPLAY_TYPES:
        raise ValueError(f"Invalid display type: {display_type}")
    # The Renderer swaps width/height for natively-portrait displays; mirror that
    # so the final canvas has the configured landscape size.
    if display_type == display_driver.DISPLAY_TYPE__ST7789:
        return DesktopDisplay(_width=width, _height=height)
    return DesktopDisplay(_width=height, _height=width)


display_driver.DisplayDriverFactory.instantiate_display_driver = classmethod(_instantiate_desktop_display)



# ---------------------------------------------------------------------------
# 3. Webcam instead of the Pi camera
# ---------------------------------------------------------------------------
from PIL import Image                               # noqa: E402
from seedsigner.hardware import camera as camera_module  # noqa: E402

CAMERA_INDEX = 0


class _WebcamStream:
    def __init__(self, resolution):
        import cv2
        self.cv2 = cv2
        self.resolution = resolution
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self.cap.isOpened():
            raise camera_module.CameraConnectionError()
        self.frame = None
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                frame = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
                # Center-crop to the requested aspect ratio and resize
                h, w = frame.shape[:2]
                tw, th = self.resolution
                target_ratio = tw / th
                if w / h > target_ratio:
                    new_w = int(h * target_ratio)
                    x0 = (w - new_w) // 2
                    frame = frame[:, x0:x0 + new_w]
                else:
                    new_h = int(w / target_ratio)
                    y0 = (h - new_h) // 2
                    frame = frame[y0:y0 + new_h, :]
                self.frame = self.cv2.resize(frame, (tw, th))
            else:
                time.sleep(0.05)

    def read(self):
        return self.frame

    def stop(self):
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()


def _start_video_stream_mode(self, resolution=(512, 384), framerate=12, format="bgr"):
    if self._video_stream is not None:
        self.stop_video_stream_mode()
    try:
        self._video_stream = _WebcamStream(resolution)
    except ImportError:
        logger.error("Webcam support needs OpenCV: pip install opencv-python-headless")
        raise camera_module.CameraConnectionError()


def _read_video_stream(self, as_image=False):
    if not self._video_stream:
        raise Exception("Must call start_video_stream first.")
    frame = self._video_stream.read()
    if not as_image or frame is None:
        return frame
    # Desktop webcams are already upright; mirror for a natural preview
    return Image.fromarray(frame.astype("uint8"), "RGB").convert("RGBA").transpose(Image.Transpose.FLIP_LEFT_RIGHT)


def _start_single_frame_mode(self, resolution=(720, 480)):
    self._single_resolution = resolution
    _start_video_stream_mode(self, resolution=resolution)


def _capture_frame(self):
    for _ in range(50):
        frame = self._video_stream.read() if self._video_stream else None
        if frame is not None:
            return Image.fromarray(frame.astype("uint8"), "RGB")
        time.sleep(0.05)
    raise camera_module.CameraConnectionError()


def _stop_single_frame_mode(self):
    self.stop_video_stream_mode()


camera_module.Camera.start_video_stream_mode = _start_video_stream_mode
camera_module.Camera.read_video_stream = _read_video_stream
camera_module.Camera.start_single_frame_mode = _start_single_frame_mode
camera_module.Camera.capture_frame = _capture_frame
camera_module.Camera.stop_single_frame_mode = _stop_single_frame_mode



# ---------------------------------------------------------------------------
# 4. Tk window
# ---------------------------------------------------------------------------
def run_window(scale: int):
    import tkinter as tk
    from PIL import ImageTk
    from seedsigner.hardware.buttons import HardwareButtonsConstants as K

    root = tk.Tk()
    root.title("SeedSigner desktop emulator (TEST SEEDS ONLY)")
    root.configure(bg="#222")

    screen_label = tk.Label(root, bg="black", bd=0)
    screen_label.grid(row=0, column=1, padx=16, pady=16)

    def make_button(parent, text, pin, **grid):
        b = tk.Button(parent, text=text, width=3, height=1, bg="#444", fg="white", activebackground="#f7931a")
        b.bind("<ButtonPress-1>", lambda e: GPIO.press(pin))
        b.bind("<ButtonRelease-1>", lambda e: GPIO.release(pin))
        b.grid(**grid)
        return b

    joystick = tk.Frame(root, bg="#222")
    joystick.grid(row=0, column=0, padx=(16, 0))
    make_button(joystick, "^", K.KEY_UP, row=0, column=1)
    make_button(joystick, "<", K.KEY_LEFT, row=1, column=0)
    make_button(joystick, "OK", K.KEY_PRESS, row=1, column=1)
    make_button(joystick, ">", K.KEY_RIGHT, row=1, column=2)
    make_button(joystick, "v", K.KEY_DOWN, row=2, column=1)

    keys = tk.Frame(root, bg="#222")
    keys.grid(row=0, column=2, padx=(0, 16))
    make_button(keys, "1", K.KEY1, row=0, column=0, pady=12)
    make_button(keys, "2", K.KEY2, row=1, column=0, pady=12)
    make_button(keys, "3", K.KEY3, row=2, column=0, pady=12)

    tk.Label(
        root, bg="#222", fg="#aaa",
        text="Arrows = joystick | Enter/Space = press | 1/2/3 = side keys | Esc = quit",
    ).grid(row=1, column=0, columnspan=3, pady=(0, 10))

    keymap = {
        "Up": K.KEY_UP, "Down": K.KEY_DOWN, "Left": K.KEY_LEFT, "Right": K.KEY_RIGHT,
        "Return": K.KEY_PRESS, "KP_Enter": K.KEY_PRESS, "space": K.KEY_PRESS,
        "1": K.KEY1, "2": K.KEY2, "3": K.KEY3,
        "KP_1": K.KEY1, "KP_2": K.KEY2, "KP_3": K.KEY3,
    }

    def on_key_press(event):
        if event.keysym == "Escape":
            quit_app()
        pin = keymap.get(event.keysym)
        if pin is not None:
            GPIO.press(pin)

    def on_key_release(event):
        pin = keymap.get(event.keysym)
        if pin is not None:
            GPIO.release(pin)

    root.bind("<KeyPress>", on_key_press)
    root.bind("<KeyRelease>", on_key_release)

    def quit_app():
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", quit_app)

    state = {"last": -1}

    def refresh():
        with DesktopDisplay.frame_lock:
            frame = DesktopDisplay.latest_frame
            counter = DesktopDisplay.frame_counter
        if frame is not None and counter != state["last"]:
            state["last"] = counter
            img = frame.convert("RGB").resize(
                (frame.width * scale, frame.height * scale), Image.Resampling.NEAREST
            )
            tk_img = ImageTk.PhotoImage(img, master=root)
            screen_label.configure(image=tk_img)
            screen_label.image = tk_img
        root.after(20, refresh)

    refresh()
    root.mainloop()



# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    global CAMERA_INDEX
    parser = argparse.ArgumentParser(description="Run SeedSigner on the desktop (test seeds only).")
    parser.add_argument("--scale", type=int, default=2, help="Window zoom factor (default: 2)")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV webcam index (default: 0)")
    parser.add_argument("-l", "--loglevel", default="INFO")
    args = parser.parse_args()
    CAMERA_INDEX = args.camera

    logging.basicConfig(
        level=getattr(logging, args.loglevel.upper(), logging.INFO),
        format="%(asctime)s %(levelname)8s [%(name)s]: %(message)s",
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)

    # Settings are stored in ./settings.json (relative to the working dir) when
    # "Persistent settings" is enabled; run from the repo root.
    os.chdir(REPO_ROOT)

    from seedsigner.controller import Controller

    def run_controller():
        try:
            Controller.get_instance().start()
        except Exception:
            logger.exception("SeedSigner stopped with an error")
        finally:
            os._exit(1)

    threading.Thread(target=run_controller, daemon=True).start()
    run_window(scale=args.scale)


if __name__ == "__main__":
    main()
