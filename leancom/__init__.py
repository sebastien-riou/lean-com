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
    TX_REQ = 0x40
    PRINT = 0x80
    RX_DATA = 0x00
    COM_TO_DEVICE = 0xC0

    def __init__(self, device):
        self.dev = device
        self.rxbuf = bytearray()

    def synchronize(self):
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
        while True:
            packet_type, data = self.rx_packet()
            if packet_type == self.TX_REQ:
                raise RuntimeError('Device is waiting for a packet')
            if packet_type == self.PRINT:
                print(data.decode(), end='', flush=True)  # noqa T201
            if packet_type == self.RX_DATA:
                return data

    def rx(self, size: int):
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
        self.tx(data)

    def read(self, size=1):
        return self.rx(size)

    def flush(self):
        self.dev.flush()

    def readline(self):
        out = bytearray()
        while True:
            c = self.rx(1)
            if c == b'\n':
                break
            out += c
        return bytes(out)
