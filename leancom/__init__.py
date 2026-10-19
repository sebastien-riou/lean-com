"""Host side of lean-com, a lightweight link between a host computer and an embedded device.

The device side is the header-only C library ``include/leancom.h``.
"""

import io
import logging
import os

try:
    from pysatl import Utils
except ModuleNotFoundError:

    class Utils:
        @staticmethod
        def hexstr(o):
            return str(o)


class DeviceRestartedError(RuntimeError):
    """The device restarted during the session: synchronize again and restart the sequence."""


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
        session_id (bytes): The id of the last handshake, see :meth:`synchronize`.
    """

    #: Header type of a transmit request, device to host (``COM_TX_REQ`` in C).
    TX_REQ = 0x40
    #: Header type of a debug print packet, device to host (``COM_PRINT`` in C).
    PRINT = 0x80
    #: Header type of a data packet, device to host (``COM_TO_HOST`` in C).
    RX_DATA = 0x00
    #: Header type of a data packet, host to device (``COM_TO_DEVICE`` in C).
    COM_TO_DEVICE = 0xC0

    #: Sent by the device when it starts the handshake (``_leancom_hello`` in C). Its last byte makes the host
    #: send :attr:`MAGIC` again; its first byte is an invalid packet header, so that a host in a running
    #: session detects a restarted device (:class:`DeviceRestartedError`).
    HELLO = bytes.fromhex('DA 42 65 83 2B A0 E6 AA')
    #: Sent by the host to open the handshake, followed by the session id (``_leancom_magic`` in C).
    MAGIC = bytes.fromhex('BC 02 9D 8A A7 3F')
    #: Sent by the device once it has received :attr:`MAGIC`, followed by the session id it received
    #: (``_leancom_ack`` in C).
    ACK = bytes.fromhex('2B D7 94 6C E1 38')
    #: Sent by the host once it has received :attr:`ACK` with its own session id; ends the handshake
    #: (``_leancom_go`` in C).
    GO = bytes.fromhex('93 4A E8 27 5C B1 F6 0E')
    #: Size of the session id that follows :attr:`MAGIC` and :attr:`ACK`.
    SESSION_ID_SIZE = 2

    def __init__(self, device):
        self.dev = device
        self.rxbuf = bytearray()
        self.session_id = None

    def synchronize(self, reset=None, session_id=None):
        """Perform the rendez-vous with the device.

        Call it once, before any transfer, while the device runs ``leancom_synchronize()``; either side may
        start first. Blocks until both sides are synchronized. The handshake skips stale bytes waiting in
        either direction, tolerates bytes lost while a side was not listening yet, and lets a host restarted
        at any moment join; see the synchronization section of the protocol documentation. It cannot
        resynchronize a device that is in its application: reset it first (``reset``), or have
        ``_leancom_error_handler()`` reset it.

        Args:
            reset: Called before the first byte is sent, to reset the device from the host (for example by
                pulsing DTR on a board wired for it). ``None`` to do nothing.
            session_id: The :attr:`SESSION_ID_SIZE` bytes identifying this handshake; drawn at random when
                ``None``. The id used is available as :attr:`session_id` afterwards.

        Raises:
            ValueError: ``session_id`` does not have :attr:`SESSION_ID_SIZE` bytes.
            RuntimeError: The transport returned no data (end of stream, or a transport with a timeout).
        """
        if session_id is None:
            session_id = os.urandom(self.SESSION_ID_SIZE)
        session_id = bytes(session_id)
        if len(session_id) != self.SESSION_ID_SIZE:
            raise ValueError('session_id must have %d bytes, got %d' % (self.SESSION_ID_SIZE, len(session_id)))
        self.session_id = session_id
        magic = self.MAGIC + session_id
        if reset is not None:
            logging.debug('sync: resetting the device')
            reset()
        if hasattr(self.dev, 'reset_input_buffer'):
            self.dev.reset_input_buffer()  # anything received so far is stale, or a HELLO we do not need
        logging.debug('sync: tx MAGIC %s' % Utils.hexstr(magic))
        self.dev.write(magic)
        window = bytearray()
        while True:
            r = self.dev.read(1)
            if not r:
                raise RuntimeError('Transport returned no data during the synchronization')
            logging.debug('sync: rx %s' % Utils.hexstr(r))
            window += r
            del window[:-8]
            if len(window) == 8 and window[:6] == self.ACK:
                if window[6:] == session_id:
                    break
                logging.debug('sync: ACK with a foreign id %s, tx MAGIC again' % Utils.hexstr(window[6:]))
                self.dev.write(magic)
            elif r == self.HELLO[-1:]:
                logging.debug('sync: end of HELLO, tx MAGIC again')
                self.dev.write(magic)
        logging.debug('sync: rx ACK, tx GO %s' % Utils.hexstr(self.GO))
        self.dev.write(self.GO)

    def rx_packet(self):
        """Receive one packet from the device.

        Low-level method: prints are returned, not displayed.

        Returns:
            tuple: ``(packet_type, data)``, where ``packet_type`` is :attr:`TX_REQ`,
            :attr:`PRINT` or :attr:`RX_DATA`. For :attr:`TX_REQ`, ``data`` is the number
            of bytes the device requests (int), otherwise it is the payload (bytes).

        Raises:
            DeviceRestartedError: The device sent its HELLO: it restarted.
            RuntimeError: The header has the host-to-device type (``0xC0``).
        """
        while True:
            header = int.from_bytes(self.dev.read(1), byteorder='little')
            packet_size = header & 0x3F
            if (header & 0xC0) == 0xC0:
                if header == self.HELLO[0]:
                    rest = self.dev.read(len(self.HELLO) - 1)
                    if rest == self.HELLO[1:]:
                        raise DeviceRestartedError('The device restarted: synchronize again and restart the sequence')
                    raise RuntimeError(
                        'Received an invalid header: 0x%02x (followed by %s)' % (header, Utils.hexstr(rest))
                    )
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
