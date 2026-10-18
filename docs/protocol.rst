Protocol
========

This page specifies the protocol between the host, which runs the ``leancom`` Python
package, and the device, which runs the C library ``include/leancom.h``, down to the
bytes on the wire.

Overview
--------

Transport
   Any full-duplex byte stream that delivers bytes in order, without loss or
   corruption, once both ends run: a UART, a USB CDC-ACM port, a pseudo-terminal.
   lean-com adds no checksum, acknowledgement or retransmission.

Roles
   The device drives the session. After synchronization, the host sends data only
   when the device requests it, and exactly the amount requested. The device can
   therefore read its input with plain blocking calls, and never has to buffer
   bytes it did not ask for.

Phases
   A session starts with a synchronization handshake, then carries packets. A
   running session cannot be resynchronized: to start a new one, restart the
   device and synchronize again.

.. _synchronization:

Synchronization
---------------

Both sides start with a handshake: ``leancom_synchronize()`` on the device,
:meth:`leancom.Device.synchronize` on the host. It works whichever side starts first,
and leaves the two byte streams aligned so that the first packet follows it.

The handshake uses an 8-byte magic sequence ``M``, the 64-bit constant
``0xF2443FA78A9D02BC`` in little-endian byte order:

.. code-block:: text

   M[0..7] = BC 02 9D 8A A7 3F 44 F2

Phase 1: magic exchange
~~~~~~~~~~~~~~~~~~~~~~~

Both sides run the same algorithm, with an index ``i`` starting at 0:

1. Send ``M[i]``, then receive a byte ``r``.
2. If ``r == M[i]``, increment ``i``.
3. Otherwise, if ``i < 7`` and ``r == M[i+1]``, the peer is one byte ahead, typically
   because its first byte was lost. Increment ``i``. If ``i`` is now 7, send ``M[7]``
   and leave phase 1.
4. Otherwise, set ``i`` to 0.
5. Leave phase 1 when ``i`` reaches 8, otherwise go back to step 1.

Phase 2: confirmation
~~~~~~~~~~~~~~~~~~~~~

The two sides now play different roles:

- The device sends ``01`` and receives a byte, and repeats until it receives ``01``.
- The host receives a byte. If it is ``01``, the host answers ``01`` and stops;
  otherwise it answers ``00`` and repeats.

In the nominal case, each direction carries the same 9 bytes:

.. code-block:: text

   host to device:  BC 02 9D 8A A7 3F 44 F2 01
   device to host:  BC 02 9D 8A A7 3F 44 F2 01

Recovery of a lost byte
~~~~~~~~~~~~~~~~~~~~~~~

A typical case: the device boots first and sends ``BC`` before the host opens the
port, so the host never receives it (``--`` below). From then on, the host receives
each magic byte while it expects the previous one, which step 3 accepts. When it
receives ``F2`` at ``i = 6``, the host sends the ``F2`` the device waits for and moves
to phase 2:

.. code-block:: text

   device sends:     BC 02 9D 8A A7 3F 44 F2 01
   host receives:    -- 02 9D 8A A7 3F 44 F2 01
   host sends:       BC 02 9D 8A A7 3F 44 F2 01
   device receives:  BC 02 9D 8A A7 3F 44 F2 01

The host sends that ``F2`` without having received a byte for it: this extra byte
replaces the lost one.

.. _sync-limitations:

Limitations
~~~~~~~~~~~

During the handshake, each side sends one byte per byte it receives, except for the
extra ``M[7]`` of step 3. The handshake can therefore make up for one missing byte,
but it cannot drain extra ones:

- **One lost byte**, in either direction: recovered, as shown above.
- **Two or more lost bytes**: both sides end up waiting for a byte that never comes.
- **Stale bytes** already in a receive buffer when the handshake starts, left over
  from a previous session or sent by a boot loader on the same port: the handshake
  never completes, and both sides keep exchanging bytes.

Make sure that both receive paths are empty when the handshake starts:

- On the host, call ``reset_input_buffer()`` on the serial port right before
  :meth:`~leancom.Device.synchronize`. At worst it discards the first magic byte of
  the device, which the handshake recovers.
- On the device, discard any byte received before ``leancom_synchronize()``, and send
  nothing else on the port before it.

Packets
-------

After synchronization, every byte belongs to a packet. A packet is a header byte,
followed by a payload unless it is a transmit request:

.. code-block:: text

   bit    7     6     5     4     3     2     1     0
       +-----------+-----------------------------------+
       |   type    |              length               |
       +-----------+-----------------------------------+

.. list-table::
   :header-rows: 1

   * - Header
     - Name in C
     - Direction
     - Payload
     - Meaning
   * - ``00`` to ``3F``
     - ``COM_TO_HOST``
     - device to host
     - ``length`` bytes
     - Data for the host.
   * - ``40`` to ``7F``
     - ``COM_TX_REQ``
     - device to host
     - none
     - Request for ``length`` bytes.
   * - ``80`` to ``BF``
     - ``COM_PRINT``
     - device to host
     - ``length`` bytes
     - Text to display.
   * - ``C0`` to ``FF``
     - ``COM_TO_DEVICE``
     - host to device
     - ``length`` bytes
     - Data for the device.

The Python constants :attr:`~leancom.Device.RX_DATA`, :attr:`~leancom.Device.TX_REQ`,
:attr:`~leancom.Device.PRINT` and :attr:`~leancom.Device.COM_TO_DEVICE` hold the
corresponding type bits.

Rules:

- ``length`` is 0 to 63. The device splits a longer transfer into packets of 63 bytes
  followed by a packet with the remainder. When the size is a non-zero multiple of 63,
  the last packet is a full one: no empty packet follows.
- The device sends data, text and requests whenever its application calls
  ``leancom_tx_data``, ``leancom_print`` (or ``leancom_putchar``) and
  ``leancom_rx_data``.
- The host sends a data packet only to answer a request, with the same ``length``.
  The device checks the type and length of the answer, and calls
  ``_leancom_error_handler()`` if they differ.
- Packets are not acknowledged, and data packets do not delimit messages: the host
  treats the data from the device as a stream.

Examples
~~~~~~~~

The exchange of the ``examples/basic`` application after synchronization, in which
text payloads are shown as strings:

.. code-block:: text

   Host                              Device
     |                                  |
     |<--- 8D "hello world!\n" ---------|   print, 13 bytes
     |<--- 44 --------------------------|   request for 4 bytes
     |---- C4 00 11 22 33 ------------->|   data, 4 bytes
     |<--- 04 FF EE DD CC --------------|   data, 4 bytes
     |<--- 91 "basic_test done.\n" -----|   print, 17 bytes
     |                                  |

A 100-byte transfer in each direction, ``leancom_rx_data(buf, 100)`` followed by
``leancom_tx_data(buf, 100)`` on the device:

.. code-block:: text

   Host                              Device
     |                                  |
     |<--- 7F --------------------------|   request for 63 bytes
     |---- FF + 63 bytes -------------->|   data, 63 bytes
     |<--- 65 --------------------------|   request for 37 bytes
     |---- E5 + 37 bytes -------------->|   data, 37 bytes
     |<--- 3F + 63 bytes ---------------|   data, 63 bytes
     |<--- 25 + 37 bytes ---------------|   data, 37 bytes
     |                                  |

Host behavior
-------------

:class:`leancom.Device` handles each packet from the device according to the
transfer in progress:

.. list-table::
   :header-rows: 1

   * - Packet received
     - During ``tx(data)``
     - During ``rx(size)``
   * - Print
     - Display it, continue.
     - Display it, continue.
   * - Request for ``n`` bytes
     - Send ``C0 | n`` and the next ``n`` bytes; raise :class:`RuntimeError` if fewer
       than ``n`` bytes remain.
     - Raise :class:`RuntimeError`: both sides wait for data.
   * - Data
     - Raise :class:`RuntimeError`: both sides send data.
     - Keep it. Return once ``size`` bytes are available; keep the excess for the next
       call.
   * - Header ``C0`` to ``FF``
     - Raise :class:`RuntimeError`.
     - Raise :class:`RuntimeError`.

``tx(data)`` returns once all of ``data`` is sent; ``tx(b'')`` returns immediately.

The host decodes each print packet as UTF-8 on its own, and writes it to stdout. A
multi-byte character split between two packets fails to decode, and the transfer
raises :class:`UnicodeDecodeError`. This always happens
with ``leancom_putchar``, and can happen at 63-byte boundaries with ``leancom_print``.
Keep device prints to ASCII.
