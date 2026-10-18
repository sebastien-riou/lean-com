"""Known bugs, listed in ISSUES.md.

Each test describes the desired behaviour and is expected to fail. When a bug gets fixed, its test passes,
the strict xfail reports a failure, and the marker is to be removed.
"""

import subprocess

import pytest
from harness import DeviceTimeoutError, compile_c

pytestmark = pytest.mark.native

QUERY = bytes.fromhex('00112233')
ANSWER = bytes.fromhex('ffeeddcc')


def run_basic(device):
    device.host.synchronize()
    device.host.tx(QUERY)
    assert device.host.rx(4) == ANSWER
    assert device.wait() == 0


@pytest.mark.needs_timeout
@pytest.mark.xfail(
    strict=True,
    raises=DeviceTimeoutError,
    reason='ISSUES.md #1: a stale byte from the device makes the synchronization loop forever',
)
def test_sync_with_stale_byte_from_device(native_device):
    run_basic(native_device('basic', garbage=1))


@pytest.mark.needs_timeout
@pytest.mark.xfail(
    strict=True,
    raises=DeviceTimeoutError,
    reason='ISSUES.md #1: a stale byte from the host makes the synchronization loop forever',
)
def test_sync_with_stale_byte_from_host(native_device):
    device = native_device('basic')
    device.transport.write(b'\x55')
    run_basic(device)


@pytest.mark.needs_timeout
@pytest.mark.xfail(
    strict=True, raises=DeviceTimeoutError, reason='ISSUES.md #1: two lost bytes make both sides wait forever'
)
def test_sync_with_two_lost_device_bytes(native_device):
    device = native_device('basic')
    assert device.transport.read(2) == b'\xbc\x02'
    run_basic(device)


@pytest.mark.xfail(
    strict=True, raises=subprocess.CalledProcessError, reason='ISSUES.md #3: leancom.h defines non-static functions'
)
def test_header_in_two_translation_units(tmp_path):
    a = tmp_path / 'a.c'
    b = tmp_path / 'b.c'
    a.write_text('#include "leancom.h"\nvoid a(void){ leancom_synchronize(); }\n')
    b.write_text(
        '#include "leancom.h"\n'
        'void a(void);\n'
        'void _leancom_tx(const void *const buf, unsigned int size){ (void)buf; (void)size; }\n'
        'void _leancom_rx(void *const buf, unsigned int size){ (void)buf; (void)size; }\n'
        'void _leancom_error_handler(uint32_t err_code){ (void)err_code; }\n'
        'int main(void){ a(); return 0; }\n'
    )
    compile_c([a, b], tmp_path / 'two', check=False).check_returncode()


@pytest.mark.xfail(
    strict=True, raises=UnicodeDecodeError, reason='ISSUES.md #4: a character split between two print packets'
)
def test_print_utf8_split_across_packets(native_device, capsys):
    device = native_device('print_utf8')
    device.host.synchronize()
    assert device.host.rx(1) == b'\x42'
    assert device.wait() == 0
    assert capsys.readouterr().out == 'a' * 62 + 'é\n'


@pytest.mark.xfail(
    strict=True, raises=RuntimeError, reason='ISSUES.md #6: a zero-size leancom_rx_data() is never answered'
)
def test_rx_zero_size_then_data(native_device):
    device = native_device('rx_zero')
    device.host.synchronize()
    device.host.tx(b'')
    assert device.host.rx(1) == b'\x42'
    assert device.wait() == 0
