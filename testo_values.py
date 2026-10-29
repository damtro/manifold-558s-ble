"""Decode testo 558s "Measurement.Values" frames from the output of btsnoop.py.

Usage: python btsnoop.py capture.log > att.txt ; python testo_values.py att.txt [offset_hours]
Frame: header 10 80 + length(u32) + CRC(u16) + name length(u32) + name, then channel count (u32)
and, for each channel: id (u32), float32 value, status code (u16); final CRC (u16).
offset_hours corrects the clock of the capture (some phones log in another time zone).
"""
import struct, sys, datetime as dt

CHANNELS = {0x26: "BattRemovable", 0x27: "BattInternal", 0x01: "LP", 0x02: "HP", 0x03: "T1", 0x04: "T2",
            0x0F: "Tevap", 0x10: "Tcond", 0x11: "SH", 0x13: "SC", 0x0B: "Patm", 0x31: "BattProbe"}
NAME = b"Measurement.Values"
OFFSET = dt.timedelta(hours=float(sys.argv[2]) if len(sys.argv) > 2 else 0)

for l in open(sys.argv[1]):
    if "NOTIF" not in l:
        continue
    b = bytes.fromhex(l.split()[-1])
    i = b.find(NAME)
    if i < 0:
        continue
    p = i + len(NAME)
    n = struct.unpack_from("<I", b, p)[0]
    p += 4
    v = {}
    for _ in range(n):
        cid, val, code = struct.unpack_from("<IfH", b, p)
        p += 10
        v[CHANNELS.get(cid, hex(cid))] = (val, code)
    h = (dt.datetime.strptime(l[:12], "%H:%M:%S.%f") + OFFSET).strftime("%H:%M:%S")
    print(h, " ".join(f"{k}={x:.2f}" + ("" if c in (0x0100, 0x0200, 0x0000, 0xFD00) else f"[{c:#06x}]")
                      for k, (x, c) in v.items()))
