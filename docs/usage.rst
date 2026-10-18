Getting started
===============

A lean-com application has two programs that run in lock-step: the firmware on the
device, using the C library, and a script on the host, using :class:`leancom.Device`.
This page walks through the ``examples/basic`` application: the device prints a
greeting, receives 4 bytes, and sends them back inverted.

Device side
-----------

Include ``include/leancom.h`` in one C file of the firmware and define the three
functions the library needs from the platform:

.. code-block:: c

   #include "leancom.h"

   // Send exactly size bytes, blocking until done.
   void _leancom_tx(const void *const buf, unsigned int size){
     uart_write(buf, size);
   }
   // Receive exactly size bytes, blocking until done.
   void _leancom_rx(void *const buf, unsigned int size){
     uart_read(buf, size);
   }
   // Called on protocol errors, must not return.
   void _leancom_error_handler(uint32_t err_code){
     while(1);
   }

``uart_write`` and ``uart_read`` stand for the blocking byte-stream functions of your
platform. ``err_code`` is the line of ``leancom.h`` that detected the error. The
error that can happen in practice is the host answering a transmit request with a
packet of the wrong type or size, see :doc:`protocol`.

The application then uses the following functions:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Function
     - Purpose
   * - ``void leancom_synchronize(void)``
     - Rendez-vous with the host. Call it once, before any other function.
   * - ``void leancom_print(const char *s)``
     - Send a NUL-terminated string for the host to display.
   * - ``int leancom_putchar(int c)``
     - Send a single character for the host to display, to back ``printf``.
   * - ``void leancom_tx_data(const void *data, uint32_t size)``
     - Send ``size`` bytes to the host.
   * - ``void leancom_rx_data(void *data, uint32_t size)``
     - Receive ``size`` bytes from the host. Blocks until the host sends them.

The example application:

.. code-block:: c

   void basic_test(){
     leancom_synchronize();
     leancom_print("hello world!\n");
     uint8_t buf[4] = {0};
     leancom_rx_data(buf, sizeof(buf));
     for(unsigned int i = 0; i < sizeof(buf); i++){
       buf[i] = ~buf[i];
     }
     leancom_tx_data(buf, sizeof(buf));
     leancom_print("basic_test done.\n");
   }

To route ``printf`` through lean-com, make the C library's character output call
``leancom_putchar``. With the STM32 system calls used by the example, whose ``_write``
calls ``__io_putchar``, this is:

.. code-block:: c

   int __io_putchar(int ch){
     return leancom_putchar(ch);
   }

Each character then travels in its own packet, so ``leancom_print`` is more efficient
for long strings.

.. note::

   Limitations of the current C library:

   - It defines non-``static`` functions in the header, so include it from a single
     translation unit.
   - It assumes a little-endian device: the synchronization bytes and the character
     sent by ``leancom_putchar`` are taken from the in-memory representation of
     multi-byte integers.

Host side
---------

On the host, open the serial port, wrap it in a :class:`leancom.Device`, then mirror
the device's sequence of operations:

.. code-block:: python

   import serial
   import leancom

   with serial.Serial('/dev/ttyACM0', baudrate=115200) as ser:
       ser.reset_input_buffer()  # discard stale bytes, see the protocol page
       device = leancom.Device(ser)
       device.synchronize()
       device.tx(bytes.fromhex('00112233'))
       print(device.rx(4).hex(' '))

Output:

.. code-block:: text

   hello world!
   ff ee dd cc

The host displays the device's prints only while it runs a transfer. ``hello world!``
appears during :meth:`~leancom.Device.tx`, which receives the print while waiting for
the device's transmit request. ``basic_test done.`` is never displayed, because the
script makes no transfer after the device sends it.

Matching the two sides
~~~~~~~~~~~~~~~~~~~~~~

Each device operation has a host counterpart:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Device
     - Host
   * - ``leancom_synchronize()``
     - :meth:`~leancom.Device.synchronize`
   * - ``leancom_rx_data(buf, n)``
     - :meth:`~leancom.Device.tx` or :meth:`~leancom.Device.write`. One host call can
       serve several consecutive device calls; keep host calls aligned with device
       calls, because a transmit request larger than what remains of the host buffer
       raises :class:`RuntimeError`.
   * - ``leancom_tx_data(buf, n)``
     - :meth:`~leancom.Device.rx`, :meth:`~leancom.Device.read` or
       :meth:`~leancom.Device.readline`. The data is a stream: the host can read it
       in pieces of any size.
   * - ``leancom_print(s)``, ``printf``
     - Nothing: the next host transfer displays the text.

When the two sides disagree on the direction of the next transfer, the host detects it
and raises :class:`RuntimeError`:

- ``Device is waiting for a packet``: the host called ``rx`` while the device waits for
  data.
- ``Device is sending data (...)``: the host called ``tx`` while the device sends data.
- ``Device request more data (...)``: the device asked for more bytes than what
  remains of the buffer passed to ``tx``.

Transport requirements
~~~~~~~~~~~~~~~~~~~~~~

:class:`leancom.Device` accepts any object with ``read(size)``, ``write(data)`` and
``flush()`` methods. ``read(size)`` must block until ``size`` bytes are available: a
read returning fewer bytes is not detected and corrupts the stream. With
``serial.Serial``, keep the default ``timeout=None``. As a consequence, a call blocks
forever if the device stops responding.

As :class:`leancom.Device` has ``read``, ``write``, ``readline`` and ``flush`` methods,
it can itself serve as the transport of a higher-level protocol.
