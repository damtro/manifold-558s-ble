"""Read a btsnoop capture (Android HCI snoop log, .log or Samsung .cfa) and list ATT traffic per LE connection.

Usage: python btsnoop.py capture.log [address_filter]
Output: one line per ATT packet: time, direction (> phone to device, < device to phone),
connection, opcode, ATT handle, hex value. Characteristic UUIDs are shown when the
discovery was captured.
"""
import struct, sys, datetime as dt

EPOCH_DELTA = 0x00DCDDB30F2F8000  # microseconds between year 0 and 1970

f = open(sys.argv[1], "rb").read()
flt = sys.argv[2].upper() if len(sys.argv) > 2 else None
assert f[:8] == b"btsnoop\0", f[:8]
off = 16
conn = {}        # HCI handle -> address
uuids = {}       # (address, ATT value handle) -> uuid
frag = {}        # HCI handle -> [expected length, cid, data]
OPS = {0x01: "ERR", 0x02: "MTUreq", 0x03: "MTUrsp", 0x08: "RdByTypeReq", 0x09: "RdByTypeRsp", 0x0A: "RdReq",
       0x0B: "RdRsp", 0x10: "RdGrpReq", 0x11: "RdGrpRsp", 0x04: "FindInfoReq", 0x05: "FindInfoRsp",
       0x12: "WrReq", 0x13: "WrRsp", 0x52: "WrCmd", 0x1B: "NOTIF", 0x1D: "IND", 0x1E: "Conf"}


def uuid_str(b):
    return f"{struct.unpack('<H', b)[0]:04x}" if len(b) == 2 else b[::-1].hex()


def att(ts, way, h, pdu):
    addr = conn.get(h, "?")
    if flt and addr != flt:
        return
    op = pdu[0]
    name = OPS.get(op, f"op{op:#04x}")
    # characteristic discovery: declaration = properties(1) value handle(2) uuid
    if op == 0x09 and len(pdu) > 2:
        ln = pdu[1]
        for i in range(2, len(pdu) - ln + 1, ln):
            e = pdu[i:i + ln]
            if ln in (7, 21):
                vh = struct.unpack_from("<H", e, 3)[0]
                uuids[(addr, vh)] = uuid_str(e[5:])
                uuids[(addr, vh + 1)] = uuid_str(e[5:]) + "/cccd"
    if op in (0x12, 0x52, 0x1B, 0x1D, 0x0A, 0x0B) and len(pdu) >= 3 or op in (0x12, 0x52, 0x1B, 0x1D, 0x0A):
        ah = struct.unpack_from("<H", pdu, 1)[0] if op != 0x0B else None
        val = pdu[3:] if op != 0x0B else pdu[1:]
        u = uuids.get((addr, ah), "") if ah is not None else ""
        hs = f"h={ah:#06x}" if ah is not None else "      "
        print(f"{ts} {way} {addr[-5:]} {name:7} {hs} {u[:8]:13} {val.hex()}")
    else:
        print(f"{ts} {way} {addr[-5:]} {name:7} {pdu[1:].hex()}")


while off + 24 <= len(f):
    olen, ilen, flags, drops, t = struct.unpack_from(">IIIIq", f, off)
    data = f[off + 24: off + 24 + ilen]
    off += 24 + ilen
    ts = dt.datetime.fromtimestamp((t - EPOCH_DELTA) / 1e6).strftime("%H:%M:%S.%f")[:-3]
    received = flags & 1
    typ = data[0]
    p = data[1:]
    if typ == 0x04 and len(p) > 2:  # HCI event
        if p[0] == 0x3E and p[2] in (0x01, 0x0A) and p[3] == 0:
            h = struct.unpack_from("<H", p, 4)[0] & 0xFFF
            conn[h] = ":".join(f"{b:02X}" for b in reversed(p[8:14]))
            if not flt or conn[h] == flt:
                print(f"{ts} CONNECT h={h:#x} {conn[h]}")
        elif p[0] == 0x05:
            h = struct.unpack_from("<H", p, 3)[0]
            if not flt or conn.get(h) == flt:
                print(f"{ts} DISCONNECT h={h:#x} {conn.get(h)} reason={p[5]:#x}")
    elif typ == 0x02 and len(p) >= 4:  # ACL
        hw, ln = struct.unpack_from("<HH", p)
        h, pb = hw & 0xFFF, (hw >> 12) & 0x3
        payload = p[4:4 + ln]
        if pb in (0x0, 0x2):  # start of an L2CAP frame
            if len(payload) < 4:
                continue
            l2len, cid = struct.unpack_from("<HH", payload)
            frag[h] = [l2len, cid, bytearray(payload[4:])]
        elif h in frag:
            frag[h][2] += payload
        else:
            continue
        l2len, cid, buf = frag[h]
        if len(buf) >= l2len:
            del frag[h]
            if cid == 0x0004 and buf:
                att(ts, "<" if received else ">", h, bytes(buf[:l2len]))
