"""List the GATT services of a BLE device, read what is readable, and print notifications.

Usage: python gatt.py AA:BB:CC:DD:EE:FF [duration_s]
Read-only: this script never writes to the device.
"""
import asyncio, sys, time
from bleak import BleakClient

ADDR = sys.argv[1]
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 20


async def main():
    async with BleakClient(ADDR, timeout=20) as c:
        print("connected", c.is_connected)
        notifiable = []
        for s in c.services:
            print(f"SERVICE {s.uuid} {s.description}")
            for ch in s.characteristics:
                val = ""
                if "read" in ch.properties:
                    try:
                        b = await c.read_gatt_char(ch)
                        val = f" = {b.hex()} {b!r}"
                    except Exception as e:
                        val = f" (read: {e})"
                print(f"  CHAR {ch.uuid} h={ch.handle} {ch.properties}{val}")
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notifiable.append(ch)
        t0 = time.time()

        def cb(ch):
            return lambda _, data: print(f"  NOTIF +{time.time()-t0:5.1f}s {ch.uuid[:8]} {data.hex()}", flush=True)
        for ch in notifiable:
            try:
                await c.start_notify(ch, cb(ch))
                print("subscribed", ch.uuid)
            except Exception as e:
                print("subscription refused", ch.uuid, e)
        await asyncio.sleep(DURATION)

asyncio.run(main())
