"""Read direct Testo 115i BLE notifications using the observed startup sequence.

Usage: python testo115.py ADDRESS [--duration 60] [--debug] [--verify-crc]
The property-value layout is based on one user's working 115i prototype.
CRC verification is opt-in pending validation against real 115i captures.
"""

import argparse
import asyncio
import math
import struct
import sys
from datetime import datetime


WRITE_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
COMMANDS = (
    bytes.fromhex("5600030000000c69023e81"),
    bytes.fromhex("2001000000003abb"),
    bytes.fromhex("110400000000f29a"),
)
MAX_LENGTH = 512  # Conservative bound retained from the working prototype.


def log(message):
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" | {message}", flush=True)


def crc16(data):
    """CRC-16/MODBUS, as documented by the upstream 558s project."""
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0xA001 if value & 1 else value >> 1
    return struct.pack("<H", value)


def measurements(frame):
    """Yield observed named Float32 values; no status-field interpretation yet."""
    payload = frame[8:-2]
    for name in ("LineTemperature", "BatteryLevel"):
        marker = name.encode("ascii")
        position = payload.find(marker)
        if position < 0:
            continue
        start = position + len(marker)
        if len(payload) < start + 4:
            continue
        value = struct.unpack_from("<f", payload, start)[0]
        if math.isfinite(value):
            yield name, value


class FrameDecoder:
    """Reassemble observed 10 80 pushes, including split and coalesced frames."""

    def __init__(self, verify_crc=False):
        self.buffer = bytearray()
        self.verify_crc = verify_crc

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 8:
            if self.buffer[:2] != b"\x10\x80":
                del self.buffer[0]
                continue
            length = struct.unpack_from("<I", self.buffer, 2)[0]
            if not 2 <= length <= MAX_LENGTH:
                del self.buffer[0]
                continue
            if self.verify_crc and crc16(self.buffer[:6]) != self.buffer[6:8]:
                del self.buffer[0]
                continue
            total = 8 + length
            if len(self.buffer) < total:
                break
            frame = bytes(self.buffer[:total])
            if self.verify_crc and crc16(frame[8:-2]) != frame[-2:]:
                del self.buffer[0]
                continue
            del self.buffer[:total]
            frames.append(frame)
        return frames


async def stream(args):
    from bleak import BleakClient

    decoder = FrameDecoder(args.verify_crc)
    disconnected = asyncio.Event()

    def notify(sender, data):
        if args.debug:
            log(f"RX {sender.uuid} | {bytes(data).hex(' ')}")
        for frame in decoder.feed(data):
            for name, value in measurements(frame):
                if name == "LineTemperature":
                    log(f"Temperature: {value:.2f} °C / {value * 9 / 5 + 32:.2f} °F")
                else:
                    log(f"Battery: {value:.0f}%")

    log(f"Connecting to Testo 115i: {args.address}")
    async with BleakClient(
        args.address, timeout=20,
        disconnected_callback=lambda _: disconnected.set(),
    ) as client:
        log(f"Connected: {client.is_connected}")
        await client.start_notify(NOTIFY_UUID, notify)
        for command in COMMANDS:
            if args.debug:
                log(f"TX {command.hex()}")
            await client.write_gatt_char(WRITE_UUID, command, response=True)
            await asyncio.sleep(1)
        if disconnected.is_set() or not client.is_connected:
            raise ConnectionError("Probe disconnected during initialization")
        log("Listening for measurements. Press Ctrl+C to stop.")
        if args.duration == 0:
            await disconnected.wait()
        else:
            try:
                await asyncio.wait_for(disconnected.wait(), timeout=args.duration)
            except asyncio.TimeoutError:
                pass
        if disconnected.is_set():
            raise ConnectionError("Probe disconnected")


def nonnegative_seconds(text):
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("duration must be a finite number >= 0")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("address", help="BLE address, or macOS device UUID (see scan.py)")
    parser.add_argument("--duration", type=nonnegative_seconds, default=0,
                        help="seconds after startup; 0 listens until Ctrl+C (default)")
    parser.add_argument("--debug", action="store_true", help="print raw RX notifications and TX commands")
    parser.add_argument("--verify-crc", action="store_true",
                        help="require upstream MODBUS CRCs (not yet verified on 115i captures)")
    args = parser.parse_args()
    try:
        asyncio.run(stream(args))
    except KeyboardInterrupt:
        log("Stopped.")
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
