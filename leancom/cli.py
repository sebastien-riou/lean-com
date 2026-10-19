"""Command line tool exchanging data with a lean-com device over a serial port."""

import argparse
import logging
import os
import time
import leancom
from pysatl import Utils
import serial


def pulse_dtr(port):
    """Pulse the DTR line of a serial port, to reset a board whose reset input is wired to it."""
    port.dtr = True
    time.sleep(0.1)
    port.dtr = False
    time.sleep(0.1)


def main():
    """Entry point of the ``leancom`` command."""
    scriptname = os.path.basename(__file__)
    parser = argparse.ArgumentParser(scriptname)
    levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    parser.add_argument('--log-level', default='INFO', choices=levels)
    parser.add_argument(
        '--reset-dtr',
        action='store_true',
        help='pulse the DTR line before synchronizing, to reset a board whose reset input is wired to it',
    )
    parser.add_argument('device', help='Path to the serial device', type=str)
    parser.add_argument('commands', help='rx<n bytes> or tx<hex data>', nargs='*', type=str)

    args = parser.parse_args()

    logformat = '%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'
    logdatefmt = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(level=args.log_level, format=logformat, datefmt=logdatefmt)

    logging.debug(f'args = {args}')

    with serial.Serial(args.device) as ser:
        device = leancom.Device(device=ser)
        device.synchronize(reset=(lambda: pulse_dtr(ser)) if args.reset_dtr else None)
        for command in args.commands:
            logging.debug(command)
            action = command[:2]
            match action:
                case 'rx':
                    size = int(command[2:])
                    logging.debug(f'RX {size} bytes')
                    data = device.rx(size)
                    print(Utils.hexstr(data))
                case 'tx':
                    data = Utils.ba(command[2:])
                    logging.debug(f'TX {len(data)} bytes: {Utils.hexstr(data)}')
                    device.tx(data)
                case _:
                    raise RuntimeError(f'Invalid command "{command}"')


if __name__ == '__main__':
    main()
