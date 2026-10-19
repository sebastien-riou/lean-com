"""Helpers of the test suite: the native device process, transports for leancom.Device and wire-level tools."""

import os
import select
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import leancom

REPO_ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIR = REPO_ROOT / 'include'
HEADER = INCLUDE_DIR / 'leancom.h'
EXAMPLE_HEADER = REPO_ROOT / 'examples' / 'basic' / 'include' / 'leancom.h'
DEVICE_SOURCE = Path(__file__).resolve().parent / 'native' / 'device.c'

#: The synchronization frames, as in docs/protocol.rst (checked against leancom.Device in test_host.py)
HELLO = bytes.fromhex('DA 42 65 83 2B A0 E6 AA')  # device -> host, announces the device
MAGIC = bytes.fromhex('BC 02 9D 8A A7 3F')  # host -> device, followed by the 2-byte session id
ACK = bytes.fromhex('2B D7 94 6C E1 38')  # device -> host, followed by the session id it received
GO = bytes.fromhex('93 4A E8 27 5C B1 F6 0E')  # host -> device, ends the handshake

#: Exit codes of the native device, see native/device.c
EXIT_USAGE = 2
EXIT_IO = 101
EXIT_LEANCOM_ERROR = 102


def sync_to_device(sid):
    """What the host sends to synchronize a native device on pipes.

    The device starts first and its HELLO waits in the pipe, so the host always receives it and sends MAGIC a
    second time; the device skips that copy while waiting for GO.
    """
    return MAGIC + sid + MAGIC + sid + GO


def sync_from_device(sid):
    """What a native device on pipes sends to synchronize."""
    return HELLO + ACK + sid


class DeviceTimeoutError(TimeoutError):
    """The host waited for the native device past the deadline: deadlock or livelock."""


class DeviceExitedError(RuntimeError):
    """The native device ended its side of the link while the host still needed it."""


def compile_c(sources, output, *, extra=(), check=True):
    """Compile and link C sources with $CC (default cc), with -I include. Returns the CompletedProcess.

    A missing compiler, or a failure when check is true, fails the test with the command and its output.
    """
    cc = os.environ.get('CC', 'cc')
    cc_path = shutil.which(cc)
    if cc_path is None:
        pytest.fail(f'C compiler "{cc}" not found: install one, set CC, or run with -m "not native"', pytrace=False)
    cmd = [cc_path, '-std=c11', '-Wall', '-Wextra', '-Wno-unused-function', '-g', '-O0', f'-I{INCLUDE_DIR}']
    cmd += shlex.split(os.environ.get('CFLAGS', ''))
    cmd += list(extra)
    cmd += ['-o', str(output), *(str(source) for source in sources)]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if check and result.returncode != 0:
        pytest.fail(
            f'compilation failed with code {result.returncode}:\n{shlex.join(cmd)}\n{result.stdout}{result.stderr}',
            pytrace=False,
        )
    return result


def build_device(directory):
    """Compile the native device, with the flush hook, into directory; return the path of the binary."""
    output = Path(directory) / 'device'
    compile_c([DEVICE_SOURCE], output, extra=('-DLEANCOM_RX_FLUSH',))
    return output


class PipeDev:
    """Transport of leancom.Device over the pipes of a NativeDevice.

    read() blocks until the requested bytes arrived, as serial.Serial does without timeout, but gives up at a
    deadline set when the object is created (timeout=None disables it). Every byte is logged in to_device and
    from_device. The first `drop` bytes written are discarded instead of sent, as a link does with bytes sent
    while the device is in reset; they are logged in `dropped`. There is deliberately no reset_input_buffer():
    a pipe keeps every byte, which the tests rely on.
    """

    def __init__(self, proc, timeout, status, drop=0):
        self._rd = proc.stdout.fileno()
        self._wr = proc.stdin.fileno()
        self._status = status
        self.timeout = timeout
        self.deadline = None if timeout is None else time.monotonic() + timeout
        self.to_device = bytearray()
        self.from_device = bytearray()
        self.to_drop = drop
        self.dropped = bytearray()

    def read(self, size=1):
        out = bytearray()
        while len(out) < size:
            pending = size - len(out)
            self._wait_readable(pending)
            chunk = os.read(self._rd, pending)
            if not chunk:
                raise DeviceExitedError(
                    f'device ended its output while the host waited for {pending} byte(s); {self._status()}'
                )
            out += chunk
        self.from_device += out
        return bytes(out)

    def _wait_readable(self, pending):
        if self.deadline is None:
            select.select([self._rd], [], [])
            return
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or not select.select([self._rd], [], [], remaining)[0]:
            raise DeviceTimeoutError(
                f'host waited for {pending} byte(s) from the device past the {self.timeout} s deadline '
                f'(--device-timeout changes it, --debug-friendly disables it); {self._status()}'
            )

    def write(self, data):
        data = bytes(data)
        if self.to_drop:
            n = min(self.to_drop, len(data))
            self.dropped += data[:n]
            self.to_drop -= n
            data = data[n:]
        view = memoryview(data)
        try:
            while view:
                n = os.write(self._wr, view)
                self.to_device += view[:n]
                view = view[n:]
        except BrokenPipeError as e:
            raise DeviceExitedError(f'device closed its input; {self._status()}') from e

    def flush(self):
        pass


class _DeviceProcess:
    """A native device process: the common part of NativeDevice and PtyDevice."""

    def __init__(self, binary, scenario, options, timeout, stderr_path):
        self.args = [str(binary), scenario, *(f'{k}={v}' for k, v in options.items())]
        self.timeout = timeout
        self.stderr_path = Path(stderr_path)
        self._stderr = open(self.stderr_path, 'wb')
        self.proc = None

    def _start(self, **popen_kwargs):
        self.proc = subprocess.Popen(self.args, stderr=self._stderr, **popen_kwargs)  # noqa: S603
        # on stderr, never in the stdout the tests assert on; shown by -s, or in "Captured stderr" on failure
        print(f'native device pid {self.proc.pid}: {shlex.join(self.args)}', file=sys.stderr)

    @property
    def stderr(self):
        """What the device wrote on stderr so far."""
        return self.stderr_path.read_bytes()

    def wait(self):
        """Wait for the device to exit, return its exit code."""
        try:
            return self.proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise DeviceTimeoutError(
                f'device still running {self.timeout} s after the host was done; {self.status()}'
            ) from e

    def status(self):
        """One line describing the state of the device, for error messages."""
        code = self.proc.poll()
        state = 'alive' if code is None else f'exited with code {code}'
        err = self.stderr.decode(errors='replace').strip() or '(nothing)'
        return f'device pid {self.proc.pid} {state}, on its stderr: {err}'

    def _reap(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self._stderr.close()


class NativeDevice(_DeviceProcess):
    """The native device on pipes, with `transport` (a PipeDev) and `host` (the leancom.Device driving it)."""

    def __init__(self, binary, scenario, options, timeout, stderr_path, drop=0):
        super().__init__(binary, scenario, options, timeout, stderr_path)
        self._start(stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.transport = PipeDev(self.proc, timeout, self.status, drop=drop)
        self.host = leancom.Device(self.transport)

    def status(self):
        t = self.transport
        dropped = f', {len(t.dropped)} B dropped before reaching it' if t.dropped else ''
        return (
            f'{super().status()}; {len(t.to_device)} B sent to it (last {t.to_device[-16:].hex(" ")}){dropped}, '
            f'{len(t.from_device)} B received from it (last {t.from_device[-16:].hex(" ")})'
        )

    def close(self):
        """End the device: end of file on its input, SIGPIPE on its output, then SIGKILL if still alive."""
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        self._reap()


class PtyDevice(_DeviceProcess):
    """The native device on the master side of a pseudo-terminal; `path` is the slave, for serial.Serial.

    This is the arrangement of Renode's CreateUartPtyTerminal. The device cannot be interrupted through the
    pty, so a watchdog kills it at the deadline: the slave then reports end of file, which makes a blocked
    serial.Serial.read() raise instead of waiting forever.
    """

    def __init__(self, binary, scenario, options, timeout, stderr_path):
        import termios
        import tty

        super().__init__(binary, scenario, options, timeout, stderr_path)
        master, self.slave_fd = os.openpty()
        # raw mode before the device sends anything: by default the line discipline echoes the bytes back to
        # the device (a stale byte for the synchronization) and turns '\n' into '\r\n'
        tty.setraw(self.slave_fd)
        try:
            tty.setraw(master)
        except termios.error:
            pass  # Linux shares one termios between the two ends, other systems may refuse the master
        self.path = os.ttyname(self.slave_fd)
        self._start(stdin=master, stdout=master)
        os.close(master)  # the device holds the only master: its exit gives end of file on the slave
        self.fired = False
        self._watchdog = None
        if timeout is not None:
            self._watchdog = threading.Timer(timeout, self._kill)
            self._watchdog.daemon = True
            self._watchdog.start()

    def _kill(self):
        self.fired = True
        self.proc.kill()

    def run(self, host_function):
        """Run the host side; an error caused by the watchdog killing the device becomes a DeviceTimeoutError."""
        import serial

        try:
            return host_function()
        except (serial.SerialException, OSError) as e:
            if self.fired:
                raise DeviceTimeoutError(
                    f'host blocked for {self.timeout} s; the device was killed to unblock it; {self.status()}'
                ) from e
            raise

    def wait(self):
        code = super().wait()
        if self.fired:
            raise DeviceTimeoutError(f'device still running {self.timeout} s after the host was done; {self.status()}')
        return code

    def close(self):
        if self._watchdog is not None:
            self._watchdog.cancel()
        self._reap()
        os.close(self.slave_fd)


class FakeLink:
    """Scripted transport playing the device: read() serves canned bytes, write() is recorded.

    read() fails when the script is exhausted, instead of returning nothing like a transport with a timeout.
    """

    def __init__(self, incoming=b''):
        self.incoming = bytearray(incoming)
        self.written = bytearray()
        self.log = []  # ('r', bytes) and ('w', bytes), in order
        self.flushes = 0

    def read(self, size=1):
        assert (
            len(self.incoming) >= size
        ), f'host reads {size} byte(s) but the script has only {len(self.incoming)} left'
        out = bytes(self.incoming[:size])
        del self.incoming[:size]
        self.log.append(('r', out))
        return out

    def write(self, data):
        data = bytes(data)
        self.written += data
        self.log.append(('w', data))

    def flush(self):
        self.flushes += 1


def split_packets(data, *, from_device):
    """Split a wire log taken after the synchronization into a list of (header, payload) tuples.

    Transmit requests (type 0x40, only from the device) have no payload.
    """
    data = bytes(data)
    packets = []
    i = 0
    while i < len(data):
        header = data[i]
        i += 1
        length = header & 0x3F
        if from_device and header & 0xC0 == leancom.Device.TX_REQ:
            length = 0
        payload = data[i : i + length]
        assert (
            len(payload) == length
        ), f'packet 0x{header:02X} at offset {i - 1} is truncated: {len(payload)}/{length} byte(s)'
        packets.append((header, payload))
        i += length
    return packets


def headers(data, *, from_device):
    """The header bytes of a wire log taken after the synchronization."""
    return [header for header, _ in split_packets(data, from_device=from_device)]
