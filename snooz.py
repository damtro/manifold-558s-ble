"""Decode the btsnooz summary of an Android bug report and list ATT (GATT) traffic.

Usage: python snooz.py snooz.b64 [start HH:MM:SS] [end HH:MM:SS]
snooz.b64 is the base64 block of the BTSNOOP_LOG_SUMMARY section of the bug report.
Note: on recent Android versions this summary keeps only HCI commands and events,
without ACL data. Use a full btsnoop log (btsnoop.py) to see the protocol itself.
"""
import base64, struct, sys, zlib, datetime as dt
from collections import Counter

raw = base64.b64decode(open(sys.argv[1]).read().replace("\n", "").replace("\r", ""))
version, last_ms = struct.unpack_from("<bQ", raw)
data = zlib.decompress(raw[9:])
print(f"version={version} last={dt.datetime.fromtimestamp(last_ms/1e6)} bytes={len(data)}")

hdr = "<HIb" if version == 1 else "<HHIb"
hsz = struct.calcsize(hdr)
recs = []
off = 0
while off < len(data):
    if version == 1:
        length, delta, typ = struct.unpack_from(hdr, data, off)
        plen = length
    else:
        length, plen, delta, typ = struct.unpack_from(hdr, data, off)
    pkt = data[off + hsz: off + hsz + length - 1]
    recs.append([delta, typ & 0xff, pkt, plen])
    off += hsz + length - 1

# timestamps: the last packet is last_ms, walk back with the deltas
t = last_ms
for r in reversed(recs):
    r.append(t)
    t -= r[0]

TYPES = {0x10: "EVT<", 0x11: "ACL<", 0x12: "SCO<", 0x20: "CMD>", 0x21: "ACL>", 0x22: "SCO>"}
print("types:", Counter(TYPES.get(r[1], hex(r[1])) for r in recs))
start = sys.argv[2] if len(sys.argv) > 2 else "00:00:00"
end = sys.argv[3] if len(sys.argv) > 3 else "23:59:59"

# LE connections: LE Connection Complete event (0x3E, sub-event 0x01 / 0x0A) -> handle + address
for delta, typ, pkt, plen, ts in recs:
    h = dt.datetime.fromtimestamp(ts / 1e6).strftime("%H:%M:%S.%f")[:-3]
    if not (start <= h[:8] <= end):
        continue
    if typ == 0x10 and len(pkt) > 4 and pkt[0] == 0x3E and pkt[2] in (0x01, 0x0A):
        handle = struct.unpack_from("<H", pkt, 4)[0] & 0x0FFF
        addr = ":".join(f"{b:02X}" for b in reversed(pkt[8:14]))
        print(f"{h} LE CONNECT handle={handle:#x} addr={addr} status={pkt[3]}")
    if typ == 0x10 and len(pkt) > 3 and pkt[0] == 0x05:
        print(f"{h} DISCONNECT handle={struct.unpack_from('<H', pkt, 3)[0]:#x}")
    if typ in (0x11, 0x21) and len(pkt) >= 8:
        handle = struct.unpack_from("<H", pkt, 0)[0] & 0x0FFF
        cid = struct.unpack_from("<H", pkt, 6)[0]
        if cid != 0x0004:
            continue
        att = pkt[8:]
        if not att:
            continue
        op = att[0]
        way = "<" if typ == 0x11 else ">"
        truncated = "" if plen == len(pkt) else f" (truncated {len(pkt)}/{plen})"
        print(f"{h} {way} h={handle:#x} ATT op={op:#04x} {att[1:].hex()}{truncated}")
