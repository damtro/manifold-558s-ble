"""Read experimental Testo 115i temperature and battery values with CRC validation.

CRC-valid streaming was captured on one Windows probe. Units and accuracy
still require comparison with the vendor app; the full schema remains unknown.
"""

import argparse
import asyncio
import csv
import math
import struct
import sys
from contextlib import nullcontext
from datetime import datetime, timezone

from testo_ble import stream_frames


def log(message):
    print(f'{datetime.now().astimezone().isoformat(timespec="seconds")} | {message}', flush=True)


def measurements(frame):
    """Extract provisional values from a validated measurement push only."""
    if frame[:2] != b'\x10\x80':
        return
    payload = frame[8:-2]
    for name in ('LineTemperature', 'BatteryLevel'):
        marker = name.encode('ascii')
        position = payload.find(marker)
        if position < 0:
            continue
        start = position + len(marker)
        if len(payload) < start + 4:
            continue
        value = struct.unpack_from('<f', payload, start)[0]
        if math.isfinite(value) and (name != 'BatteryLevel' or 0 <= value <= 100):
            yield name, value


class Readout:
    """Print and persist one row per push, without carrying stale values forward."""

    FIELDS = ('timestamp_utc', 'temperature_c', 'temperature_f', 'battery_percent')

    def __init__(self, csv_file=None):
        self.csv_file = csv_file
        self.writer = csv.DictWriter(csv_file, fieldnames=self.FIELDS) if csv_file else None
        self.count = 0
        if self.writer:
            self.writer.writeheader()
            csv_file.flush()

    def __call__(self, frame):
        values = dict(measurements(frame))
        if not values:
            return
        row = {'timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds')}
        if 'LineTemperature' in values:
            celsius = values['LineTemperature']
            fahrenheit = celsius * 9 / 5 + 32
            row.update(temperature_c=celsius, temperature_f=fahrenheit)
            log(f'Temperature: {celsius:.2f} °C / {fahrenheit:.2f} °F')
        if 'BatteryLevel' in values:
            row['battery_percent'] = values['BatteryLevel']
            log(f'Battery: {values["BatteryLevel"]:.0f}%')
        if self.writer:
            self.writer.writerow(row)
            self.csv_file.flush()
        self.count += 1


async def stream(args):
    # Exclusive creation protects existing logs from accidental overwrite.
    output = open(args.csv, 'x', newline='', encoding='utf-8') if args.csv else nullcontext(None)
    with output as csv_file:
        readout = Readout(csv_file)
        log(f'Connecting to Testo 115i: {args.address}; CRC validation enabled')
        rejected = await stream_frames(args.address, readout, duration=args.duration,
                                       debug=log if args.debug else None)
        log(f'Received {readout.count} measurement pushes; rejected {rejected} invalid framing bytes')
        if readout.count == 0:
            raise RuntimeError('No validated measurements received. Capture --debug output to investigate the session and CRC/schema compatibility.')


def nonnegative_seconds(text):
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError('duration must be a finite number >= 0')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('address', help='BLE address, or macOS device UUID (see scan.py)')
    parser.add_argument('--duration', type=nonnegative_seconds, default=0,
                        help='seconds after startup; 0 listens until Ctrl+C (default)')
    parser.add_argument('--csv', metavar='PATH', help='create a new CSV log (existing files are protected)')
    parser.add_argument('--debug', action='store_true', help='print raw RX notifications and TX commands')
    parser.add_argument('--verify-crc', action='store_true', help='compatibility option; CRC validation is always enabled')
    args = parser.parse_args()
    try:
        asyncio.run(stream(args))
    except KeyboardInterrupt:
        log('Stopped.')
    except Exception as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
