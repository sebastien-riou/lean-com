"""The Python host against the real C library, compiled for this machine and run as a subprocess."""

import pytest
from harness import (
    ACK,
    DEVICE_SOURCE,
    EXIT_LEANCOM_ERROR,
    GO,
    HELLO,
    MAGIC,
    DeviceExitedError,
    NativeDevice,
    compile_c,
    headers,
    split_packets,
    sync_from_device,
    sync_to_device,
)

from leancom import Device, DeviceRestartedError

pytestmark = pytest.mark.native

GREETING = b'hello world!\n'
DONE = b'basic_test done.\n'
QUERY = bytes.fromhex('00112233')
ANSWER = bytes.fromhex('ffeeddcc')


def run_basic(device):
    """The host side of the 'basic' scenario, up to the exit of the device."""
    device.host.synchronize()
    device.host.tx(QUERY)
    assert device.host.rx(4) == ANSWER
    assert device.wait() == 0


def after_sync(device):
    """The wire logs without their synchronization prefix: (to the device, from the device)."""
    sid = device.host.session_id
    to_device = device.transport.to_device[len(sync_to_device(sid)) :]
    from_device = device.transport.from_device[len(sync_from_device(sid)) :]
    return to_device, from_device


def test_basic_example(native_device, capsys):
    """The exchange of docs/protocol.rst, byte for byte."""
    device = native_device('basic')
    host = device.host
    host.synchronize()
    host.tx(QUERY)
    assert host.rx(4) == ANSWER
    assert host.rx_packet() == (Device.PRINT, DONE)
    assert device.wait() == 0
    assert capsys.readouterr().out == 'hello world!\n'
    sid = host.session_id
    assert device.transport.to_device == sync_to_device(sid) + b'\xc4' + QUERY
    expected = sync_from_device(sid) + b'\x8d' + GREETING + b'\x44' + b'\x04' + ANSWER + b'\x91' + DONE
    assert device.transport.from_device == expected


@pytest.mark.parametrize('size', [0, 1, 62, 63, 64, 126, 127, 200, 4096])
def test_echo(native_device, size):
    """Transfers are split in packets of 63 bytes plus the remainder; no empty packet after an exact multiple."""
    device = native_device('echo', size=size)
    host = device.host
    host.synchronize()
    payload = bytes(i & 0xFF for i in range(size))
    host.tx(payload)
    assert host.rx(size) == payload
    assert device.wait() == 0
    full, rest = divmod(size, 63)
    tail = [rest] if rest else []
    to_device, from_device = after_sync(device)
    assert headers(from_device, from_device=True) == [0x7F] * full + [0x40 | r for r in tail] + [0x3F] * full + tail
    assert headers(to_device, from_device=False) == [0xFF] * full + [0xC0 | r for r in tail]


def test_zero_size_transfers_send_nothing(native_device):
    """leancom_rx_data(), leancom_tx_data() and leancom_print() with a size of 0 put nothing on the wire."""
    device = native_device('zero_sizes')
    device.host.synchronize()
    device.host.tx(b'')
    assert device.host.rx(1) == b'\x42'
    assert device.wait() == 0
    to_device, from_device = after_sync(device)
    assert to_device == b''
    assert from_device == b'\x01\x42'


def test_rx_in_pieces(native_device):
    device = native_device('echo', size=10)
    device.host.synchronize()
    device.host.tx(bytes(range(10)))
    assert device.host.rx(3) + device.host.rx(7) == bytes(range(10))
    assert device.wait() == 0


def test_readline_and_print_during_rx(native_device, capsys):
    device = native_device('lines')
    device.host.synchronize()
    assert device.host.readline() == b'line one'
    assert device.host.readline() == b'line two'
    assert device.wait() == 0
    assert capsys.readouterr().out == '0123456789' * 7 + '\n'
    assert headers(after_sync(device)[1], from_device=True) == [0xBF, 0x88, 0x12]


def test_putchar_packets(native_device, capsys):
    """leancom_putchar, behind printf, sends one packet per character."""
    device = native_device('basic_printf')
    host = device.host
    host.synchronize()
    host.tx(QUERY)
    assert host.rx(4) == ANSWER
    assert host.rx_packet() == (Device.PRINT, DONE)
    assert device.wait() == 0
    assert capsys.readouterr().out == 'hello world!\nhello world from printf over lean-com!\n'
    packets = split_packets(after_sync(device)[1], from_device=True)
    chars = packets[1:40]
    assert [header for header, _ in chars] == [0x81] * 39
    assert b''.join(payload for _, payload in chars) == b'hello world from printf over lean-com!\n'


# synchronization: the device starts first, so on pipes its HELLO is always received (see sync_to_device);
# device-first on a real port is "HELLO lost", host-first is "MAGIC lost" (drop=N)


def test_sync_hello_lost(native_device):
    """The host opened its port after HELLO went by: its first MAGIC is enough."""
    device = native_device('basic')
    assert device.transport.read(8) == HELLO  # dropped before synchronize()
    run_basic(device)
    sid = device.host.session_id
    assert device.transport.to_device.startswith(MAGIC + sid + GO)


def test_sync_hello_partially_lost(native_device):
    """The port was opened in the middle of HELLO: its last byte still triggers a second MAGIC."""
    device = native_device('basic')
    assert device.transport.read(3) == HELLO[:3]
    run_basic(device)
    assert device.transport.to_device.startswith(sync_to_device(device.host.session_id))


def test_sync_magic_lost(native_device):
    """The device was in reset when the first MAGIC was sent: HELLO makes the host send it again."""
    device = native_device('basic', drop=8)
    run_basic(device)
    sid = device.host.session_id
    assert device.transport.dropped == MAGIC + sid
    assert device.transport.to_device.startswith(MAGIC + sid + GO)


@pytest.mark.parametrize('drop', [1, 5, 7])
def test_sync_magic_partially_lost(native_device, drop):
    device = native_device('basic', drop=drop)
    run_basic(device)
    sid = device.host.session_id
    assert device.transport.to_device.startswith((MAGIC + sid)[drop:] + MAGIC + sid + GO)


@pytest.mark.parametrize('garbage', [1, 7, 8, 9, 20])
def test_sync_stale_bytes_from_device(native_device, garbage):
    device = native_device('basic', garbage=garbage)
    run_basic(device)
    sid = device.host.session_id
    assert device.transport.from_device.startswith(b'\x55' * garbage + HELLO + ACK + sid)
    assert device.transport.to_device.startswith(sync_to_device(sid))


@pytest.mark.parametrize(
    'prelude',
    [b'\x55', b'\x55' * 20, MAGIC[:4], GO, GO + MAGIC[:5], MAGIC + b'\x00\x00'],
    ids=['byte', 'bytes', 'partial-magic', 'go', 'go-and-partial-magic', 'stale-frame'],
)
def test_sync_stale_bytes_from_host(native_device, prelude):
    """Stale bytes in the device input, including a complete stale MAGIC that the device acknowledges."""
    device = native_device('basic')
    assert device.transport.read(8) == HELLO  # the device is past its flush: the prelude reaches its window
    device.transport.write(prelude)
    run_basic(device)
    assert device.transport.to_device.startswith(prelude)


def test_sync_host_restart_while_device_waits_for_go(native_device):
    """A new host, with a new id, joins a device that acknowledged a previous host and waits for GO."""
    device = native_device('basic')
    transport = device.transport
    assert transport.read(8) == HELLO  # the first host synchronizes by hand, then dies before GO
    transport.write(MAGIC + b'\x00\x01')
    assert transport.read(8) == ACK + b'\x00\x01'
    device.host.synchronize(session_id=b'\x00\x02')
    device.host.tx(QUERY)
    assert device.host.rx(4) == ANSWER
    assert device.wait() == 0
    assert transport.from_device[16:24] == ACK + b'\x00\x02'


def test_device_restart_is_detected_and_resynchronized(native_device, capsys):
    """A device reset in the middle of the session: the host raises, synchronizes again and goes on."""
    device = native_device('restart')
    host = device.host
    host.synchronize()
    with pytest.raises(DeviceRestartedError):
        host.rx(1)
    assert capsys.readouterr().out == 'hello world!\n'
    host.synchronize()
    host.tx(QUERY)
    assert host.rx(4) == ANSWER
    assert device.wait() == 0


def test_print_utf8_split_across_packets(native_device, capsys):
    """A character cut by the 63-byte packet boundary is displayed once complete (ISSUES.md #4)."""
    device = native_device('print_utf8')
    device.host.synchronize()
    assert device.host.rx(1) == b'\x42'
    assert device.wait() == 0
    assert capsys.readouterr().out == 'a' * 62 + '\u00e9\n'


def test_header_in_two_translation_units(tmp_path):
    """Every function of the header is static: two C files can include it and link together (ISSUES.md #3)."""
    a = tmp_path / 'a.c'
    b = tmp_path / 'b.c'
    a.write_text('#include "leancom.h"\nvoid a(void){ leancom_synchronize(); }\n')
    b.write_text(
        '#include "leancom.h"\n'
        'void a(void);\n'
        'void _leancom_tx(const void *const buf, unsigned int size){ (void)buf; (void)size; }\n'
        'void _leancom_rx(void *const buf, unsigned int size){ (void)buf; (void)size; }\n'
        'void _leancom_error_handler(uint32_t err_code){ (void)err_code; }\n'
        'int main(void){ a(); leancom_synchronize(); return 0; }\n'
    )
    compile_c([a, b], tmp_path / 'two')


def test_flush_hook_discards_stale_input(native_device):
    """A complete stale MAGIC and GO in the device input are discarded by _leancom_rx_flush()."""
    device = native_device('basic', flush=1)
    device.transport.write(b'\x00' + MAGIC + b'\xaa\xbb' + GO)  # one write: all in place when the trigger is read
    run_basic(device)
    assert device.transport.from_device.startswith(HELLO + ACK + device.host.session_id)


def test_without_flush_hook_stale_frames_desynchronize(device_timeout, tmp_path):
    """Without the hook, the device acknowledges the stale MAGIC, consumes the stale GO and enters its
    application, where the host's MAGIC is a bad packet header."""
    binary = tmp_path / 'device-noflush'
    compile_c([DEVICE_SOURCE], binary)
    device = NativeDevice(binary, 'basic', {}, device_timeout, tmp_path / 'device-noflush.stderr')
    try:
        device.transport.write(MAGIC + b'\xaa\xbb' + GO)
        with pytest.raises(DeviceExitedError):
            device.host.synchronize()
        assert device.wait() == EXIT_LEANCOM_ERROR
    finally:
        device.close()


# direction errors and the device's own checks


def test_rx_while_device_waits_raises(native_device, capsys):
    device = native_device('basic')
    device.host.synchronize()
    with pytest.raises(RuntimeError, match='Device is waiting for a packet'):
        device.host.rx(1)
    assert capsys.readouterr().out == 'hello world!\n'  # the print before the request was displayed


def test_tx_while_device_sends_raises(native_device):
    device = native_device('sends_first')
    device.host.synchronize()
    with pytest.raises(RuntimeError, match=r'^Device is sending data \('):
        device.host.tx(b'\x00')


def test_tx_with_too_little_data_raises(native_device):
    device = native_device('basic')
    device.host.synchronize()
    with pytest.raises(RuntimeError, match=r'Device request more data \(4 requested, 3 available\)'):
        device.host.tx(QUERY[:3])


@pytest.mark.parametrize('answer', [b'\x04' + QUERY, b'\xc5' + QUERY + b'\x44'], ids=['wrong-type', 'wrong-size'])
def test_device_rejects_bad_answer(native_device, answer):
    """The device checks the type and the size of the answer to its request, and calls the error handler."""
    device = native_device('basic')
    device.host.synchronize()
    assert device.host.rx_packet() == (Device.PRINT, GREETING)
    assert device.host.rx_packet() == (Device.TX_REQ, 4)
    device.transport.write(answer)
    assert device.wait() == EXIT_LEANCOM_ERROR
    assert b'device: leancom error at leancom.h:' in device.stderr
