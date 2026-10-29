"""Live readout of a testo 558s digital manifold over Bluetooth LE, without the vendor app.

Usage: python testo558.py AA:BB:CC:DD:EE:FF [--duration 20] [--debug]

Commands are written to characteristic fff1, replies arrive as notifications on fff2 (service fff0).
Frame = cmd(1) seq(1) length(u32 LE) CRC16/MODBUS of the 6 header bytes, then the payload
followed by its own CRC16/MODBUS (the length counts the payload CRC). See README.md.
"""
import argparse, asyncio, struct, sys, time
from bleak import BleakClient, BleakScanner

CHANNELS = {0x01: "LP", 0x02: "HP", 0x03: "T1", 0x04: "T2", 0x0F: "Tevap", 0x10: "Tcond", 0x11: "SH",
            0x13: "SC", 0x0B: "Patm", 0x26: "BattRemovable", 0x27: "BattInternal", 0x31: "BattProbe"}
NO_VALUE = 0x0800

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("address", help="Bluetooth address of the 558s (see scan.py)")
parser.add_argument("--duration", type=float, default=20, help="seconds to listen (default 20)")
parser.add_argument("--debug", action="store_true", help="print raw frames")
args = parser.parse_args()


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return struct.pack("<H", c)


def frame(cmd, seq, payload=b""):
    if payload:
        payload += crc16(payload)
    header = bytes([cmd, seq]) + struct.pack("<I", len(payload))
    return header + crc16(header) + payload


def string(s):
    return struct.pack("<I", len(s)) + s.encode()


buffer = bytearray()


def decode(data):
    """Reassemble notifications and print complete frames."""
    if args.debug:
        print("  fff2", data.hex()[:80], flush=True)
    buffer.extend(data)
    while len(buffer) >= 8:
        ln = struct.unpack_from("<I", buffer, 2)[0]
        if len(buffer) < 8 + ln:
            return
        t = bytes(buffer[:8 + ln])
        del buffer[:8 + ln]
        cmd = t[0]
        body = t[8:-2] if ln else b""
        if len(body) >= 4:
            n = struct.unpack_from("<I", body)[0]
            name = body[4:4 + n].decode(errors="replace")
            rest = body[4 + n:]
        else:
            name, rest = "", body
        if name == "Measurement.Values":
            k = struct.unpack_from("<I", rest)[0]
            vals = []
            for i in range(k):
                cid, v, code = struct.unpack_from("<IfH", rest, 4 + 10 * i)
                if code != NO_VALUE:
                    vals.append(f"{CHANNELS.get(cid, hex(cid))}={v:.2f}")
            print(time.strftime("%H:%M:%S"), " ".join(vals), flush=True)
        elif cmd == 0x07 and len(body) >= 4:
            n = struct.unpack_from("<I", body)[0]
            print("  reply:", body[4:4 + n].decode(errors="replace"), flush=True)
        elif name and name not in ("Errorstate", "DataSync", "Logging.RemainingRunTime"):
            print(f"  [{cmd:#04x}] {name} {rest.hex()}", flush=True)


async def main():
    dev = await BleakScanner.find_device_by_address(args.address, timeout=20)
    if not dev:
        sys.exit(f"{args.address} not found: is the 558s on, and disconnected from the phone app?")
    print("found:", dev.name)
    async with BleakClient(dev, timeout=20) as c:
        wr = nt = None
        for s in c.services:
            for ch in s.characteristics:
                print(f"  {s.uuid[:8]} {ch.uuid[:8]} h={ch.handle:#06x} {ch.properties}")
                # look up by UUID: handle numbers differ between OS backends
                if ch.uuid.startswith("0000fff1"):
                    wr = ch
                if ch.uuid.startswith("0000fff2"):
                    nt = ch
        if not (wr and nt):
            sys.exit("characteristics fff1 / fff2 not found, see the list above")
        await c.start_notify(nt, lambda _, d: decode(d))
        for t in (frame(0x56, 0x00, b"\x02"),
                  frame(0x20, 0x01),
                  frame(0x04, 0x02, string("FirmwareVersion")),
                  frame(0x04, 0x03, string("CurrentRefrigerant")),
                  frame(0x11, 0x04)):  # subscribe: the device then pushes Measurement.Values
            if args.debug:
                print("  send", t.hex(), flush=True)
            await c.write_gatt_char(wr, t, response=True)
            await asyncio.sleep(0.3)
        await asyncio.sleep(args.duration)


asyncio.run(main())
