import asyncio
import csv
import io
import struct
import unittest
from unittest.mock import patch

import testo_ble as m
from testo115 import measurements, Readout


def frame(payload):
    h = b'\x10\x80' + struct.pack('<I', len(payload) + 2)
    return h + m.crc16(h) + payload + m.crc16(payload)


class DecoderTests(unittest.TestCase):
    def test_all_fragment_boundaries(self):
        data = frame(b'LineTemperature' + struct.pack('<f', 23.5))
        for cut in range(1, len(data)):
            decoder = m.FrameDecoder()
            self.assertEqual(decoder.feed(data[:cut]), [])
            self.assertEqual(decoder.feed(data[cut:]), [data])

    def test_noise_coalescing_and_both_properties(self):
        data = frame(b'LineTemperature' + struct.pack('<f', 23.5)
                     + b'BatteryLevel' + struct.pack('<f', 75))
        self.assertEqual(m.FrameDecoder().feed(b'noise' + data + data), [data, data])
        self.assertEqual(list(measurements(data)),
                         [('LineTemperature', 23.5), ('BatteryLevel', 75)])

    def test_uint32_length_and_crc_recovery(self):
        valid = frame(b'BatteryLevel' + struct.pack('<f', 80))
        bad_header = bytearray(valid)
        bad_header[4] = 1
        bad_payload = bytearray(valid)
        bad_payload[-1] ^= 1
        self.assertEqual(m.FrameDecoder().feed(bad_header + bad_payload + valid), [valid])

    def test_crc_required(self):
        data = bytearray(frame(b'BatteryLevel' + struct.pack('<f', 80)))
        data[-1] ^= 1
        self.assertEqual(m.FrameDecoder().feed(data), [])

    def test_truncated_and_nonfinite_values(self):
        for payload in (b'LineTemperature\x00', b'LineTemperature' + struct.pack('<f', float('nan'))):
            self.assertEqual(list(measurements(frame(payload))), [])

    def test_known_startup_checksums(self):
        self.assertEqual(m.crc16(b'123456789'), bytes.fromhex('374b'))
        for command in m.COMMANDS:
            self.assertEqual(m.crc16(command[:6]), command[6:8])
            self.assertEqual(len(command), 8 + struct.unpack_from('<I', command, 2)[0])
            if len(command) > 8:
                self.assertEqual(m.crc16(command[8:-2]), command[-2:])

    def test_large_frame_uses_all_four_length_bytes(self):
        data = frame(b'x' * 65536)
        decoder = m.FrameDecoder()
        self.assertEqual(decoder.feed(data[:60000]), [])
        self.assertEqual(decoder.feed(data[60000:]), [data])

    def test_empty_and_other_command_frames(self):
        for data in m.COMMANDS:
            self.assertEqual(m.FrameDecoder().feed(data), [data])
            self.assertEqual(list(measurements(data)), [])

    def test_invalid_lengths_and_bounded_noise(self):
        valid = frame(b'BatteryLevel' + struct.pack('<f', 80))
        for length in (1, m.MAX_LENGTH + 1, 0xffffffff):
            header = b'\x10\x80' + struct.pack('<I', length)
            decoder = m.FrameDecoder()
            self.assertEqual(decoder.feed(header + m.crc16(header) + valid), [valid])
        decoder = m.FrameDecoder()
        decoder.feed(b'x' * 10000)
        self.assertLess(len(decoder.buffer), 8)

    def test_csv_rows_do_not_reuse_stale_values(self):
        output = io.StringIO()
        readout = Readout(output)
        with patch('testo115.log'):
            readout(frame(b'LineTemperature' + struct.pack('<f', 0)))
            readout(frame(b'BatteryLevel' + struct.pack('<f', 75)))
            readout(frame(b'BatteryLevel' + struct.pack('<f', 101)))
        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(float(rows[0]['temperature_f']), 32)
        self.assertEqual(rows[0]['battery_percent'], '')
        self.assertEqual(rows[1]['temperature_c'], '')
        self.assertTrue(rows[0]['timestamp_utc'].endswith('+00:00'))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def run_transport(self, *, disconnect=False, callback_error=False):
        events = []
        received = []
        packet = frame(b'BatteryLevel' + struct.pack('<f', 75))

        class Client:
            is_connected = True

            def __init__(self, address, **kwargs):
                self.disconnect = kwargs['disconnected_callback']

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                events.append('closed')

            async def start_notify(self, uuid, callback):
                events.append('subscribed')
                self.callback = callback

            async def write_gatt_char(self, uuid, command, response):
                events.append(command)
                self.callback(None, packet)
                if disconnect:
                    self.is_connected = False
                    self.disconnect(self)

        def consume(data):
            if callback_error:
                raise OSError('disk full')
            received.append(data)

        try:
            await m.stream_frames('test', consume, client_factory=Client,
                                  duration=0.001, startup_delay=0)
        finally:
            self.assertEqual(events[0], 'subscribed')
            self.assertEqual(events[-1], 'closed')
        self.assertEqual(events[1:-1], list(m.COMMANDS))
        self.assertEqual(received, [packet] * 3)

    async def test_subscribe_before_writes_and_cleanup(self):
        await self.run_transport()

    async def test_disconnect_surfaces(self):
        with self.assertRaisesRegex(ConnectionError, 'disconnected'):
            await self.run_transport(disconnect=True)

    async def test_csv_failure_surfaces(self):
        with self.assertRaisesRegex(OSError, 'disk full'):
            await self.run_transport(callback_error=True)


if __name__ == '__main__':
    unittest.main()
