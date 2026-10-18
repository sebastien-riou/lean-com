"""The Python host against the real C library, compiled for this machine and run as a subprocess."""

import pytest
from harness import EXIT_LEANCOM_ERROR, SYNC, headers, split_packets

from leancom import Device

pytestmark = pytest.mark.native

HELLO = b'hello world!\n'
DONE = b'basic_test done.\n'
QUERY = bytes.fromhex('00112233')
ANSWER = bytes.fromhex('ffeeddcc')


def run_basic(device):
    """The host side of the 'basic' scenario, up to the exit of the device."""
    device.host.synchronize()
    device.host.tx(QUERY)
    assert device.host.rx(4) == ANSWER
    assert device.wait() == 0


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
    assert device.transport.to_device == SYNC + b'\xc4' + QUERY
    assert device.transport.from_device == SYNC + b'\x8d' + HELLO + b'\x44' + b'\x04' + ANSWER + b'\x91' + DONE


@pytest.mark.parametrize('size', [1, 62, 63, 64, 126, 127, 200, 4096])
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
    from_device = device.transport.from_device[len(SYNC) :]
    to_device = device.transport.to_device[len(SYNC) :]
    assert headers(from_device, from_device=True) == [0x7F] * full + [0x40 | r for r in tail] + [0x3F] * full + tail
    assert headers(to_device, from_device=False) == [0xFF] * full + [0xC0 | r for r in tail]


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
    assert headers(device.transport.from_device[len(SYNC) :], from_device=True) == [0xBF, 0x88, 0x12]


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
    packets = split_packets(device.transport.from_device[len(SYNC) :], from_device=True)
    chars = packets[1:40]
    assert [header for header, _ in chars] == [0x81] * 39
    assert b''.join(payload for _, payload in chars) == b'hello world from printf over lean-com!\n'


def test_sync_recovers_lost_device_byte(native_device):
    device = native_device('basic')
    assert device.transport.read(1) == b'\xbc'  # dropped: the host never sees the first magic byte
    run_basic(device)


def test_sync_recovers_lost_host_byte(native_device):
    run_basic(native_device('basic', discard=1))


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
    assert device.host.rx_packet() == (Device.PRINT, HELLO)
    assert device.host.rx_packet() == (Device.TX_REQ, 4)
    device.transport.write(answer)
    assert device.wait() == EXIT_LEANCOM_ERROR
    assert b'device: leancom error at leancom.h:' in device.stderr
