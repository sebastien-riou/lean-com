"""leancom.Device against a scripted transport: no device, no C compiler. Bytes come from docs/protocol.rst."""

import pytest
import syncsim
from harness import ACK, GO, HELLO, MAGIC, FakeLink

from leancom import Device, DeviceRestartedError, cli

GREETING = b'hello world!\n'  # 13 bytes: print packet 0x8D
QUERY = bytes.fromhex('00112233')
ANSWER = bytes.fromhex('ffeeddcc')
SID = b'\x12\x34'  # the session id, imposed so that the scripted bytes are known


class AnsweringLink(FakeLink):
    """Plays a device waiting for the magic: answers it with ACK and the id it carried."""

    def read(self, size=1):
        if not self.incoming and self.written[-8:-2] == MAGIC:
            self.incoming += ACK + self.written[-2:]
        return super().read(size)


# synchronization


def test_sync_nominal():
    link = FakeLink(ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.written == MAGIC + SID + GO
    assert not link.incoming
    assert link.log == [('w', MAGIC + SID), *[('r', bytes([b])) for b in ACK + SID], ('w', GO)]


def test_sync_hello_then_ack():
    """The device started after the host: its HELLO makes the host send MAGIC again."""
    link = FakeLink(HELLO + ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.written == (MAGIC + SID) * 2 + GO
    assert link.log[9] == ('w', MAGIC + SID)  # right after the last byte of HELLO


def test_sync_skips_stale_bytes_and_partial_frames():
    link = FakeLink(b'\x55' * 20 + HELLO[:5] + ACK[:5] + MAGIC + GO + ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.written == MAGIC + SID + GO
    assert not link.incoming


def test_sync_two_hellos():
    link = FakeLink(HELLO + HELLO + ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.written == (MAGIC + SID) * 3 + GO


@pytest.mark.parametrize('incoming', [HELLO[3:] + ACK + SID, b'\x55' + HELLO[-1:] + ACK + SID], ids=['tail', 'byte'])
def test_sync_resends_magic_on_last_byte_of_hello(incoming):
    """A HELLO truncated by the opening of the port still triggers a new MAGIC; a spurious copy is harmless."""
    link = FakeLink(incoming)
    Device(link).synchronize(session_id=SID)
    assert link.written == (MAGIC + SID) * 2 + GO


def test_sync_ignores_ack_with_foreign_id():
    link = FakeLink(ACK + b'\xff\xff' + ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.written == (MAGIC + SID) * 2 + GO


def test_sync_leaves_bytes_after_ack():
    link = FakeLink(ACK + SID + b'\x8d' + GREETING)
    Device(link).synchronize(session_id=SID)
    assert link.incoming == b'\x8d' + GREETING


def test_sync_rejects_empty_read():
    class Silent(FakeLink):
        def read(self, size=1):
            return b''

    with pytest.raises(RuntimeError, match='no data'):
        Device(Silent()).synchronize(session_id=SID)


def test_sync_session_id():
    link = FakeLink(ACK + SID)
    device = Device(link)
    with pytest.raises(ValueError):
        device.synchronize(session_id=b'\x01')
    assert link.log == []
    device.synchronize(session_id=SID)
    assert device.session_id == SID


def test_sync_draws_a_random_session_id():
    link = AnsweringLink()
    device = Device(link)
    device.synchronize()
    assert len(device.session_id) == Device.SESSION_ID_SIZE
    assert link.written == MAGIC + device.session_id + GO


def test_sync_reset_hook_runs_before_any_byte():
    link = FakeLink(ACK + SID)
    Device(link).synchronize(reset=lambda: link.log.append(('reset',)), session_id=SID)
    assert link.log[:2] == [('reset',), ('w', MAGIC + SID)]


def test_sync_flushes_the_input_when_the_transport_can():
    class FlushingLink(FakeLink):
        def __init__(self, stale, live):
            super().__init__(stale)
            self.live = live

        def reset_input_buffer(self):
            self.log.append(('flush',))
            self.incoming = bytearray(self.live)

    link = FlushingLink(b'\x55' * 3 + ACK + b'\x00\x00', ACK + SID)
    Device(link).synchronize(session_id=SID)
    assert link.log[:2] == [('flush',), ('w', MAGIC + SID)]
    assert link.written == MAGIC + SID + GO


def test_sync_constants():
    """The frames of docs/protocol.rst, and the properties that make the window matching unambiguous."""
    patterns = {'HELLO': HELLO, 'MAGIC': MAGIC, 'ACK': ACK, 'GO': GO}
    assert (Device.HELLO, Device.MAGIC, Device.ACK, Device.GO) == (HELLO, MAGIC, ACK, GO)
    assert (syncsim.HELLO, syncsim.MAGIC, syncsim.ACK, syncsim.GO) == (HELLO, MAGIC, ACK, GO)
    assert Device.SESSION_ID_SIZE == 2
    assert [len(p) for p in patterns.values()] == [8, 6, 6, 8]
    for p in patterns.values():
        assert len(set(p)) == len(p), 'distinct bytes'
        assert p[0] != 0, 'the zeroed initial window must not match'
        assert any(b >= 0x80 for b in p), 'stale ASCII text must not match'
        assert all(p[:k] != p[-k:] for k in range(1, len(p))), 'no border'
    assert HELLO[-1] not in ACK
    assert HELLO[0] & 0xC0 == 0xC0, 'an invalid packet header, to detect a restarted device'
    assert not any(b in b'\r\n\x03\x04\x11\x13\x1a\x1c\x7f' for b in HELLO), 'no tty special byte'

    # No frame is recognized at a wrong position inside what a side can receive, whatever the id (wildcards)
    wild = [None, None]
    frames = {'HELLO': list(HELLO), 'MAGIC': list(MAGIC) + wild, 'ACK': list(ACK) + wild, 'GO': list(GO)}

    def stream(*names):
        data, starts = [], {}
        for name in names:
            starts[len(data)] = name
            data += frames[name]
        return data, starts

    sequences = [('MAGIC', 'MAGIC', 'GO'), ('HELLO', 'ACK', 'ACK')] + [(a, b) for a in frames for b in frames]
    for names in sequences:
        data, starts = stream(*names)
        for i in range(len(data)):
            for name, pattern in patterns.items():
                window = data[i : i + len(pattern)]
                if len(window) == len(pattern) and all(
                    w is None or w == p for w, p in zip(window, pattern, strict=True)
                ):
                    assert starts.get(i) == name, f'{name} would be recognized at offset {i} of {names}'


def test_simulation_random_campaign():
    """The in-memory model of both state machines, over random stale bytes, losses, resets and restarts."""
    stats = syncsim.campaign(seed=1, cases=3000)
    assert stats.get('unexpected', 0) == 0, stats
    assert stats['ok'] > 2500, stats


def test_pulse_dtr(monkeypatch):
    class Port:
        def __init__(self):
            self.levels = []

        @property
        def dtr(self):
            return self.levels[-1]

        @dtr.setter
        def dtr(self, level):
            self.levels.append(level)

    sleeps = []
    monkeypatch.setattr(cli.time, 'sleep', sleeps.append)
    port = Port()
    cli.pulse_dtr(port)
    assert port.levels == [True, False]
    assert sleeps == [0.1, 0.1]


# rx_packet


@pytest.mark.parametrize('header, size', [(0x44, 4), (0x40, 0), (0x7F, 63)])
def test_rx_packet_tx_req(header, size):
    link = FakeLink(bytes([header, 0xAA]))  # a request has no payload: the next byte is not read
    assert Device(link).rx_packet() == (Device.TX_REQ, size)
    assert link.incoming == b'\xaa'


def test_rx_packet_print():
    link = FakeLink(b'\x8d' + GREETING)
    assert Device(link).rx_packet() == (Device.PRINT, GREETING)
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


def test_rx_packet_detects_a_restarted_device():
    with pytest.raises(DeviceRestartedError):
        Device(FakeLink(HELLO)).rx_packet()


def test_rx_packet_rejects_hello_header_without_hello():
    with pytest.raises(RuntimeError, match='Received an invalid header: 0xda'):
        Device(FakeLink(b'\xda' + bytes(7))).rx_packet()


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
    link = FakeLink(b'\x8d' + GREETING + b'\x44')
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
