import io,sys
import logging
try:
    import serial
except:
    print("ERROR: Please install pyserial package. For example:\n\t%s -m pip install pyserial"%sys.executable)
    sys.exit(-1)
try:
    from pysatl import Utils
except:
    class Utils:
        @staticmethod
        def hexstr(o):
            return str(o)

class Device(object):
    TX_REQ = 0x40
    PRINT =  0x80
    RX_DATA = 0x00
    COM_TO_DEVICE = 0xC0
    def __init__(self,device):
        self.dev = device
        self.rxbuf = bytearray()

    def synchronize(self):
        magic = 0xF2443FA78A9D02BC
        magic_bytes = magic.to_bytes(8,byteorder='little')
        cnt=0
        hit_next = False
        while cnt < len(magic_bytes):
            t = magic_bytes[cnt:cnt+1]
            logging.debug("sync: cnt = %d, tx %s"%(cnt,Utils.hexstr(t)))
            self.dev.write(t)
            r = self.dev.read(1)
            logging.debug("sync: cnt = %d, rx %s"%(cnt,Utils.hexstr(r)))
            hit = r[0] == magic_bytes[cnt]
            hit_next = False
            if cnt < len(magic_bytes)-1:
                if not hit:
                    hit = r[0] == magic_bytes[cnt+1]
                    if hit:
                        hit_next = True
                        logging.debug("sync: hit next")
                        if cnt+1 == len(magic_bytes)-1:
                            t = magic_bytes[-1:]
                            logging.debug("sync: cnt = %d, tx %s"%(cnt,Utils.hexstr(t)))
                            self.dev.write(t)
                            break;
            if hit:
                cnt += 1
            else:
                cnt = 0
        while True:
            r = self.dev.read(1)
            logging.debug("sync: rx %s (final loop)"%(Utils.hexstr(r)))
            if int(r[0]) == 1:
                logging.debug("sync: tx 1")
                self.dev.write(bytearray([1]))
                break
            else:
                logging.debug("sync: tx 0")
                self.dev.write(bytearray([0]))

    def rx_packet(self):
        while(True):
            header = int.from_bytes(self.dev.read(1),byteorder='little')
            packet_size = header & 0x3f
            if (header & 0xC0) == 0xC0:
                raise RuntimeError("Received an invalid header: 0x%02x"%header)
            if header & self.TX_REQ:
                ptype = self.TX_REQ
                data = packet_size
            else:
                data = self.dev.read(packet_size)
                if header & self.PRINT:
                    ptype = self.PRINT
                else:
                    ptype = self.RX_DATA
            return ptype,data

    def tx(self, data):
        size = len(data)
        dat = io.BytesIO(data)
        while(size > 0):
            logging.debug("tx: wait for packet from device")
            packet_type,packet_data = self.rx_packet()
            if packet_type == self.PRINT:
                print(packet_data.decode(),end="",flush=True)
            if packet_type == self.RX_DATA:
                raise RuntimeError("Device is sending data (%s)"%Utils.hexstr(packet_data))
            if packet_type == self.TX_REQ:
                packet_size = packet_data
                logging.debug("tx: received TX_REQ, packet_size = %d"%packet_size)
                header = self.COM_TO_DEVICE|packet_size
                if packet_size > size:
                    raise RuntimeError("Device request more data (%d requested, %d available)"%(packet_size,size))
                size -= packet_size
                logging.debug("tx: sending header")
                self.dev.write(header.to_bytes(1,byteorder='little'))
                logging.debug("tx: sending data")
                self.dev.write(dat.read(packet_size))
                logging.debug("tx: done")

    def rx_core(self):
        while(True):
            packet_type,data = self.rx_packet()
            if packet_type == self.TX_REQ:
                raise RuntimeError("Device is waiting for a packet")
            if packet_type == self.PRINT:
                print(data.decode(),end="",flush=True)
            if packet_type == self.RX_DATA:
                return data
            
    def rx(self, size:int):
        out = bytearray()
        available = len(self.rxbuf)
        rxsize = 0
        if available > 0:
            out += self.rxbuf[0:available]
            self.rxbuf = self.rxbuf[available:]
            rxsize = available
        while(size > rxsize):
            data = self.rx_core()
            out += data
            rxsize += len(data)
        excess = rxsize - size
        if excess:
            self.rxbuf += out[-excess:]
        return out[:size]
    