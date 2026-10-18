"""leancom.Device against a scripted transport: no device, no C compiler. Bytes come from docs/protocol.rst."""

import pytest
from harness import MAGIC, SYNC, FakeLink

from leancom import Device

HELLO = b'hello world!\n'  # 13 bytes: print packet 0x8D
QUERY = bytes.fromhex('00112233')
ANSWER = bytes.fromhex('ffeeddcc')


def nominal_sync_log():
    """The reads and writes of a nominal synchronization, in order."""
    log = []
    for byte in MAGIC:
        log += [('w', bytes([byte])), ('r', bytes([byte]))]
    return [*log, ('r', b'\x01'), ('w', b'\x01')]


# synchronization


def test_sync_nominal():
    link = FakeLink(SYNC)
    Device(link).synchronize()
    assert link.written == SYNC
    assert not link.incoming
    assert link.log == nominal_sync_log()


def test_sync_recovers_lost_device_byte():
    """The host receives each magic byte one step late, and sends the last one without waiting."""
    link = FakeLink(SYNC[1:])
    Device(link).synchronize()
    assert link.written == SYNC
    assert link.log[-5:] == [('w', b'\x44'), ('r', b'\xf2'), ('w', b'\xf2'), ('r', b'\x01'), ('w', b'\x01')]


def test_sync_restarts_on_mismatch():
    link = FakeLink(MAGIC[:2] + b'\x55' + SYNC)
    Device(link).synchronize()
    assert link.written == MAGIC[:3] + SYNC


def test_sync_answers_zero_until_one():
    link = FakeLink(MAGIC + b'\x55\x01')
    Device(link).synchronize()
    assert link.written == MAGIC + b'\x00\x01'


# rx_packet


@pytest.mark.parametrize('header, size', [(0x44, 4), (0x40, 0), (0x7F, 63)])
def test_rx_packet_tx_req(header, size):
    link = FakeLink(bytes([header, 0xAA]))  # a request has no payload: the next byte is not read
    assert Device(link).rx_packet() == (Device.TX_REQ, size)
    assert link.incoming == b'\xaa'


def test_rx_packet_print():
    link = FakeLink(b'\x8d' + HELLO)
    assert Device(link).rx_packet() == (Device.PRINT, HELLO)
    assert not link.incoming


@pytest.mark.parametrize('packet, payload', [(b'\x04' + ANSWER, ANSWER), (b'\x00', b'')])
def test_rx_packet_data(packet, payload):
    link = FakeLink(packet)
    assert Device(link).rx_packet() == (Device.RX_DATA, payload)
    assert not link.incoming


@pytest.mark.parametrize('header', [0xC0, 0xC4, 0xFF])
def test_rx_packet_rejects_host_to_device_header(header):
    link = FakeLink(bytes([header]) + bytes(63))
    with pytest.raises(RuntimeError, match=f'Received an invalid header: 0x{header:02x}'):
        Device(link).rx_packet()


# tx


def test_tx_serves_one_request():
    link = FakeLink(b'\x44')
    Device(link).tx(QUERY)
    assert link.log == [('r', b'\x44'), ('w', b'\xc4'), ('w', QUERY)]


def test_tx_splits_in_packets():
    """100 bytes requested as 63 + 37, the example of docs/protocol.rst."""
    data = bytes(range(100))
    link = FakeLink(b'\x7f\x65')
    Device(link).tx(data)
    assert link.written == b'\xff' + data[:63] + b'\xe5' + data[63:]


def test_tx_serves_several_device_calls():
    link = FakeLink(b'\x42\x42')
    Device(link).tx(QUERY)
    assert link.written == b'\xc2' + QUERY[:2] + b'\xc2' + QUERY[2:]


def test_tx_empty_returns_without_reading():
    link = FakeLink()
    Device(link).tx(b'')
    assert link.log == []


def test_tx_displays_prints(capsys):
    link = FakeLink(b'\x8d' + HELLO + b'\x44')
    Device(link).tx(QUERY)
    assert capsys.readouterr().out == 'hello world!\n'


def test_tx_rejects_data_packet():
    link = FakeLink(b'\x02\x00\x11')
    with pytest.raises(RuntimeError, match=r'^Device is sending data \('):
        Device(link).tx(b'\x00')


def test_tx_rejects_oversized_request():
    link = FakeLink(b'\x45')
    with pytest.raises(RuntimeError, match=r'Device request more data \(5 requested, 4 available\)'):
        Device(link).tx(QUERY)
    assert link.written == b''


# rx, readline and the file-like aliases


def test_rx_exact_packet():
    link = FakeLink(b'\x04' + ANSWER)
    device = Device(link)
    out = device.rx(4)
    assert out == ANSWER
    assert isinstance(out, bytearray)
    assert device.rxbuf == b''


def test_rx_keeps_excess_for_next_call():
    link = FakeLink(bytes.fromhex('04 01020304 03 050607'))
    device = Device(link)
    assert device.rx(2) == b'\x01\x02'
    assert device.rxbuf == b'\x03\x04'
    assert device.rx(3) == b'\x03\x04\x05'
    assert device.rxbuf == b'\x06\x07'
    assert not link.incoming
    assert device.rx(2) == b'\x06\x07'
    assert device.rxbuf == b''


def test_rx_spans_packets():
    data = bytes(range(100))
    link = FakeLink(b'\x3f' + data[:63] + b'\x25' + data[63:])
    assert Device(link).rx(100) == data


def test_rx_zero_returns_without_reading():
    link = FakeLink()
    assert Device(link).rx(0) == b''
    assert link.log == []


def test_rx_skips_empty_packets():
    link = FakeLink(b'\x00\x01A')
    assert Device(link).rx(1) == b'A'


def test_rx_displays_prints(capsys):
    link = FakeLink(b'\x83hi\n\x01\x42')
    assert Device(link).rx(1) == b'\x42'
    assert capsys.readouterr().out == 'hi\n'


def test_rx_rejects_tx_req():
    link = FakeLink(b'\x44')
    with pytest.raises(RuntimeError, match='Device is waiting for a packet'):
        Device(link).rx(1)


def test_readline_within_packet():
    device = Device(FakeLink(b'\x06ab\ncd\n'))
    assert device.readline() == b'ab'
    assert device.readline() == b'cd'


def test_readline_across_packets():
    device = Device(FakeLink(b'\x02ab\x02\nc\x02d\n'))
    line = device.readline()
    assert line == b'ab'
    assert type(line) is bytes
    assert device.readline() == b'cd'


def test_file_like_aliases():
    link = FakeLink(b'\x44\x05' + ANSWER + b'\x99')
    device = Device(link)
    assert device.write(QUERY) is None
    assert link.written == b'\xc4' + QUERY
    assert device.read(4) == ANSWER
    assert device.read() == b'\x99'
    device.flush()
    assert link.flushes == 1


def test_header_constants():
    assert (Device.RX_DATA, Device.TX_REQ, Device.PRINT, Device.COM_TO_DEVICE) == (0x00, 0x40, 0x80, 0xC0)
