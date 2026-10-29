"""Scan for nearby Bluetooth LE devices that look like testo instruments.

Usage: python scan.py [--duration 30] [--all]
A device only advertises while it is not connected to the phone app.
"""
import argparse, asyncio
from bleak import BleakScanner

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--duration", type=float, default=30, help="seconds to scan (default 30)")
parser.add_argument("--all", action="store_true", help="show every device, not only likely matches")
args = parser.parse_args()

seen = {}


def likely(name, adv):
    # filter on the name, or on service fff0 seen in the advertisements of the devices we tested
    return "testo" in name.lower() or name.upper().startswith("T") or \
        any(str(u).startswith("0000fff0") for u in adv.service_uuids)


def cb(dev, adv):
    name = adv.local_name or dev.name or ""
    if not args.all and not likely(name, adv):
        return
    line = (f"{dev.address} rssi={adv.rssi} name={name!r}"
            f" mfr={{{', '.join(f'{k:#06x}:{v.hex()}' for k, v in adv.manufacturer_data.items())}}}"
            f" svc={[str(u)[:8] for u in adv.service_uuids]}"
            f" sdata={{{', '.join(f'{str(k)[:8]}:{v.hex()}' for k, v in adv.service_data.items())}}}")
    if seen.get(dev.address) != line:
        seen[dev.address] = line
        print(line, flush=True)


async def main():
    async with BleakScanner(cb):
        await asyncio.sleep(args.duration)
    print(f"--- {len(seen)} device(s)")

asyncio.run(main())
