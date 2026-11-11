import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    'testo115', Path(__file__).resolve().parents[1] / 'testo115.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def frame(payload):
    h = b'\x10\x80' + struct.pack('<I', len(payload) + 2)
    return h + m.crc16(h) + payload + m.crc16(payload)


class DecoderTests(unittest.TestCase):
    def test_all_fragment_boundaries(self):
        data = frame(b'LineTemperature' + struct.pack('<f', 23.5))
        for cut in range(1, len(data)):
            decoder = m.FrameDecoder(True)
            self.assertEqual(decoder.feed(data[:cut]), [])
            self.assertEqual(decoder.feed(data[cut:]), [data])

    def test_noise_coalescing_and_both_properties(self):
        data = frame(b'LineTemperature' + struct.pack('<f', 23.5)
                     + b'BatteryLevel' + struct.pack('<f', 75))
        self.assertEqual(m.FrameDecoder(True).feed(b'noise' + data + data), [data, data])
        self.assertEqual(list(m.measurements(data)),
                         [('LineTemperature', 23.5), ('BatteryLevel', 75)])

    def test_uint32_length_and_crc_recovery(self):
        valid = frame(b'BatteryLevel' + struct.pack('<f', 80))
        bad_header = bytearray(valid)
        bad_header[4] = 1
        bad_payload = bytearray(valid)
        bad_payload[-1] ^= 1
        self.assertEqual(m.FrameDecoder(True).feed(bad_header + bad_payload + valid), [valid])

    def test_crc_optional(self):
        data = bytearray(frame(b'BatteryLevel' + struct.pack('<f', 80)))
        data[-1] ^= 1
        self.assertEqual(m.FrameDecoder().feed(data), [bytes(data)])

    def test_truncated_and_nonfinite_values(self):
        for payload in (b'LineTemperature\x00', b'LineTemperature' + struct.pack('<f', float('nan'))):
            self.assertEqual(list(m.measurements(frame(payload))), [])

    def test_known_startup_checksums(self):
        self.assertEqual(m.crc16(b'123456789'), bytes.fromhex('374b'))
        for command in m.COMMANDS:
            self.assertEqual(m.crc16(command[:6]), command[6:8])
            self.assertEqual(len(command), 8 + struct.unpack_from('<I', command, 2)[0])
            if len(command) > 8:
                self.assertEqual(m.crc16(command[8:-2]), command[-2:])


if __name__ == '__main__':
    unittest.main()
