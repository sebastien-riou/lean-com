"""Host side of lean-com, a lightweight link between a host computer and an embedded device.

The device side is the header-only C library ``include/leancom.h``.
"""

import io
import logging

try:
    from pysatl import Utils
except ModuleNotFoundError:

    class Utils:
        @staticmethod
        def hexstr(o):
            return str(o)


class Device:
    """Host end of a lean-com link.

    Wraps the byte stream connected to the device and exposes the device's data
    channel as a file-like object. Debug prints sent by the device are written to
    stdout as they are received, which only happens while a transfer method runs.

    Args:
        device: Underlying transport, typically a ``serial.Serial``. It must provide
            ``read(size)``, ``write(data)`` and ``flush()``, and ``read(size)`` must
            block until ``size`` bytes are available (for ``serial.Serial``, keep the
            default ``timeout=None``).

    Attributes:
        dev: The underlying transport.
        rxbuf (bytearray): Data received from the device but not yet returned by :meth:`rx`.
    """

    #: Header type of a transmit request, device to host (``COM_TX_REQ`` in C).
    TX_REQ = 0x40
    #: Header type of a debug print packet, device to host (``COM_PRINT`` in C).
    PRINT = 0x80
    #: Header type of a data packet, device to host (``COM_TO_HOST`` in C).
    RX_DATA = 0x00
    #: Header type of a data packet, host to device (``COM_TO_DEVICE`` in C).
    COM_TO_DEVICE = 0xC0

    def __init__(self, device):
        self.dev = device
        self.rxbuf = bytearray()

    def synchronize(self):
        """Perform the rendez-vous with the device.

        Call it once, before any transfer, while the device runs ``leancom_synchronize()``.
        Blocks until both sides are synchronized. The handshake recovers from the loss of
        one byte but not from stale bytes already waiting in a receive buffer, see the
        synchronization section of the protocol documentation.
        """
        magic = 0xF2443FA78A9D02BC
        magic_bytes = magic.to_bytes(8, byteorder='little')
        cnt = 0
        while cnt < len(magic_bytes):
            t = magic_bytes[cnt : cnt + 1]
            logging.debug('sync: cnt = %d, tx %s' % (cnt, Utils.hexstr(t)))
            self.dev.write(t)
            r = self.dev.read(1)
            logging.debug('sync: cnt = %d, rx %s' % (cnt, Utils.hexstr(r)))
            hit = r[0] == magic_bytes[cnt]
            if cnt < len(magic_bytes) - 1:
                if not hit:
                    hit = r[0] == magic_bytes[cnt + 1]
                    if hit:
                        if cnt + 1 == len(magic_bytes) - 1:
                            t = magic_bytes[-1:]
                            logging.debug('sync: cnt = %d, tx %s' % (cnt, Utils.hexstr(t)))
                            self.dev.write(t)
                            break
            if hit:
                cnt += 1
            else:
                cnt = 0
        while True:
            r = self.dev.read(1)
            logging.debug('sync: rx %s (final loop)' % (Utils.hexstr(r)))
            if int(r[0]) == 1:
                logging.debug('sync: tx 1')
                self.dev.write(bytearray([1]))
                break
            else:
                logging.debug('sync: tx 0')
                self.dev.write(bytearray([0]))

    def rx_packet(self):
        """Receive one packet from the device.

        Low-level method: prints are returned, not displayed.

        Returns:
            tuple: ``(packet_type, data)``, where ``packet_type`` is :attr:`TX_REQ`,
            :attr:`PRINT` or :attr:`RX_DATA`. For :attr:`TX_REQ`, ``data`` is the number
            of bytes the device requests (int), otherwise it is the payload (bytes).

        Raises:
            RuntimeError: The header has the host-to-device type (``0xC0``).
        """
        while True:
            header = int.from_bytes(self.dev.read(1), byteorder='little')
            packet_size = header & 0x3F
            if (header & 0xC0) == 0xC0:
                raise RuntimeError('Received an invalid header: 0x%02x' % header)
            if header & self.TX_REQ:
                ptype = self.TX_REQ
                data = packet_size
            else:
                data = self.dev.read(packet_size)
                if header & self.PRINT:
                    ptype = self.PRINT
                else:
                    ptype = self.RX_DATA
            return ptype, data

    def tx(self, data):
        """Send data to the device.

        Serves the device's transmit requests until all of ``data`` is sent. The transfer
        may span several ``leancom_rx_data()`` calls on the device, but each request must
        fit in what remains of ``data``. Prints received meanwhile are written to stdout.

        Args:
            data: Bytes-like object to send.

        Raises:
            RuntimeError: The device sent data instead of requesting some, or requested
                more bytes than remain to be sent.
        """
        size = len(data)
        dat = io.BytesIO(data)
        while size > 0:
            logging.debug('tx: wait for packet from device')
            packet_type, packet_data = self.rx_packet()
            if packet_type == self.PRINT:
                print(packet_data.decode(), end='', flush=True)  # noqa T201
            if packet_type == self.RX_DATA:
                raise RuntimeError('Device is sending data (%s)' % Utils.hexstr(packet_data))
            if packet_type == self.TX_REQ:
                packet_size = packet_data
                logging.debug('tx: received TX_REQ, packet_size = %d' % packet_size)
                header = self.COM_TO_DEVICE | packet_size
                if packet_size > size:
                    raise RuntimeError('Device request more data (%d requested, %d available)' % (packet_size, size))
                size -= packet_size
                logging.debug('tx: sending header')
                self.dev.write(header.to_bytes(1, byteorder='little'))
                logging.debug('tx: sending data')
                self.dev.write(dat.read(packet_size))
                logging.debug('tx: done')

    def rx_core(self):
        """Receive the next data packet from the device.

        Prints received before it are written to stdout.

        Returns:
            bytes: The payload of the packet, 0 to 63 bytes.

        Raises:
            RuntimeError: The device sent a transmit request, so both sides wait for data.
        """
        while True:
            packet_type, data = self.rx_packet()
            if packet_type == self.TX_REQ:
                raise RuntimeError('Device is waiting for a packet')
            if packet_type == self.PRINT:
                print(data.decode(), end='', flush=True)  # noqa T201
            if packet_type == self.RX_DATA:
                return data

    def rx(self, size: int):
        """Receive exactly ``size`` bytes from the device.

        Packet boundaries are not preserved: bytes left over from a packet are kept in
        :attr:`rxbuf` and returned first by the next call. Prints received meanwhile are
        written to stdout.

        Args:
            size: Number of bytes to receive.

        Returns:
            bytearray: The received bytes.

        Raises:
            RuntimeError: The device sent a transmit request, so both sides wait for data.
        """
        out = bytearray()
        available = len(self.rxbuf)
        rxsize = 0
        if available > 0:
            out += self.rxbuf[0:available]
            self.rxbuf = self.rxbuf[available:]
            rxsize = available
        while size > rxsize:
            data = self.rx_core()
            out += data
            rxsize += len(data)
        excess = rxsize - size
        if excess:
            self.rxbuf += out[-excess:]
        return out[:size]

    def write(self, data):
        """Same as :meth:`tx`, for use as a file-like object. Returns ``None``."""
        self.tx(data)

    def read(self, size=1):
        """Same as :meth:`rx`, for use as a file-like object."""
        return self.rx(size)

    def flush(self):
        """Flush the underlying transport."""
        self.dev.flush()

    def readline(self):
        """Receive bytes up to the next newline character.

        Returns:
            bytes: The line, without its terminating newline (unlike ``io.IOBase.readline``).
        """
        out = bytearray()
        while True:
            c = self.rx(1)
            if c == b'\n':
                break
            out += c
        return bytes(out)
