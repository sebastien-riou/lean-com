Command line tool
=================

The ``leancom`` command opens a serial port, synchronizes with the device, then runs
a sequence of transfers given on the command line. It is meant for quick tests and
for exploring a device without writing a host script.

Synopsis
--------

.. code-block:: text

   leancom [-h] [--log-level LEVEL] device [command ...]

The same tool runs with ``python -m leancom`` or ``python -m leancom.cli``.

Arguments
---------

.. program:: leancom

.. option:: device

   Path of the serial port, for example ``/dev/ttyACM0``, ``COM3`` or the
   pseudo-terminal created by an emulator such as ``/tmp/leancom-uart``.

.. option:: command

   A transfer, run in order after synchronization:

   ``rx<n>``
      Receive ``n`` bytes from the device and print them in hexadecimal.
   ``tx<hex>``
      Send the bytes given as a hexadecimal string, for example ``tx00112233``.

   Commands are checked only when reached: an invalid one aborts the tool with an
   exception after the previous ones have run.

.. option:: --log-level LEVEL

   One of ``DEBUG``, ``INFO`` (default), ``WARNING``, ``ERROR`` and ``CRITICAL``.
   ``DEBUG`` logs every byte of the synchronization and every step of the transfers.

Prints from the device are displayed while transfers run, see :doc:`usage`.

The serial port uses the pyserial defaults: 9600 baud, 8 data bits, no parity, one
stop bit, no flow control. The baud rate does not matter for USB CDC-ACM ports and
pseudo-terminals; for a physical UART at another rate, use the Python API.

Example
-------

With the ``examples/basic`` firmware running in Renode, which exposes the device's
UART as ``/tmp/leancom-uart``:

.. code-block:: console

   $ leancom /tmp/leancom-uart tx00112233 rx4
   hello world!
   hello world from printf over lean-com!
   FF EE DD CC

The device inverts the 4 bytes it receives and sends them back.
