"""Interactive companion to run_115i_test.bat; no shell interpolation of input."""

import contextlib
from datetime import datetime
import importlib.util
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


class Tee:
    def __init__(self, console, logfile):
        self.console = console
        self.logfile = logfile

    def write(self, text):
        self.console.write(text)
        self.logfile.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.logfile.flush()


def run_logged(arguments, path):
    """Show setup/scanner output while saving an exact text copy."""
    with path.open('x', encoding='utf-8') as logfile:
        with subprocess.Popen(
            arguments, cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        ) as process:
            try:
                for line in process.stdout:
                    print(line, end='', flush=True)
                    logfile.write(line)
                    logfile.flush()
                return process.wait()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise


def main():
    if sys.version_info < (3, 11):
        print('Python 3.11 or newer is required. Install it and recreate the .venv folder.')
        return 1
    session = ROOT / 'test-results' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    session.mkdir(parents=True)
    print(f'All results for this run: {session}')
    if importlib.util.find_spec('bleak') is None:
        print('Installing Bluetooth dependencies (internet required on first run)...')
        result = run_logged(
            [sys.executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')],
            session / 'setup-debug.log',
        )
        if result:
            print('Dependency installation failed. See setup-debug.log.')
            return result
    print('Checking the offline tests...')
    result = run_logged(
        [sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        session / 'offline-tests.log',
    )
    if result:
        print('Offline tests failed. Resolve this before testing the probe.')
        return result

    print('\nPower on the 115i. Disconnect it from the phone app and manifold.')
    print('No Windows Settings pairing or PIN entry is required for this test.')
    address = input('Probe Bluetooth address (Enter to scan first): ').strip()
    if not address:
        result = run_logged(
            [sys.executable, '-u', str(ROOT / 'scan.py'), '--duration', '30', '--all'],
            session / 'scan-debug.log',
        )
        if result:
            print('Scan failed. See scan-debug.log.')
            return result
        address = input('Copy the 115i Bluetooth address from the scan above: ').strip()
    while not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address):
        print('Enter a Windows Bluetooth address in the form AA:BB:CC:DD:EE:FF.')
        address = input('Probe Bluetooth address: ').strip()

    print('\nChoose 60 seconds for a room-temperature baseline, or 120 for warming/cooling.')
    while True:
        duration = input('Test duration in seconds [60]: ').strip() or '60'
        if duration.isascii() and duration.isdigit() and 1 <= int(duration) <= 86400:
            break
        print('Enter a whole number from 1 to 86400.')

    import testo115

    csv_path = session / 'readings.csv'
    log_path = session / 'debug.log'
    print('Starting test. CRC checks are enabled. Press Ctrl+C to stop early.')
    previous_argv = sys.argv
    try:
        sys.argv = ['testo115.py', address, '--duration', duration,
                    '--csv', str(csv_path), '--debug']
        with log_path.open('x', encoding='utf-8') as logfile:
            out, err = Tee(sys.stdout, logfile), Tee(sys.stderr, logfile)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                print(f'Python: {sys.version}; duration: {duration} seconds after startup')
                result = testo115.main()
                print(f'Reader exit code: {result}')
    finally:
        sys.argv = previous_argv
    (session / 'exit-code.txt').write_text(f'{result}\n', encoding='utf-8')
    print(f'\nResults saved in: {session}')
    print('Share readings.csv, debug.log, offline-tests.log, and your app comparisons.')
    print('An exit code of 0 after Ctrl+C means a clean stop, not hardware validation.')
    return result


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nTest setup cancelled.')
        sys.exit(130)
    except Exception as error:
        print(f'Launcher error: {error}', file=sys.stderr)
        sys.exit(1)
