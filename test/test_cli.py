"""The command line tool over a pseudo-terminal, the way Renode exposes a UART."""

import sys

import pytest

pytest.importorskip('termios')

from leancom import cli

pytestmark = pytest.mark.native

README_OUTPUT = 'hello world!\nhello world from printf over lean-com!\nFF EE DD CC\n'


def test_cli_basic_over_pty(pty_device, monkeypatch, capsys, clean_root_logger):
    """The session described in the README, with its output verbatim."""
    device = pty_device('basic_printf')
    monkeypatch.setattr(sys, 'argv', ['leancom', device.path, 'tx00112233', 'rx4'])
    device.run(cli.main)
    assert capsys.readouterr().out == README_OUTPUT
    assert device.wait() == 0


def test_cli_invalid_command(pty_device, monkeypatch, clean_root_logger):
    device = pty_device('basic')
    monkeypatch.setattr(sys, 'argv', ['leancom', device.path, 'zz'])
    with pytest.raises(RuntimeError, match='Invalid command "zz"'):
        device.run(cli.main)
