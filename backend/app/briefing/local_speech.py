"""Synchronous eSpeak NG retrieval in an isolated process (library has global state)."""

import ctypes as c
import sys

from espeakng_loader import get_data_path, get_library_path


def main():
    from pathlib import Path

    lib = c.CDLL(str(get_library_path()))
    data = Path(get_data_path())
    path = data.parent if data.name == "espeak-ng-data" else data
    lib.espeak_Initialize.argtypes = [c.c_int, c.c_int, c.c_char_p, c.c_int]
    sample_rate = lib.espeak_Initialize(2, 0, str(path).encode(), 0)
    if sample_rate != 22050:
        raise RuntimeError("Unsupported speech sample rate")
    buffer = bytearray()
    callback_type = c.CFUNCTYPE(c.c_int, c.POINTER(c.c_short), c.c_int, c.c_void_p)

    @callback_type
    def receive(pcm, frames, _events):
        if frames > 0 and pcm:
            buffer.extend(c.string_at(pcm, frames * 2))
        return 0

    lib.espeak_SetSynthCallback.argtypes = [callback_type]
    lib.espeak_SetSynthCallback(receive)
    if lib.espeak_SetVoiceByName(sys.argv[1].encode()) != 0:
        raise RuntimeError("Offline speech language unavailable")
    lib.espeak_SetParameter(1, int(sys.argv[2]), 0)
    lib.espeak_SetParameter(3, int(sys.argv[3]), 0)
    data = sys.stdin.buffer.read() + b"\0"
    lib.espeak_Synth.argtypes = [
        c.c_char_p,
        c.c_size_t,
        c.c_uint,
        c.c_int,
        c.c_uint,
        c.c_uint,
        c.c_void_p,
        c.c_void_p,
    ]
    if lib.espeak_Synth(data, len(data), 0, 1, 0, 1, None, None) != 0 or not buffer:
        raise RuntimeError("Speech rendering produced no samples")
    lib.espeak_Terminate()
    sys.stdout.buffer.write(buffer)


if __name__ == "__main__":
    main()
