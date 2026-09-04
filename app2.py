import io
import json
import os
import re
import time
import queue
import threading
import subprocess
import traceback
import tkinter as tk
from tkinter import messagebox

import requests
from PIL import Image, ImageTk
import pyflac


# ============================================================
# CONFIG
# ============================================================

NAVIDROME_URL = "http://192.168.10.10:4533"
USERNAME = "nia"
PASSWORD = "367"

ALSA_DEVICE = "default"
ALSA_CARD = "0"

ALBUM_COLUMNS = 2
ALBUM_ROWS = 4
ALBUMS_PER_PAGE = ALBUM_COLUMNS * ALBUM_ROWS

LIBRARY_BATCH_SIZE = 100

HOLD_TIME_MS = 650

# RAM-only source cover size.
# Display images are resized from this source image and are
# NOT permanently cached as additional full-size images.
COVER_SOURCE_MAX = 1000 

ALBUM_CACHE_LIMIT = 12
QUEUE_CACHE_LIMIT = 24
PLAYING_CACHE_LIMIT = 1

HTTP_TIMEOUT = 15

PCM_CHUNK_BYTES = 65536
PCM_QUEUE_CHUNKS = 8

# Persistent settings.
SETTINGS_FILE = "kindle_navidrome_settings.json"

DEFAULT_VOLUME = 70


# ============================================================
# LOGGING
# ============================================================

def log(*args):
    print(
        time.strftime("[%H:%M:%S]"),
        *args,
        flush=True,
    )


# ============================================================
# SETTINGS
# ============================================================

class Settings:

    def __init__(self, filename):

        self.filename = filename
        self.lock = threading.Lock()

        self.values = {
            "volume": DEFAULT_VOLUME,
        }

        self.load()

    def load(self):

        try:

            with open(
                self.filename,
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

            volume = int(
                data.get(
                    "volume",
                    DEFAULT_VOLUME,
                )
            )
            global ALSA_DEVICE
            ALSA_DEVICE = data.get("device")

            self.values["volume"] = max(
                0,
                min(
                    100,
                    volume,
                ),
            )

            log(
                "Loaded volume:",
                self.values["volume"],
            )

        except FileNotFoundError:

            log(
                "No settings file; using defaults"
            )

        except Exception as e:

            log(
                "Settings load error:",
                repr(e),
            )

    def get_volume(self):

        with self.lock:
            return self.values["volume"]

    def set_volume(
            self,
            volume,
        ):

            volume = max(
                0,
                min(
                    100,
                    int(volume),
                ),
            )

            with self.lock:
                self.values["volume"] = volume

            try:

                directory = os.path.dirname(
                    self.filename
                )

                if directory:
                    os.makedirs(
                        directory,
                        exist_ok=True,
                    )

                data = {}

                try:
                    with open(
                        self.filename,
                        "r",
                        encoding="utf-8",
                    ) as f:

                        data = json.load(f)

                    if not isinstance(data, dict):
                        data = {}

                except (
                    FileNotFoundError,
                    json.JSONDecodeError,
                ):
                    data = {}

                # Change ONLY the volume.
                data["volume"] = volume

                temporary = (
                    self.filename
                    + ".tmp"
                )

                with open(
                    temporary,
                    "w",
                    encoding="utf-8",
                ) as f:

                    json.dump(
                        data,
                        f,
                        indent=4,
                    )

                os.replace(
                    temporary,
                    self.filename,
                )

            except Exception as e:

                log(
                    "Settings save error:",
                    repr(e),
                )

# ============================================================
# NAVIDROME
# ============================================================

class NavidromeClient:

    def __init__(
        self,
        base_url,
        username,
        password,
    ):

        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

        self.session = requests.Session()

    def request(
        self,
        endpoint,
        **params,
    ):

        params.update({
            "u": self.username,
            "p": self.password,
            "v": "1.16.1",
            "c": "KindleNavidrome",
            "f": "json",
        })

        url = (
            self.base_url
            + "/rest/"
            + endpoint
        )

        log("GET", url)
        log("PARAMS", params)

        response = self.session.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT,
        )

        log(
            "HTTP",
            response.status_code,
        )

        response.raise_for_status()

        data = response.json()

        root = data.get(
            "subsonic-response"
        )

        if root is None:

            raise RuntimeError(
                "Response is not a Subsonic response:\n"
                + str(data)[:1000]
            )

        if root.get("status") != "ok":

            error = root.get(
                "error",
                {},
            )

            raise RuntimeError(
                "Navidrome error "
                + str(
                    error.get(
                        "code",
                        "",
                    )
                )
                + ": "
                + str(
                    error.get(
                        "message",
                        "unknown error",
                    )
                )
            )

        return root

    def get_album_list(
        self,
        offset=0,
        size=8,
    ):

        root = self.request(
            "getAlbumList2",
            type="alphabeticalByName",
            size=size,
            offset=offset,
        )

        album_list = root.get(
            "albumList2",
            {},
        )

        return album_list.get(
            "album",
            [],
        )

    def get_album(
        self,
        album_id,
    ):

        root = self.request(
            "getAlbum",
            id=album_id,
        )

        return root.get(
            "album",
            {},
        )

    def get_cover(
        self,
        cover_id,
        size=COVER_SOURCE_MAX,
    ):

        url = (
            self.base_url
            + "/rest/getCoverArt"
        )

        params = {
            "u": self.username,
            "p": self.password,
            "v": "1.16.1",
            "c": "KindleNavidrome",
            "id": str(cover_id),
            "size": size,
        }

        response = self.session.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT,
        )

        response.raise_for_status()

        return response.content

    def get_stream_url(
        self,
        song_id,
    ):

        return (
            self.base_url
            + "/rest/stream"
            + "?u="
            + requests.utils.quote(
                self.username
            )
            + "&p="
            + requests.utils.quote(
                self.password
            )
            + "&v=1.16.1"
            + "&c=KindleNavidrome"
            + "&id="
            + requests.utils.quote(
                str(song_id)
            )
            + "&format=flac"
        )


# ============================================================
# RAM-ONLY COVER CACHE
# ============================================================

class CoverCache:

    def __init__(
        self,
        max_items=12,
    ):

        self.max_items = max_items

        self.ram = {}
        self.order = []

        self.lock = threading.Lock()

    def get(
        self,
        key,
    ):

        if not key:
            return None

        with self.lock:

            image = self.ram.get(
                key
            )

            if image is None:
                return None

            try:
                self.order.remove(
                    key
                )
            except ValueError:
                pass

            self.order.append(
                key
            )

            return image

    def put(
        self,
        key,
        data,
    ):

        if not key:
            return None

        try:

            if isinstance(
                data,
                Image.Image,
            ):

                image = data

                if image.mode != "RGB":
                    image = image.convert(
                        "RGB"
                    )

            else:

                image = Image.open(
                    io.BytesIO(data)
                )

                image.load()

                image = image.convert(
                    "RGB"
                )

            # Keep only a moderate RAM source image.
            # Display size is handled separately.
            image.thumbnail(
                (
                    COVER_SOURCE_MAX,
                    COVER_SOURCE_MAX,
                ),
                Image.Resampling.LANCZOS,
            )

        except Exception as e:

            log(
                "Could not decode cover:",
                repr(e),
            )

            return None

        with self.lock:

            if key in self.ram:

                try:
                    self.order.remove(
                        key
                    )
                except ValueError:
                    pass

            self.ram[key] = image
            self.order.append(key)

            while (
                len(self.order)
                > self.max_items
            ):

                old = self.order.pop(0)

                self.ram.pop(
                    old,
                    None,
                )

        return image

    def clear(self):

        with self.lock:

            self.ram.clear()
            self.order.clear()


# ============================================================
# RESPONSIVE IMAGE HELPERS
# ============================================================

def fit_image(
    image,
    max_width,
    max_height,
):
    """
    Returns a temporary resized PIL image.

    The cache retains only the source image.
    """

    if image is None:
        return None

    max_width = max(
        1,
        int(max_width),
    )

    max_height = max(
        1,
        int(max_height),
    )

    result = image.copy()

    result.thumbnail(
        (
            max_width,
            max_height,
        ),
        Image.Resampling.LANCZOS,
    )

    return result


# ============================================================
# AUDIO TRACK BUFFER
# ============================================================

class TrackBuffer:

    def __init__(
        self,
        song,
        stop_event,
    ):

        self.song = song
        self.stop_event = stop_event

        self.pcm_queue = queue.Queue(
            maxsize=PCM_QUEUE_CHUNKS
        )

        self.format_event = threading.Event()
        self.done_event = threading.Event()

        self.error = None

        self.sample_rate = None
        self.channels = None
        self.sample_format = None
        self.bytes_per_sample = None

        self.response = None
        self.thread = None

    def set_format(
        self,
        sample_rate,
        channels,
        sample_format,
        bytes_per_sample,
    ):

        if self.format_event.is_set():
            return

        self.sample_rate = int(
            sample_rate
        )

        self.channels = int(
            channels
        )

        self.sample_format = (
            sample_format
        )

        self.bytes_per_sample = int(
            bytes_per_sample
        )

        log(
            "Track format:",
            self.song.get("title"),
            self.sample_rate,
            "Hz",
            self.channels,
            "ch",
            self.sample_format,
        )

        self.format_event.set()

    def put(
        self,
        pcm,
    ):

        offset = 0
        length = len(pcm)

        while offset < length:

            if self.stop_event.is_set():
                return False

            end = min(
                offset + PCM_CHUNK_BYTES,
                length,
            )

            chunk = pcm[
                offset:end
            ]

            while (
                not self.stop_event.is_set()
            ):

                try:

                    self.pcm_queue.put(
                        chunk,
                        timeout=0.2,
                    )

                    break

                except queue.Full:
                    continue

            if self.stop_event.is_set():
                return False

            offset = end

        return True


# ============================================================
# AUDIO PLAYER
# ============================================================

class AudioPlayer:

    def __init__(
        self,
        client,
        settings,
    ):

        self.client = client
        self.settings = settings

        self.lock = threading.RLock()

        self.generation = 0

        self.session_thread = None

        self.stop_event = None
        self.pause_event = threading.Event()

        self.process = None
        self.process_lock = threading.Lock()

        self.active_response = None
        self.response_lock = threading.Lock()

        self.current_song = None

        self.position = 0.0
        self.duration = 0.0

        self.volume = (
            settings.get_volume()
            / 100.0
        )

        self.current_index = -1

        self.next_song_provider = None

        self.on_track_changed = None
        self.on_finished = None
        self.on_error = None

        self.mixer_control = (
            detect_mixer_control()
        )

        # Apply remembered volume once.
        self.apply_hardware_volume(
            int(
                self.volume * 100
            )
        )

    # ========================================================
    # VOLUME
    # ========================================================

    def set_volume(
        self,
        value,
    ):

        value = max(
            0,
            min(
                100,
                int(value),
            ),
        )

        self.volume = (
            value / 100.0
        )

        self.settings.set_volume(
            value
        )

        self.apply_hardware_volume(
            value
        )

    def apply_hardware_volume(
        self,
        value,
    ):

        if not self.mixer_control:
            return

        try:

            subprocess.run(
                [
                    "amixer",
                    "-q",
                    "-c",
                    ALSA_CARD,
                    "sset",
                    self.mixer_control,
                    str(value) + "%",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )

        except Exception as e:

            log(
                "Volume control error:",
                repr(e),
            )

    # ========================================================
    # APLAY
    # ========================================================

    def start_aplay(
        self,
        sample_rate,
        channels,
        sample_format,
    ):

        command = [
            "aplay",
            "-q",
            "-D",
            ALSA_DEVICE,
            "-t",
            "raw",
            "-f",
            sample_format,
            "-c",
            str(channels),
            "-r",
            str(sample_rate),
        ]

        log(
            "Starting aplay:",
            " ".join(command),
        )

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        with self.process_lock:
            self.process = process

        return process

    def stop_aplay(self):

        with self.process_lock:

            process = self.process
            self.process = None

        if process is None:
            return

        try:

            if process.stdin:
                process.stdin.close()

        except Exception:
            pass

        try:

            process.terminate()

            process.wait(
                timeout=1
            )

        except Exception:

            try:
                process.kill()
            except Exception:
                pass

    def terminate_current_process(self):

        with self.process_lock:

            process = self.process

        if process is None:
            return

        try:
            process.terminate()
        except Exception:
            pass

    # ========================================================
    # RESPONSE
    # ========================================================

    def set_active_response(
        self,
        response,
    ):

        with self.response_lock:
            self.active_response = response

    def clear_active_response(
        self,
        response,
    ):

        with self.response_lock:

            if (
                self.active_response
                is response
            ):

                self.active_response = None

    def close_active_response(self):

        with self.response_lock:

            response = (
                self.active_response
            )

            self.active_response = None

        if response is not None:

            try:
                response.close()
            except Exception:
                pass

    # ========================================================
    # FLAC CALLBACK
    # ========================================================

    def make_flac_callback(
        self,
        track_buffer,
    ):

        def callback(
            audio,
            sample_rate,
            num_channels,
            num_samples,
        ):

            if track_buffer.stop_event.is_set():
                return

            dtype_name = str(
                audio.dtype
            )

            if dtype_name in (
                "int16",
                "<i2",
                ">i2",
            ):

                sample_format = "S16_LE"
                bytes_per_sample = 2

                pcm = audio.astype(
                    "<i2",
                    copy=False,
                ).tobytes()

            elif dtype_name in (
                "int32",
                "<i4",
                ">i4",
            ):

                sample_format = "S32_LE"
                bytes_per_sample = 4

                pcm = audio.astype(
                    "<i4",
                    copy=False,
                ).tobytes()

            else:

                raise RuntimeError(
                    "Unsupported pyFLAC sample type: "
                    + dtype_name
                )

            track_buffer.set_format(
                sample_rate,
                num_channels,
                sample_format,
                bytes_per_sample,
            )

            track_buffer.put(
                pcm
            )

        return callback

    # ========================================================
    # TRACK PRODUCER
    # ========================================================

    def produce_track(
        self,
        track_buffer,
        generation,
    ):

        song = track_buffer.song

        response = None

        try:

            url = self.client.get_stream_url(
                song["id"]
            )

            response = self.client.session.get(
                url,
                stream=True,
                timeout=HTTP_TIMEOUT,
            )

            response.raise_for_status()

            track_buffer.response = response

            self.set_active_response(
                response
            )

            log(
                "Stream opened:",
                song.get("title"),
            )

            decoder = pyflac.StreamDecoder(
                write_callback=(
                    self.make_flac_callback(
                        track_buffer
                    )
                )
            )

            for chunk in response.iter_content(
                chunk_size=16384
            ):

                if track_buffer.stop_event.is_set():
                    break

                with self.lock:

                    if (
                        generation
                        != self.generation
                    ):
                        break

                if chunk:
                    decoder.process(
                        chunk
                    )

            if not track_buffer.stop_event.is_set():

                try:
                    decoder.finish()
                except Exception as e:

                    log(
                        "Decoder finish:",
                        repr(e),
                    )

        except Exception as e:

            if not track_buffer.stop_event.is_set():

                track_buffer.error = e

                log(
                    "TRACK PRODUCER ERROR:",
                    repr(e),
                )

                traceback.print_exc()

        finally:

            self.clear_active_response(
                response
            )

            if response is not None:

                try:
                    response.close()
                except Exception:
                    pass

            track_buffer.response = None

            track_buffer.done_event.set()

    def start_producer(
        self,
        track_buffer,
        generation,
    ):

        thread = threading.Thread(
            target=self.produce_track,
            args=(
                track_buffer,
                generation,
            ),
            daemon=True,
        )

        track_buffer.thread = thread

        thread.start()

    # ========================================================
    # FORMAT
    # ========================================================

    def wait_for_format(
        self,
        track_buffer,
    ):

        while not track_buffer.format_event.is_set():

            if track_buffer.stop_event.is_set():
                return False

            if track_buffer.done_event.wait(
                0.1
            ):

                if (
                    not track_buffer.format_event.is_set()
                ):

                    if track_buffer.error:
                        raise track_buffer.error

                    raise RuntimeError(
                        "Track produced no audio"
                    )

                break

        return (
            track_buffer.format_event.is_set()
        )

    # ========================================================
    # OUTPUT
    # ========================================================

    def output_track(
        self,
        track_buffer,
        generation,
        existing_process,
        existing_format,
    ):

        if not self.wait_for_format(
            track_buffer
        ):
            return (
                existing_process,
                existing_format,
            )

        new_format = (
            track_buffer.sample_rate,
            track_buffer.channels,
            track_buffer.sample_format,
        )

        process = existing_process

        if (
            process is None
            or existing_format != new_format
        ):

            if process is not None:
                self.stop_aplay()

            process = self.start_aplay(
                track_buffer.sample_rate,
                track_buffer.channels,
                track_buffer.sample_format,
            )

            existing_format = new_format

        self.sample_rate = (
            track_buffer.sample_rate
        )

        self.channels = (
            track_buffer.channels
        )

        self.position = 0.0

        bytes_per_frame = (
            track_buffer.channels
            * track_buffer.bytes_per_sample
        )

        while True:

            if track_buffer.stop_event.is_set():
                return (
                    process,
                    existing_format,
                )

            with self.lock:

                if (
                    generation
                    != self.generation
                ):

                    return (
                        process,
                        existing_format,
                    )

            while self.pause_event.is_set():

                if track_buffer.stop_event.wait(
                    0.1
                ):

                    return (
                        process,
                        existing_format,
                    )

                with self.lock:

                    if (
                        generation
                        != self.generation
                    ):

                        return (
                            process,
                            existing_format,
                        )

            try:

                chunk = (
                    track_buffer.pcm_queue.get(
                        timeout=0.1
                    )
                )

            except queue.Empty:

                if (
                    track_buffer.done_event.is_set()
                    and track_buffer.pcm_queue.empty()
                ):
                    break

                continue

            try:

                if process.stdin is None:
                    raise BrokenPipeError(
                        "aplay stdin closed"
                    )

                process.stdin.write(
                    chunk
                )

                if bytes_per_frame > 0:

                    frames = (
                        len(chunk)
                        / float(bytes_per_frame)
                    )

                    self.position += (
                        frames
                        / float(
                            track_buffer.sample_rate
                        )
                    )

            except (
                BrokenPipeError,
                OSError,
            ) as e:

                if track_buffer.stop_event.is_set():
                    return (
                        process,
                        existing_format,
                    )

                raise e

        if track_buffer.error:
            raise track_buffer.error

        return (
            process,
            existing_format,
        )

    # ========================================================
    # PLAYBACK WORKER
    # ========================================================

    def playback_worker(
        self,
        generation,
        first_song,
        first_index,
        first_next,
    ):

        current = TrackBuffer(
            first_song,
            self.stop_event,
        )

        next_buffer = None

        process = None
        output_format = None

        try:

            self.start_producer(
                current,
                generation,
            )

            if first_next is not None:

                next_buffer = TrackBuffer(
                    first_next[1],
                    self.stop_event,
                )

                self.start_producer(
                    next_buffer,
                    generation,
                )

            current_index = first_index

            while True:

                with self.lock:

                    if (
                        generation
                        != self.generation
                    ):
                        return

                process, output_format = (
                    self.output_track(
                        current,
                        generation,
                        process,
                        output_format,
                    )
                )

                if self.stop_event.is_set():
                    return

                if next_buffer is None:

                    next_info = (
                        self.get_next_song()
                    )

                    if next_info is None:
                        break

                    next_index, next_song = (
                        next_info
                    )

                    next_buffer = TrackBuffer(
                        next_song,
                        self.stop_event,
                    )

                    self.start_producer(
                        next_buffer,
                        generation,
                    )

                else:

                    next_index = (
                        current_index + 1
                    )

                current = next_buffer
                next_buffer = None

                current_index = next_index

                with self.lock:

                    self.current_index = (
                        current_index
                    )

                    self.current_song = (
                        current.song
                    )

                    self.position = 0.0

                    self.duration = (
                        current.song.get(
                            "duration",
                            0,
                        )
                        or 0
                    )

                if self.on_track_changed:

                    self.on_track_changed(
                        current_index,
                        current.song,
                    )

                following = (
                    self.get_next_song()
                )

                if following is not None:

                    following_index, following_song = (
                        following
                    )

                    if (
                        following_index
                        != current_index
                    ):

                        next_buffer = TrackBuffer(
                            following_song,
                            self.stop_event,
                        )

                        self.start_producer(
                            next_buffer,
                            generation,
                        )

            self.stop_aplay()

            if (
                not self.stop_event.is_set()
                and self.on_finished
            ):

                self.on_finished()

        except Exception as e:

            if not self.stop_event.is_set():

                log(
                    "PLAYBACK ERROR:",
                    repr(e),
                )

                traceback.print_exc()

                self.stop_aplay()

                if self.on_error:
                    self.on_error(
                        str(e)
                    )

        finally:

            self.close_active_response()

            if self.stop_event.is_set():
                self.stop_aplay()

    def get_next_song(self):

        provider = (
            self.next_song_provider
        )

        if provider is None:
            return None

        try:
            return provider(
                self.current_index
            )
        except Exception as e:

            log(
                "Next-song provider error:",
                repr(e),
            )

            return None

    # ========================================================
    # PLAY
    # ========================================================

    def play(
        self,
        song,
        index=-1,
        next_song_provider=None,
    ):

        self.stop()

        with self.lock:

            self.generation += 1

            generation = (
                self.generation
            )

            self.stop_event = (
                threading.Event()
            )

            self.current_song = song
            self.current_index = index

            self.position = 0.0

            self.duration = (
                song.get(
                    "duration",
                    0,
                )
                or 0
            )

            self.next_song_provider = (
                next_song_provider
            )

        self.pause_event.clear()

        first_next = None

        if next_song_provider is not None:

            try:
                first_next = (
                    next_song_provider(
                        index
                    )
                )
            except Exception as e:

                log(
                    "Next-song lookup error:",
                    repr(e),
                )

        thread = threading.Thread(
            target=self.playback_worker,
            args=(
                generation,
                song,
                index,
                first_next,
            ),
            daemon=True,
        )

        self.session_thread = thread

        thread.start()

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        with self.lock:

            old_event = self.stop_event

            if old_event is not None:
                old_event.set()

            self.generation += 1

        self.close_active_response()

        self.terminate_current_process()

        self.pause_event.clear()

        old_thread = (
            self.session_thread
        )

        if (
            old_thread is not None
            and old_thread
            is not threading.current_thread()
        ):

            try:
                old_thread.join(
                    timeout=0.5
                )
            except Exception:
                pass

        self.session_thread = None

    # ========================================================
    # PAUSE
    # ========================================================

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()

    def toggle_pause(self):

        if self.pause_event.is_set():
            self.resume()
        else:
            self.pause()

    def is_paused(self):

        return self.pause_event.is_set()


# ============================================================
# ALSA MIXER
# ============================================================

_mixer_control_cache = None
_mixer_control_checked = False


def detect_mixer_control():

    global _mixer_control_cache
    global _mixer_control_checked

    if _mixer_control_checked:
        return _mixer_control_cache

    _mixer_control_checked = True

    try:

        result = subprocess.run(
            [
                "amixer",
                "-c",
                ALSA_CARD,
                "scontrols",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )

        controls = re.findall(
            r"Simple mixer control '([^']+)'",
            result.stdout,
        )

    except Exception as e:

        log(
            "ALSA mixer detection failed:",
            repr(e),
        )

        return None

    if not controls:

        log(
            "No ALSA mixer controls found"
        )

        return None

    for preferred in (
        "Master",
        "PCM",
        "Speaker",
        "Digital",
        "Headphone",
    ):

        if preferred in controls:

            _mixer_control_cache = preferred

            log(
                "Mixer control:",
                preferred,
            )

            return preferred

    _mixer_control_cache = (
        controls[0]
    )

    log(
        "Mixer control:",
        controls[0],
    )

    return controls[0]


# ============================================================
# APPLICATION
# ============================================================

class App(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title(
            "Navidrome"
        )

        self.configure(
            bg="white"
        )

        self.settings = Settings(
            SETTINGS_FILE
        )

        self.current_view = "playing"

        # ----------------------------------------------------
        # Window resize tracking
        # ----------------------------------------------------

        self.resize_after_id = None

        self.last_render_width = 0
        self.last_render_height = 0

        self.bind(
            "<Configure>",
            self.on_window_resize,
        )

        # ----------------------------------------------------
        # Library
        # ----------------------------------------------------

        self.all_albums = []
        self.albums = []

        self.album_page = 0

        self.library_loading = False
        self.library_loaded = False

        self.album_view_generation = 0

        # ----------------------------------------------------
        # Album cache
        # ----------------------------------------------------

        self.cover_cache = CoverCache(
            ALBUM_CACHE_LIMIT
        )

        self.cover_images = []

        # ----------------------------------------------------
        # Playing cover
        # ----------------------------------------------------

        self.playing_cover_cache = (
            CoverCache(
                PLAYING_CACHE_LIMIT
            )
        )

        self.playing_cover_image = None
        self.playing_cover_photo = None

        self.playing_cover_loading = False

        # ----------------------------------------------------
        # Queue
        # ----------------------------------------------------

        self.queue = []
        self.queue_index = -1

        self.queue_lock = threading.RLock()

        self.queue_cover_cache = (
            CoverCache(
                QUEUE_CACHE_LIMIT
            )
        )

        self.queue_cover_loading = set()
        self.queue_photos = []

        # ----------------------------------------------------
        # Client/player
        # ----------------------------------------------------

        self.client = NavidromeClient(
            NAVIDROME_URL,
            USERNAME,
            PASSWORD,
        )

        self.player = AudioPlayer(
            self.client,
            self.settings,
        )

        self.player.on_track_changed = (
            self.player_track_changed
        )

        self.player.on_finished = (
            self.player_finished
        )

        self.player.on_error = (
            self.player_error
        )

        # ----------------------------------------------------
        # Screen
        # ----------------------------------------------------

        try:

            width = (
                self.winfo_screenwidth()
            )

            height = (
                self.winfo_screenheight()
            )

            log(
                "Screen:",
                width,
                "x",
                height,
            )

            self.geometry(
                f"{width}x{height}"
            )

        except Exception as e:

            log(
                "Screen size error:",
                repr(e),
            )

            self.geometry(
                "600x800"
            )

        # ----------------------------------------------------
        # Tabs
        # ----------------------------------------------------

        tabs = tk.Frame(
            self,
            bg="white",
        )

        tabs.pack(
            fill="x",
            side="top",
        )

        tk.Button(
            tabs,
            text="PLAYING",
            font=("Helvetica", 14),
            command=lambda:
            self.show_tab(
                "playing"
            ),
        ).pack(
            side="left",
            expand=True,
            fill="x",
        )

        tk.Button(
            tabs,
            text="ALBUMS",
            font=("Helvetica", 14),
            command=lambda:
            self.show_tab(
                "albums"
            ),
        ).pack(
            side="left",
            expand=True,
            fill="x",
        )

        tk.Button(
            tabs,
            text="QUEUE",
            font=("Helvetica", 14),
            command=lambda:
            self.show_tab(
                "queue"
            ),
        ).pack(
            side="left",
            expand=True,
            fill="x",
        )

        # ----------------------------------------------------
        # Main frames
        # ----------------------------------------------------

        self.content = tk.Frame(
            self,
            bg="white",
        )

        self.content.pack(
            fill="both",
            expand=True,
        )

        self.playing_frame = tk.Frame(
            self.content,
            bg="white",
        )

        self.albums_frame = tk.Frame(
            self.content,
            bg="white",
        )

        self.queue_frame = tk.Frame(
            self.content,
            bg="white",
        )

        # Temporary screens.
        self.tracklist_frame = None
        self.options_frame = None

        self.tracklist_album = None
        self.tracklist_songs = []

        self.options_song = None

        self.show_tab(
            "playing"
        )

        self.after(
            1000,
            self.update_ui,
        )

    # ========================================================
    # WINDOW RESIZE
    # ========================================================

    def on_window_resize(
        self,
        event,
    ):

        # Ignore child-widget Configure events.
        if event.widget is not self:
            return

        if self.resize_after_id is not None:

            try:
                self.after_cancel(
                    self.resize_after_id
                )
            except Exception:
                pass

        self.resize_after_id = (
            self.after(
                250,
                self.handle_resize,
            )
        )

    def handle_resize(self):

        self.resize_after_id = None

        width = max(
            1,
            self.winfo_width(),
        )

        height = max(
            1,
            self.winfo_height(),
        )

        if (
            width == self.last_render_width
            and height == self.last_render_height
        ):
            return

        self.last_render_width = width
        self.last_render_height = height

        if self.current_view == "playing":

            self.render_playing()

        elif self.current_view == "albums":

            self.render_albums()

        elif self.current_view == "queue":

            self.render_queue()

    # ========================================================
    # VIEW MANAGEMENT
    # ========================================================

    def destroy_temporary_views(self):

        if self.tracklist_frame is not None:

            try:
                self.tracklist_frame.destroy()
            except Exception:
                pass

            self.tracklist_frame = None

        if self.options_frame is not None:

            try:
                self.options_frame.destroy()
            except Exception:
                pass

            self.options_frame = None

    def show_tab(
        self,
        name,
    ):

        self.destroy_temporary_views()

        self.current_view = name

        self.playing_frame.pack_forget()
        self.albums_frame.pack_forget()
        self.queue_frame.pack_forget()

        if name == "playing":

            self.playing_frame.pack(
                fill="both",
                expand=True,
            )

            self.render_playing()

        elif name == "albums":

            self.albums_frame.pack(
                fill="both",
                expand=True,
            )

            if not self.library_loaded:

                if not self.library_loading:
                    self.load_library()

            else:

                self.render_albums()

        elif name == "queue":

            self.queue_frame.pack(
                fill="both",
                expand=True,
            )

            self.render_queue()

    # ========================================================
    # LIBRARY
    # ========================================================

    def load_library(self):

        if self.library_loading:
            return

        self.library_loading = True

        self.album_view_generation += 1

        self.render_library_loading()

        threading.Thread(
            target=self.library_worker,
            daemon=True,
        ).start()

    def library_worker(self):

        albums = []
        offset = 0

        try:

            while True:

                batch = (
                    self.client.get_album_list(
                        offset=offset,
                        size=LIBRARY_BATCH_SIZE,
                    )
                )

                if not batch:
                    break

                albums.extend(
                    batch
                )

                log(
                    "Albums loaded:",
                    len(albums),
                )

                if (
                    len(batch)
                    < LIBRARY_BATCH_SIZE
                ):
                    break

                offset += (
                    LIBRARY_BATCH_SIZE
                )

            self.after(
                0,
                lambda:
                self.library_loaded_ui(
                    albums
                ),
            )

        except Exception as e:

            log(
                "LIBRARY ERROR:",
                repr(e),
            )

            traceback.print_exc()

            self.after(
                0,
                lambda:
                self.library_error(
                    str(e)
                ),
            )

    def library_loaded_ui(
        self,
        albums,
    ):

        self.library_loading = False
        self.library_loaded = True

        self.all_albums = albums
        self.album_page = 0

        self.rebuild_page_menu()

        self.display_album_page()

    def library_error(
        self,
        error,
    ):

        self.library_loading = False

        self.render_albums()

        messagebox.showerror(
            "Navidrome",
            error,
        )

    def render_library_loading(self):

        for child in (
            self.albums_frame.winfo_children()
        ):
            child.destroy()

        tk.Label(
            self.albums_frame,
            text="Loading library...",
            font=("Helvetica", 18),
            bg="white",
        ).pack(
            expand=True
        )

    # ========================================================
    # ALBUM PAGE HELPERS
    # ========================================================

    def total_pages(self):

        if not self.all_albums:
            return 0

        return (
            len(self.all_albums)
            + ALBUMS_PER_PAGE
            - 1
        ) // ALBUMS_PER_PAGE

    def page_albums(
        self,
        page,
    ):

        start = (
            page
            * ALBUMS_PER_PAGE
        )

        return self.all_albums[
            start:
            start + ALBUMS_PER_PAGE
        ]

    def normalized_initial(
        self,
        name,
    ):

        name = (
            name
            or ""
        ).strip()

        if not name:
            return "#"

        first = name[0].upper()

        if (
            "A" <= first <= "Z"
        ):
            return first

        return "#"

    def page_label(
        self,
        page,
    ):

        albums = self.page_albums(
            page
        )

        if not albums:
            return "—"

        first = self.normalized_initial(
            albums[0].get(
                "name",
                "",
            )
        )

        last = self.normalized_initial(
            albums[-1].get(
                "name",
                "",
            )
        )

        if first == last:
            return first

        return (
            first
            + "–"
            + last
        )

    def rebuild_page_menu(self):

        if not hasattr(
            self,
            "page_menu",
        ):
            return

        self.page_menu.delete(
            0,
            "end",
        )

        pages = self.total_pages()

        previous_label = None

        for page in range(pages):

            label = self.page_label(
                page
            )

            if label != previous_label:

                if page > 0:
                    self.page_menu.add_separator()

                self.page_menu.add_command(
                    label=(
                        "──── "
                        + label
                        + " ────"
                    ),
                    state="disabled",
                    font=(
                        "Helvetica",
                        12,
                    ),
                )

                previous_label = label

            self.page_menu.add_command(
                label=str(page + 1),
                font=(
                    "Helvetica",
                    15,
                ),
                command=lambda p=page:
                self.goto_album_page(p),
            )

    def display_album_page(self):

        self.album_view_generation += 1

        generation = (
            self.album_view_generation
        )

        self.cover_cache.clear()

        self.albums = self.page_albums(
            self.album_page
        )

        self.render_albums()

        for album in self.albums:

            threading.Thread(
                target=self.load_album_cover,
                args=(
                    album,
                    generation,
                ),
                daemon=True,
            ).start()

    def goto_album_page(
        self,
        page,
    ):

        pages = self.total_pages()

        if pages <= 0:
            return

        page = max(
            0,
            min(
                page,
                pages - 1,
            ),
        )

        if page == self.album_page:
            return

        self.album_page = page

        self.display_album_page()

    def first_page(self):
        self.goto_album_page(0)

    def previous_page(self):
        self.goto_album_page(
            self.album_page - 1
        )

    def next_page(self):
        self.goto_album_page(
            self.album_page + 1
        )

    # ========================================================
    # ALBUM GRID
    # ========================================================

    def render_albums(self):

        for child in (
            self.albums_frame.winfo_children()
        ):
            child.destroy()

        if not self.library_loaded:

            if self.library_loading:
                self.render_library_loading()

            return

        # Navigation gets a fixed small portion at the bottom.
        nav_height = 55

        available_height = max(
            100,
            self.albums_frame.winfo_height()
            - nav_height
            - 10,
        )

        available_width = max(
            100,
            self.albums_frame.winfo_width()
            - 10,
        )

        grid = tk.Frame(
            self.albums_frame,
            bg="white",
        )

        grid.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=5,
        )

        self.cover_images = []

        for row in range(
            ALBUM_ROWS
        ):

            grid.grid_rowconfigure(
                row,
                weight=1,
            )

        for col in range(
            ALBUM_COLUMNS
        ):

            grid.grid_columnconfigure(
                col,
                weight=1,
            )

        if not self.albums:

            tk.Label(
                grid,
                text="No albums",
                font=("Helvetica", 16),
                bg="white",
            ).pack(
                expand=True
            )

        else:

            for i, album in enumerate(
                self.albums
            ):

                row = (
                    i
                    // ALBUM_COLUMNS
                )

                col = (
                    i
                    % ALBUM_COLUMNS
                )

                cell = tk.Frame(
                    grid,
                    bg="white",
                )

                cell.grid(
                    row=row,
                    column=col,
                    sticky="nsew",
                    padx=4,
                    pady=4,
                )

                self.make_album_cell(
                    cell,
                    album,
                )

        nav = tk.Frame(
            self.albums_frame,
            bg="white",
            height=nav_height,
        )

        nav.pack(
            fill="x",
            side="bottom",
        )

        nav.pack_propagate(False)

        tk.Button(
            nav,
            text="<<",
            font=("Helvetica", 14),
            command=self.first_page,
        ).pack(
            side="left",
            padx=3,
        )

        tk.Button(
            nav,
            text="<",
            font=("Helvetica", 14),
            command=self.previous_page,
        ).pack(
            side="left",
            padx=3,
        )

        self.page_button = tk.Menubutton(
            nav,
            text=(
                "PAGE "
                + str(
                    self.album_page + 1
                )
                + " ▼"
            ),
            font=("Helvetica", 14),
            relief="raised",
            bd=2,
            padx=10,
        )

        self.page_button.pack(
            side="left",
            padx=8,
        )

        self.page_menu = tk.Menu(
            self.page_button,
            tearoff=0,
            font=(
                "Helvetica",
                15,
            ),
        )

        self.page_button.configure(
            menu=self.page_menu
        )

        self.rebuild_page_menu()

        tk.Button(
            nav,
            text=">",
            font=("Helvetica", 14),
            command=self.next_page,
        ).pack(
            side="left",
            padx=3,
        )

        pages = self.total_pages()

        tk.Label(
            nav,
            text=(
                str(
                    self.album_page + 1
                )
                + " / "
                + str(
                    max(
                        pages,
                        1,
                    )
                )
            ),
            font=("Helvetica", 13),
            bg="white",
        ).pack(
            side="left",
            padx=8,
        )


    def make_album_cell(self, parent, album):

        width = max(
            200,
            self.albums_frame.winfo_width(),
        )

        height = max(
            300,
            self.albums_frame.winfo_height(),
        )

        # Space occupied by the bottom page navigation.
        nav_height = 55

        # Approximate space needed for the album title.
        title_height = 42

        # Gaps between cells.
        horizontal_gap = 14
        vertical_gap = 14

        cell_width = (
            width
            - horizontal_gap
        ) // ALBUM_COLUMNS

        cell_height = (
            height
            - nav_height
            - vertical_gap
        ) // ALBUM_ROWS

        cover_size = min(
            cell_width - 12,
            cell_height - title_height - 8,
        )

        # Don't make the covers unnecessarily tiny.
        cover_size = max(
            100,
            cover_size,
        )

        # 320 is still reasonable for the Kindle-sized UI.
        cover_size = min(
            320,
            cover_size,
        )

        cover_id = album.get(
            "coverArt"
        )

        image = self.cover_cache.get(
            cover_id
        )

        # Dedicated area for the artwork.
        cover_holder = tk.Frame(
            parent,
            width=cover_size,
            height=cover_size,
            bg="white",
        )

        cover_holder.pack(
            expand=True,
        )

        cover_holder.pack_propagate(
            False,
        )

        if image is not None:

            display = fit_image(
                image,
                cover_size,
                cover_size,
            )

            photo = ImageTk.PhotoImage(
                display
            )

            self.cover_images.append(
                photo
            )

            cover = tk.Label(
                cover_holder,
                image=photo,
                bg="white",
            )

            cover.pack(
                fill="both",
                expand=True,
            )

        else:

            cover = tk.Label(
                cover_holder,
                text="...",
                font=("Helvetica", 20),
                bg="white",
            )

            cover.pack(
                fill="both",
                expand=True,
            )

        title = tk.Label(
            parent,
            text=album.get(
                "name",
                "",
            ),
            font=("Helvetica", 12),
            bg="white",
            wraplength=max(
                100,
                cell_width - 10,
            ),
        )

        title.pack(
            fill="x",
            pady=3,
        )

        self.bind_album_gesture(
            parent,
            album,
        )

        self.bind_album_gesture(
            cover_holder,
            album,
        )

        self.bind_album_gesture(
            cover,
            album,
        )

        self.bind_album_gesture(
            title,
            album,
        )
    # ========================================================
    # ALBUM COVER
    # ========================================================

    def load_album_cover(
        self,
        album,
        generation,
    ):

        cover_id = album.get(
            "coverArt"
        )

        if not cover_id:
            return

        if (
            self.cover_cache.get(
                cover_id
            )
            is not None
        ):
            return

        try:

            data = self.client.get_cover(
                cover_id,
                COVER_SOURCE_MAX,
            )

            image = self.cover_cache.put(
                cover_id,
                data,
            )

            if image is None:
                return

            def update():

                if (
                    generation
                    != self.album_view_generation
                ):
                    return

                if self.current_view != "albums":
                    return

                self.render_albums()

            self.after(
                0,
                update,
            )

        except Exception as e:

            log(
                "COVER ERROR:",
                repr(e),
            )

    # ========================================================
    # ALBUM GESTURES
    # ========================================================

    def bind_album_gesture(
        self,
        widget,
        album,
    ):

        state = {
            "timer": None,
            "held": False,
        }

        def hold():

            state["timer"] = None
            state["held"] = True

            self.open_tracklist(
                album
            )

        def press(event):

            state["held"] = False

            state["timer"] = widget.after(
                HOLD_TIME_MS,
                hold,
            )

        def release(event):

            if state["timer"]:

                try:
                    widget.after_cancel(
                        state["timer"]
                    )
                except Exception:
                    pass

                state["timer"] = None

            if not state["held"]:

                self.play_album(
                    album
                )

        widget.bind(
            "<ButtonPress-1>",
            press,
        )

        widget.bind(
            "<ButtonRelease-1>",
            release,
        )

    # ========================================================
    # PLAY ALBUM
    # ========================================================

    def play_album(
        self,
        album,
    ):

        threading.Thread(
            target=self.album_play_worker,
            args=(album,),
            daemon=True,
        ).start()

    def album_play_worker(
        self,
        album,
    ):

        try:

            full = self.client.get_album(
                album["id"]
            )

            songs = full.get(
                "song",
                [],
            )

            if not songs:

                raise RuntimeError(
                    "Album contains no tracks"
                )

            self.after(
                0,
                lambda:
                self.replace_queue(
                    songs,
                    0,
                ),
            )

        except Exception as e:

            log(
                "ALBUM PLAY ERROR:",
                repr(e),
            )

            traceback.print_exc()

            self.after(
                0,
                lambda:
                messagebox.showerror(
                    "Navidrome",
                    str(e),
                ),
            )

    # ========================================================
    # QUEUE CONTROL
    # ========================================================

    def get_next_song_for_player(
        self,
        current_index,
    ):

        with self.queue_lock:

            next_index = (
                current_index + 1
            )

            if (
                next_index < 0
                or next_index
                >= len(self.queue)
            ):
                return None

            return (
                next_index,
                self.queue[
                    next_index
                ],
            )

    def replace_queue(
        self,
        songs,
        index=0,
    ):

        songs = list(
            songs
        )

        if not songs:
            return

        index = max(
            0,
            min(
                index,
                len(songs) - 1,
            ),
        )

        with self.queue_lock:

            self.queue = songs
            self.queue_index = index

            song = self.queue[
                index
            ]

        self.player.play(
            song,
            index=index,
            next_song_provider=(
                self.get_next_song_for_player
            ),
        )

        self.load_playing_cover(
            song
        )

        self.show_tab(
            "playing"
        )

    def previous_song(self):

        with self.queue_lock:

            if not self.queue:
                return

            if self.queue_index <= 0:
                return

            self.queue_index -= 1

            index = self.queue_index
            song = self.queue[index]

        self.player.play(
            song,
            index=index,
            next_song_provider=(
                self.get_next_song_for_player
            ),
        )

        self.load_playing_cover(
            song
        )

        self.render_playing()

    def next_song(self):

        with self.queue_lock:

            if not self.queue:
                return

            next_index = (
                self.queue_index + 1
            )

            if (
                next_index
                >= len(self.queue)
            ):
                return

            self.queue_index = (
                next_index
            )

            song = self.queue[
                next_index
            ]

        self.player.play(
            song,
            index=next_index,
            next_song_provider=(
                self.get_next_song_for_player
            ),
        )

        self.load_playing_cover(
            song
        )

        self.show_tab(
            "playing"
        )

    # ========================================================
    # PLAYER CALLBACKS
    # ========================================================

    def player_track_changed(
        self,
        index,
        song,
    ):

        def update():

            with self.queue_lock:

                if (
                    index < 0
                    or index
                    >= len(self.queue)
                ):
                    return

                self.queue_index = index

            self.load_playing_cover(
                song
            )

            if self.current_view == "playing":
                self.render_playing()

            elif self.current_view == "queue":
                self.render_queue()

        self.after(
            0,
            update,
        )

    def player_finished(self):

        def update():

            if self.current_view == "playing":
                self.render_playing()

            elif self.current_view == "queue":
                self.render_queue()

        self.after(
            0,
            update,
        )

    # ========================================================
    # PLAYING COVER
    # ========================================================

    def load_playing_cover(
        self,
        song,
    ):

        cover_id = song.get(
            "coverArt"
        )

        if not cover_id:
            self.playing_cover_image = None
            self.playing_cover_photo = None
            return

        # Check album cache first.
        image = self.cover_cache.get(
            cover_id
        )

        if image is not None:

            self.playing_cover_image = (
                image
            )

            self.playing_cover_cache.put(
                cover_id,
                image,
            )

            if self.current_view == "playing":
                self.render_playing()

            return

        # Then playing cache.
        image = (
            self.playing_cover_cache.get(
                cover_id
            )
        )

        if image is not None:

            self.playing_cover_image = (
                image
            )

            if self.current_view == "playing":
                self.render_playing()

            return

        if self.playing_cover_loading:
            return

        self.playing_cover_loading = True

        threading.Thread(
            target=self.playing_cover_worker,
            args=(
                song,
                cover_id,
            ),
            daemon=True,
        ).start()

    def playing_cover_worker(
        self,
        song,
        cover_id,
    ):

        try:

            data = self.client.get_cover(
                cover_id,
                COVER_SOURCE_MAX,
            )

            image = (
                self.playing_cover_cache.put(
                    cover_id,
                    data,
                )
            )

            if image is None:
                return

            def update():

                self.playing_cover_loading = (
                    False
                )

                current = (
                    self.player.current_song
                )

                if not current:
                    return

                if (
                    current.get("id")
                    != song.get("id")
                ):
                    return

                self.playing_cover_image = (
                    image
                )

                if self.current_view == "playing":
                    self.render_playing()

            self.after(
                0,
                update,
            )

        except Exception as e:

            log(
                "PLAYING COVER ERROR:",
                repr(e),
            )

            self.after(
                0,
                lambda:
                setattr(
                    self,
                    "playing_cover_loading",
                    False,
                ),
            )

    # ========================================================
    # PLAYING
    # ========================================================

    def render_playing(self):

        for child in (
            self.playing_frame.winfo_children()
        ):
            child.destroy()

        song = (
            self.player.current_song
        )

        if not song:

            tk.Label(
                self.playing_frame,
                text="Nothing playing",
                font=("Helvetica", 20),
                bg="white",
            ).pack(
                expand=True
            )

            return

        width = max(
            200,
            self.playing_frame.winfo_width(),
        )

        height = max(
            200,
            self.playing_frame.winfo_height(),
        )

        # Reserve space for:
        # title, artist, seek, controls, volume.
        reserved = 230

        max_cover_width = max(
            100,
            width - 40,
        )

        max_cover_height = max(
            100,
            height - reserved,
        )

        cover_id = song.get(
            "coverArt"
        )

        image = (
            self.playing_cover_image
        )

        if image is None and cover_id:

            image = (
                self.cover_cache.get(
                    cover_id
                )
            )

        if image is not None:

            display = fit_image(
                image,
                max_cover_width,
                max_cover_height,
            )

            photo = ImageTk.PhotoImage(
                display
            )

            self.playing_cover_photo = (
                photo
            )

            tk.Label(
                self.playing_frame,
                image=photo,
                bg="white",
            ).pack(
                pady=5,
                expand=False,
            )

        else:

            tk.Label(
                self.playing_frame,
                text="[ no cover ]",
                font=("Helvetica", 16),
                bg="white",
            ).pack(
                pady=30
            )

            self.load_playing_cover(
                song
            )

        title_font = max(
            14,
            min(
                22,
                width // 28,
            ),
        )

        artist_font = max(
            12,
            min(
                17,
                width // 36,
            ),
        )

        tk.Label(
            self.playing_frame,
            text=song.get(
                "title",
                "",
            ),
            font=(
                "Helvetica",
                title_font,
            ),
            bg="white",
            wraplength=max(
                200,
                width - 30,
            ),
        ).pack(
            padx=15,
            pady=3,
        )

        tk.Label(
            self.playing_frame,
            text=song.get(
                "artist",
                "",
            ),
            font=(
                "Helvetica",
                artist_font,
            ),
            bg="white",
            wraplength=max(
                200,
                width - 30,
            ),
        ).pack(
            pady=2
        )

        self.seek = tk.Scale(
            self.playing_frame,
            from_=0,
            to=max(
                self.player.duration,
                1,
            ),
            orient="horizontal",
            showvalue=False,
            length=max(
                200,
                width - 60,
            ),
            bg="white",
            highlightthickness=0,
        )

        self.seek.pack(
            fill="x",
            padx=30,
            pady=4,
        )

        controls = tk.Frame(
            self.playing_frame,
            bg="white",
        )

        controls.pack(
            pady=5
        )

        button_font = max(
            14,
            min(
                20,
                width // 30,
            ),
        )

        tk.Button(
            controls,
            text="|<<",
            font=(
                "Helvetica",
                button_font,
            ),
            width=5,
            command=self.previous_song,
        ).pack(
            side="left",
            padx=4,
        )

        self.pause_button = tk.Button(
            controls,
            text=(
                "PLAY"
                if self.player.is_paused()
                else "PAUSE"
            ),
            font=(
                "Helvetica",
                button_font,
            ),
            width=7,
            command=self.toggle_pause,
        )

        self.pause_button.pack(
            side="left",
            padx=4,
        )

        tk.Button(
            controls,
            text=">>|",
            font=(
                "Helvetica",
                button_font,
            ),
            width=5,
            command=self.next_song,
        ).pack(
            side="left",
            padx=4,
        )

        # ----------------------------------------------------
        # Responsive volume
        # ----------------------------------------------------

        volume_frame = tk.Frame(
            self.playing_frame,
            bg="white",
        )

        volume_frame.pack(
            fill="x",
            padx=30,
            pady=3,
        )

        tk.Label(
            volume_frame,
            text="VOL",
            font=("Helvetica", 13),
            bg="white",
        ).pack(
            side="left"
        )

        self.volume_scale = tk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient="horizontal",
            showvalue=True,
            resolution=1,
            bg="white",
            highlightthickness=0,
            command=self.set_volume,
        )

        self.volume_scale.set(
            int(
                self.player.volume
                * 100
            )
        )

        self.volume_scale.pack(
            side="left",
            fill="x",
            expand=True,
            padx=8,
        )

    def set_volume(
        self,
        value,
    ):

        try:
            value = int(
                float(value)
            )
        except ValueError:
            return

        self.player.set_volume(
            value
        )

    def toggle_pause(self):

        self.player.toggle_pause()

        if hasattr(
            self,
            "pause_button",
        ):

            self.pause_button.config(
                text=(
                    "PLAY"
                    if self.player.is_paused()
                    else "PAUSE"
                )
            )

    # ========================================================
    # TRACKLIST
    # ========================================================

    def open_tracklist(
        self,
        album,
    ):

        threading.Thread(
            target=self.tracklist_worker,
            args=(album,),
            daemon=True,
        ).start()

    def tracklist_worker(
        self,
        album,
    ):

        try:

            full = self.client.get_album(
                album["id"]
            )

            songs = full.get(
                "song",
                [],
            )

            self.after(
                0,
                lambda:
                self.show_tracklist(
                    full,
                    songs,
                ),
            )

        except Exception as e:

            log(
                "TRACKLIST ERROR:",
                repr(e),
            )

            self.after(
                0,
                lambda:
                messagebox.showerror(
                    "Navidrome",
                    str(e),
                ),
            )

    def show_tracklist(
        self,
        album,
        songs,
    ):

        self.destroy_temporary_views()

        self.playing_frame.pack_forget()
        self.albums_frame.pack_forget()
        self.queue_frame.pack_forget()

        self.current_view = "tracklist"

        self.tracklist_album = album
        self.tracklist_songs = list(
            songs
        )

        self.tracklist_frame = tk.Frame(
            self.content,
            bg="white",
        )

        self.tracklist_frame.pack(
            fill="both",
            expand=True,
        )

        header = tk.Frame(
            self.tracklist_frame,
            bg="white",
        )

        header.pack(
            fill="x",
        )

        tk.Button(
            header,
            text="< BACK",
            font=("Helvetica", 14),
            command=self.show_albums_again,
        ).pack(
            side="left",
            padx=5,
            pady=5,
        )

        tk.Label(
            header,
            text=album.get(
                "name",
                "",
            ),
            font=("Helvetica", 17),
            bg="white",
        ).pack(
            side="left",
            padx=10,
            pady=5,
        )

        canvas = tk.Canvas(
            self.tracklist_frame,
            bg="white",
            highlightthickness=0,
        )

        scrollbar = tk.Scrollbar(
            self.tracklist_frame,
            orient="vertical",
            command=canvas.yview,
        )

        canvas.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(
            side="right",
            fill="y",
        )

        canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        inner = tk.Frame(
            canvas,
            bg="white",
        )

        canvas.create_window(
            (0, 0),
            window=inner,
            anchor="nw",
        )

        inner.bind(
            "<Configure>",
            lambda e:
            canvas.configure(
                scrollregion=canvas.bbox(
                    "all"
                )
            ),
        )

        for i, song in enumerate(
            songs
        ):

            row = tk.Frame(
                inner,
                bg="white",
                bd=1,
                relief="solid",
            )

            row.pack(
                fill="x",
                padx=5,
                pady=2,
            )

            number = tk.Label(
                row,
                text=str(i + 1),
                width=4,
                font=("Helvetica", 12),
                bg="white",
            )

            number.pack(
                side="left"
            )

            label = tk.Label(
                row,
                text=(
                    song.get(
                        "title",
                        "",
                    )
                    + "\n"
                    + self.format_time(
                        song.get(
                            "duration",
                            0,
                        )
                        or 0
                    )
                ),
                anchor="w",
                justify="left",
                font=("Helvetica", 13),
                bg="white",
            )

            label.pack(
                side="left",
                fill="x",
                expand=True,
                padx=5,
                pady=8,
            )

            self.bind_track(
                row,
                label,
                number,
                song,
                songs,
                i,
            )

    def show_albums_again(self):

        self.destroy_temporary_views()

        self.show_tab(
            "albums"
        )

    # ========================================================
    # TRACK GESTURE
    # ========================================================

    def bind_track(
        self,
        row,
        label,
        number,
        song,
        album_songs,
        index,
    ):

        state = {
            "timer": None,
            "held": False,
        }

        def hold():

            state["timer"] = None
            state["held"] = True

            self.track_options(
                song,
                album_songs,
                index,
            )

        def press(event):

            state["held"] = False

            state["timer"] = row.after(
                HOLD_TIME_MS,
                hold,
            )

        def release(event):

            if state["timer"]:

                try:
                    row.after_cancel(
                        state["timer"]
                    )
                except Exception:
                    pass

                state["timer"] = None

            if not state["held"]:

                self.replace_queue(
                    album_songs,
                    index,
                )

        for widget in (
            row,
            label,
            number,
        ):

            widget.bind(
                "<ButtonPress-1>",
                press,
            )

            widget.bind(
                "<ButtonRelease-1>",
                release,
            )

    # ========================================================
    # TRACK OPTIONS
    # ========================================================

    def track_options(
        self,
        song,
        album_songs,
        index,
    ):

        self.tracklist_songs = list(
            album_songs
        )

        self.options_song = song

        if self.tracklist_frame is not None:

            try:
                self.tracklist_frame.destroy()
            except Exception:
                pass

            self.tracklist_frame = None

        self.options_frame = tk.Frame(
            self.content,
            bg="white",
        )

        self.options_frame.pack(
            fill="both",
            expand=True,
        )

        tk.Label(
            self.options_frame,
            text=song.get(
                "title",
                "",
            ),
            font=("Helvetica", 18),
            bg="white",
            wraplength=450,
        ).pack(
            pady=30,
            padx=20,
        )

        tk.Button(
            self.options_frame,
            text="PLAY AFTER CURRENT",
            font=("Helvetica", 15),
            width=25,
            height=2,
            command=lambda:
            self.option_play_after(
                song
            ),
        ).pack(
            pady=8,
        )

        tk.Button(
            self.options_frame,
            text="APPEND TO QUEUE",
            font=("Helvetica", 15),
            width=25,
            height=2,
            command=lambda:
            self.option_append(
                song
            ),
        ).pack(
            pady=8,
        )

        tk.Button(
            self.options_frame,
            text="< BACK",
            font=("Helvetica", 15),
            width=25,
            height=2,
            command=self.close_options,
        ).pack(
            pady=25,
        )

    def option_play_after(
        self,
        song,
    ):

        self.play_after_current(
            song
        )

        self.close_options_to_queue()

    def option_append(
        self,
        song,
    ):

        self.append_queue(
            song
        )

        self.close_options_to_queue()

    def close_options(self):

        if self.options_frame is not None:

            try:
                self.options_frame.destroy()
            except Exception:
                pass

            self.options_frame = None

        self.show_tracklist(
            self.tracklist_album,
            self.tracklist_songs,
        )

    def close_options_to_queue(self):

        if self.options_frame is not None:

            try:
                self.options_frame.destroy()
            except Exception:
                pass

            self.options_frame = None

        self.show_tab(
            "queue"
        )

    # ========================================================
    # QUEUE MUTATION
    # ========================================================

    def append_queue(
        self,
        song,
    ):

        with self.queue_lock:

            self.queue.append(
                song
            )

        if self.current_view == "queue":
            self.render_queue()

    def play_after_current(
        self,
        song,
    ):

        with self.queue_lock:

            if not self.queue:

                self.queue = [song]
                self.queue_index = 0

                start_now = True

            else:

                position = (
                    self.queue_index + 1
                )

                self.queue.insert(
                    position,
                    song,
                )

                start_now = False

        if start_now:

            self.player.play(
                song,
                index=0,
                next_song_provider=(
                    self.get_next_song_for_player
                ),
            )

            self.load_playing_cover(
                song
            )

            self.show_tab(
                "playing"
            )

        elif self.current_view == "queue":

            self.render_queue()

    # ========================================================
    # QUEUE
    # ========================================================

    def render_queue(self):

        for child in (
            self.queue_frame.winfo_children()
        ):
            child.destroy()

        width = max(
            200,
            self.queue_frame.winfo_width(),
        )

        height = max(
            200,
            self.queue_frame.winfo_height(),
        )

        # Header scales with the window rather than fixing
        # the queue to a hard-coded content height.
        header_height = max(
            40,
            min(
                65,
                height // 10,
            ),
        )

        header = tk.Frame(
            self.queue_frame,
            bg="white",
            height=header_height,
        )

        header.pack(
            fill="x",
            side="top",
        )

        header.pack_propagate(
            False
        )

        tk.Label(
            header,
            text="QUEUE",
            font=(
                "Helvetica",
                max(
                    16,
                    min(
                        22,
                        width // 28,
                    ),
                ),
            ),
            bg="white",
        ).pack(
            expand=True
        )

        with self.queue_lock:

            songs = list(
                self.queue
            )

            current_index = (
                self.queue_index
            )

        if not songs:

            tk.Label(
                self.queue_frame,
                text="Queue empty",
                font=("Helvetica", 16),
                bg="white",
            ).pack(
                fill="both",
                expand=True,
            )

            return

        # This canvas fills ALL remaining window space.
        canvas = tk.Canvas(
            self.queue_frame,
            bg="white",
            highlightthickness=0,
        )

        scrollbar = tk.Scrollbar(
            self.queue_frame,
            orient="vertical",
            command=canvas.yview,
        )

        canvas.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(
            side="right",
            fill="y",
        )

        canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        inner = tk.Frame(
            canvas,
            bg="white",
        )

        inner_window = canvas.create_window(
            (0, 0),
            window=inner,
            anchor="nw",
        )

        def resize_inner(event):

            canvas.itemconfigure(
                inner_window,
                width=event.width,
            )

        canvas.bind(
            "<Configure>",
            resize_inner,
        )

        inner.bind(
            "<Configure>",
            lambda e:
            canvas.configure(
                scrollregion=canvas.bbox(
                    "all"
                )
            ),
        )

        self.queue_photos = []

        # Queue cover size is derived from the actual window.
        queue_cover_size = max(
            40,
            min(
                110,
                int(
                    min(
                        width * 0.16,
                        height * 0.10,
                    )
                ),
            ),
        )

        row_height = max(
            60,
            queue_cover_size + 12,
        )

        text_font = max(
            11,
            min(
                17,
                width // 45,
            ),
        )

        for i, song in enumerate(
            songs
        ):

            bg = (
                "#dddddd"
                if i == current_index
                else "white"
            )

            row = tk.Frame(
                inner,
                bg=bg,
                height=row_height,
            )

            row.pack(
                fill="x",
                padx=5,
                pady=2,
            )

            row.pack_propagate(
                False
            )

            cover_id = song.get(
                "coverArt"
            )

            image = (
                self.queue_cover_cache.get(
                    cover_id
                )
            )

            if image is not None:

                display = fit_image(
                    image,
                    queue_cover_size,
                    queue_cover_size,
                )

                photo = ImageTk.PhotoImage(
                    display
                )

                self.queue_photos.append(
                    photo
                )

                cover_widget = tk.Label(
                    row,
                    image=photo,
                    bg=bg,
                )

            else:

                cover_widget = tk.Label(
                    row,
                    text="",
                    width=max(
                        4,
                        queue_cover_size // 8,
                    ),
                    bg=bg,
                )

                self.request_queue_cover(
                    cover_id
                )

            cover_widget.pack(
                side="left",
                padx=5,
            )

            label = tk.Label(
                row,
                text=(
                    song.get(
                        "title",
                        "",
                    )
                    + "\n"
                    + song.get(
                        "artist",
                        "",
                    )
                ),
                anchor="w",
                justify="left",
                font=(
                    "Helvetica",
                    text_font,
                ),
                bg=bg,
            )

            label.pack(
                side="left",
                fill="both",
                expand=True,
                padx=8,
            )

            self.bind_queue_click(
                row,
                cover_widget,
                label,
                i,
            )

    def bind_queue_click(
        self,
        row,
        cover,
        label,
        index,
    ):

        def click(event=None):

            with self.queue_lock:

                if (
                    index < 0
                    or index
                    >= len(self.queue)
                ):
                    return

                self.queue_index = index

                song = self.queue[
                    index
                ]

            self.player.play(
                song,
                index=index,
                next_song_provider=(
                    self.get_next_song_for_player
                ),
            )

            self.load_playing_cover(
                song
            )

            self.show_tab(
                "playing"
            )

        for widget in (
            row,
            cover,
            label,
        ):

            widget.bind(
                "<Button-1>",
                click,
            )

    # ========================================================
    # QUEUE COVER
    # ========================================================

    def request_queue_cover(
        self,
        cover_id,
    ):

        if not cover_id:
            return

        if (
            self.queue_cover_cache.get(
                cover_id
            )
            is not None
        ):
            return

        if (
            cover_id
            in self.queue_cover_loading
        ):
            return

        self.queue_cover_loading.add(
            cover_id
        )

        threading.Thread(
            target=self.queue_cover_worker,
            args=(cover_id,),
            daemon=True,
        ).start()

    def queue_cover_worker(
        self,
        cover_id,
    ):

        try:

            data = self.client.get_cover(
                cover_id,
                COVER_SOURCE_MAX,
            )

            self.queue_cover_cache.put(
                cover_id,
                data,
            )

        except Exception as e:

            log(
                "QUEUE COVER ERROR:",
                repr(e),
            )

        finally:

            self.queue_cover_loading.discard(
                cover_id
            )

            self.after(
                0,
                lambda:
                self.render_queue_if_visible(),
            )

    def render_queue_if_visible(self):

        if self.current_view == "queue":
            self.render_queue()

    # ========================================================
    # UTILITIES
    # ========================================================

    def format_time(
        self,
        seconds,
    ):

        seconds = int(
            max(
                0,
                seconds,
            )
        )

        return (
            str(seconds // 60)
            + ":"
            + f"{seconds % 60:02d}"
        )

    def player_error(
        self,
        error,
    ):

        log(
            "PLAYER ERROR:",
            error,
        )

        self.after(
            0,
            lambda:
            messagebox.showerror(
                "Playback error",
                error,
            ),
        )

    # ========================================================
    # UI TIMER
    # ========================================================

    def update_ui(self):

        if (
            self.current_view == "playing"
            and hasattr(
                self,
                "seek",
            )
            and self.player.current_song
        ):

            try:

                self.seek.set(
                    self.player.position
                )

            except Exception:
                pass

        self.after(
            1000,
            self.update_ui,
        )

    # ========================================================
    # SHUTDOWN
    # ========================================================

    def destroy(self):

        log(
            "Shutting down"
        )

        try:
            self.player.stop()
        except Exception:
            pass

        super().destroy()


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "================================"
    )

    log(
        "Kindle Navidrome starting"
    )

    log(
        "Navidrome:",
        NAVIDROME_URL,
    )

    log(
        "ALSA:",
        ALSA_DEVICE,
    )

    log(
        "================================"
    )

    try:

        app = App()

        app.mainloop()

    except Exception:

        traceback.print_exc()

        raise


if __name__ == "__main__":
    main()

