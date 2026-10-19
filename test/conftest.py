"""Options, markers and fixtures of the test suite."""

import logging
import os
import sys

import harness
import pytest


def pytest_addoption(parser):
    group = parser.getgroup('leancom')
    group.addoption(
        '--device-timeout',
        type=float,
        default=5.0,
        metavar='SECONDS',
        help='time the host waits for the native device in one test before giving up; -1 = forever (default: 5)',
    )
    group.addoption(
        '--debug-friendly',
        action='store_true',
        help='disable every timeout for single-step debugging (same as --device-timeout -1); the tests that end '
        'only thanks to the timeout are skipped. LEANCOM_DEBUG_FRIENDLY=1 in the environment does the same.',
    )


def pytest_configure(config):
    if config.getoption('debug_friendly') or os.environ.get('LEANCOM_DEBUG_FRIENDLY') == '1':
        config.option.device_timeout = -1.0


def pytest_collection_modifyitems(config, items):
    no_timeout = config.getoption('device_timeout') < 0
    for item in items:
        if sys.platform == 'win32' and 'native' in item.keywords:
            item.add_marker(pytest.mark.skip(reason='the native device needs POSIX pipes and pseudo-terminals'))
        if no_timeout and 'needs_timeout' in item.keywords:
            item.add_marker(pytest.mark.skip(reason='ends only thanks to the device timeout, which is disabled'))


@pytest.fixture(scope='session')
def device_timeout(request):
    """Seconds the host waits for the device in one test, None when timeouts are disabled."""
    timeout = request.config.getoption('device_timeout')
    return None if timeout < 0 else timeout


@pytest.fixture(scope='session')
def device_binary(tmp_path_factory):
    """The native device, compiled once per session."""
    return harness.build_device(tmp_path_factory.mktemp('native'))


@pytest.fixture
def native_device(device_binary, device_timeout, tmp_path):
    """Factory: native_device(scenario, *, drop=0, timeout=None, **options) starts a device on pipes.

    drop=N discards the first N bytes the host writes (lost while the device was in reset); timeout shortens
    the deadline of this device (ignored when timeouts are disabled). All devices are ended at teardown.
    """
    started = []

    def start(scenario, *, drop=0, timeout=None, **options):
        stderr_path = tmp_path / f'device{len(started)}.stderr'
        deadline = device_timeout if timeout is None or device_timeout is None else timeout
        device = harness.NativeDevice(device_binary, scenario, options, deadline, stderr_path, drop=drop)
        started.append(device)
        return device

    yield start
    for device in started:
        device.close()


@pytest.fixture
def pty_device(device_binary, device_timeout, tmp_path):
    """Factory: pty_device(scenario, **options) starts a device behind a pseudo-terminal, see harness.PtyDevice."""
    started = []

    def start(scenario, **options):
        stderr_path = tmp_path / f'pty-device{len(started)}.stderr'
        device = harness.PtyDevice(device_binary, scenario, options, device_timeout, stderr_path)
        started.append(device)
        return device

    yield start
    for device in started:
        device.close()


@pytest.fixture
def clean_root_logger():
    """Undo what logging.basicConfig() did during the test (cli.main calls it)."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
    root.setLevel(level)
