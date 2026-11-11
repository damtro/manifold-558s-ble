"""Shared Testo framing and BLE transport; probe schemas belong in drivers."""

import asyncio
import struct

WRITE_UUID = '0000fff1-0000-1000-8000-00805f9b34fb'
NOTIFY_UUID = '0000fff2-0000-1000-8000-00805f9b34fb'
MAX_LENGTH = 1024 * 1024  # Resource limit, not a protocol field width.


def crc16(data):
    """Return the little-endian CRC-16/MODBUS checksum."""
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0xA001 if value & 1 else value >> 1
    return struct.pack('<H', value)


def build_frame(command, sequence, payload=b''):
    body = payload + crc16(payload) if payload else b''
    header = bytes((command, sequence)) + struct.pack('<I', len(body))
    return header + crc16(header) + body


COMMANDS = (build_frame(0x56, 0, b'\x02'), build_frame(0x20, 1), build_frame(0x11, 4))


class FrameDecoder:
    """Incrementally validate all frame types, retaining incomplete frames.

    Invalid headers or payloads resynchronize one byte at a time. A valid
    header is trusted until its declared body arrives. Lengths are uint32;
    the configurable bound prevents unbounded retention of incomplete bodies.
    """

    def __init__(self, max_length=MAX_LENGTH):
        if not 2 <= max_length <= 0xffffffff:
            raise ValueError('max_length must be between 2 and 4294967295')
        self.max_length = max_length
        self.buffer = bytearray()
        self.rejected_bytes = 0

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        offset = 0
        while len(self.buffer) - offset >= 8:
            header = self.buffer[offset:offset + 8]
            length = struct.unpack_from('<I', header, 2)[0]
            if (length == 1 or length > self.max_length
                    or crc16(header[:6]) != header[6:]):
                offset += 1
                self.rejected_bytes += 1
                continue
            total = 8 + length
            if len(self.buffer) - offset < total:
                break
            frame = bytes(self.buffer[offset:offset + total])
            if length and crc16(frame[8:-2]) != frame[-2:]:
                offset += 1
                self.rejected_bytes += 1
                continue
            frames.append(frame)
            offset += total
        del self.buffer[:offset]
        return frames


async def stream_frames(address, on_frame, *, duration=0, debug=None,
                        commands=COMMANDS, client_factory=None, startup_delay=1):
    """Subscribe before startup; surface disconnects and callback failures.

    A future probe driver can reuse transport with its own startup commands and
    frame callback. This does not establish compatibility with other probes.
    """
    if client_factory is None:
        from bleak import BleakClient
        client_factory = BleakClient
    decoder = FrameDecoder()
    loop = asyncio.get_running_loop()
    stopped = loop.create_future()

    def fail(error):
        if not stopped.done():
            stopped.set_result(error)

    def notify(sender, data):
        if stopped.done():
            return
        try:
            if debug:
                debug(f'RX {bytes(data).hex(" ")}')
            for frame in decoder.feed(data):
                on_frame(frame)
        except Exception as error:
            fail(error)

    async with client_factory(
        address, timeout=20,
        disconnected_callback=lambda _: fail(ConnectionError('Probe disconnected')),
    ) as client:
        await client.start_notify(NOTIFY_UUID, notify)
        for command in commands:
            if stopped.done():
                raise stopped.result()
            if debug:
                debug(f'TX {command.hex()}')
            await client.write_gatt_char(WRITE_UUID, command, response=True)
            if startup_delay:
                try:
                    error = await asyncio.wait_for(asyncio.shield(stopped), startup_delay)
                except asyncio.TimeoutError:
                    pass
                else:
                    raise error
        if not client.is_connected:
            raise ConnectionError('Probe disconnected during initialization')
        try:
            if duration:
                error = await asyncio.wait_for(asyncio.shield(stopped), duration)
            else:
                error = await stopped
        except asyncio.TimeoutError:
            pass
        else:
            raise error
    return decoder.rejected_bytes
