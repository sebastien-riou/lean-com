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
   A session starts with a synchronization handshake, then carries packets. The
   handshake tolerates stale bytes, bytes lost while a side was not listening, and a
   host restarted at any moment. A running session cannot be resynchronized: reset
   the device, or let its error handler do it, and synchronize again.

.. _synchronization:

Synchronization
---------------

Both sides start with a handshake: ``leancom_synchronize()`` on the device,
:meth:`leancom.Device.synchronize` on the host. It works whichever side starts first,
skips stale bytes waiting in either direction, tolerates bytes lost while a side was
not listening yet, and lets a host restarted at any moment join. It leaves the two
byte streams aligned, so that the first packet follows it.

Frames
~~~~~~

The handshake uses four frames of 8 bytes:

.. list-table::
   :header-rows: 1

   * - Frame
     - Direction
     - Bytes
     - Python
     - C
   * - HELLO
     - device to host
     - ``DA 42 65 83 2B A0 E6 AA``
     - :attr:`~leancom.Device.HELLO`
     - ``_leancom_hello``
   * - MAGIC
     - host to device
     - ``BC 02 9D 8A A7 3F`` + session id
     - :attr:`~leancom.Device.MAGIC`
     - ``_leancom_magic``
   * - ACK
     - device to host
     - ``2B D7 94 6C E1 38`` + session id
     - :attr:`~leancom.Device.ACK`
     - ``_leancom_ack``
   * - GO
     - host to device
     - ``93 4A E8 27 5C B1 F6 0E``
     - :attr:`~leancom.Device.GO`
     - ``_leancom_go``

The session id is 2 bytes drawn at random by the host for each handshake, none of them
equal to the last byte of HELLO (in an ACK, such a byte would make the host send MAGIC
once more, harmlessly). The device copies the id it received into its ACK.

A side waiting for a frame keeps the last 8 bytes it received and compares them to the
frame after each byte: MAGIC and ACK are recognized when their 6-byte pattern sits at
the front of the window, with the id behind it; GO when the whole window equals it.
Everything else slides out and is discarded, which is what skips stale bytes and
partial frames. The constants are chosen so that no frame is recognized at a wrong
position inside the sequences each side sends, whatever the id: distinct bytes in each
pattern, no border, no match across frames. Each contains a byte above ``0x7F``, so
stale ASCII text never matches.

Sequence
~~~~~~~~

Device: if ``LEANCOM_RX_FLUSH`` is defined, discard the bytes already received; send
HELLO; wait for MAGIC and store the id; send ACK with that id; wait for GO. While
waiting for GO, a MAGIC with a different id is a restarted host: the device stores the
new id and sends ACK again. A MAGIC with the same id is a surplus copy, and slides out.

Host: draw an id; call the ``reset`` hook if given; empty the input buffer if the
transport can; send MAGIC; read byte by byte: an ACK with its own id ends the wait; an
ACK with another id (stale, or the device acknowledged a stale MAGIC) makes it send
MAGIC again; the last byte of HELLO (a whole HELLO, or only its tail when the port was
opened or flushed while HELLO was in flight) makes it send MAGIC again. Then send GO.

Whoever starts second sends to a peer that is already listening: a device started
second sends HELLO, which makes the host send MAGIC again; a host started second sends
MAGIC to a device that waits for it. Surplus copies of MAGIC carry the same id and all
precede GO, so the wait for GO drains them.

The device starts first, on a real port:

.. code-block:: text

   Host                                       Device
     |                                        |
     |<--- HELLO -----------------------------|   lost: the host has not opened its port yet
     |---- MAGIC id ------------------------->|   the host opens the port and starts
     |<--- ACK id ----------------------------|
     |---- GO ------------------------------->|   both sides are done
     |                                        |

The host starts first:

.. code-block:: text

   Host                                       Device
     |                                        |
     |---- MAGIC id ------------------------->|   lost: the device is in reset
     |<--- HELLO -----------------------------|   the device starts; its last byte triggers a new MAGIC
     |---- MAGIC id ------------------------->|
     |<--- ACK id ----------------------------|
     |---- GO ------------------------------->|
     |                                        |

A link that buffers (pseudo-terminal, pipe, USB), with stale bytes:

.. code-block:: text

   Host                                       Device
     |                                        |
     |<--- 55 55 -----------------------------|   stale, slide out on the host
     |<--- HELLO -----------------------------|   buffered until the host reads
     |---- MAGIC id ------------------------->|   sent before the host reads anything
     |<--- ACK id ----------------------------|
     |---- MAGIC id ------------------------->|   end of HELLO: a second copy, slides out on the device
     |---- GO ------------------------------->|
     |                                        |

The host restarts while the device waits for GO:

.. code-block:: text

   Host                                       Device
     |                                        |
     |---- MAGIC id1 ------------------------>|
     |<--- ACK id1 ---------------------------|   the host dies before sending GO
     |---- MAGIC id2 ------------------------>|   a new host, a new id
     |<--- ACK id2 ---------------------------|   the device acknowledges the new id
     |---- GO ------------------------------->|
     |                                        |

What it tolerates
~~~~~~~~~~~~~~~~~

- Stale bytes in either direction, whatever their content and number.
- HELLO or MAGIC lost or truncated: the other side sends again.
- Bytes overrun while the device transmits HELLO or ACK: only a surplus copy of MAGIC
  can be hit.
- A device reset at any point before it sends ACK.
- A host restart at any moment, even while the device waits for GO.

Against a peer sending random bytes, the host completes the handshake by chance with
probability 2\ :sup:`-64` per byte position (ACK followed by its own id), and the
device with about 2\ :sup:`-112` (MAGIC, then GO). Two hosts in a row drawing the same
id happens with probability 2\ :sup:`-16`; it only matters in the restart case above,
where the device then takes the new host for a surplus copy.

.. _sync-limitations:

What still needs attention
~~~~~~~~~~~~~~~~~~~~~~~~~~

- **The device resets after it sent ACK.** The host completes the handshake, then its
  next transfer receives HELLO and raises :class:`leancom.DeviceRestartedError`. Call
  :meth:`~leancom.Device.synchronize` again (the device waits for MAGIC) and restart
  the application sequence.
- **The device kept a complete MAGIC in its receive path across its own reset** (a
  receive buffer that is not reset with the core). Without the flush hook, the device
  acknowledges it; the live host, whose id differs, then gets its own ACK, unless a
  stale GO followed, in which case the device is in its application (next point).
  Define ``LEANCOM_RX_FLUSH`` to remove the case.
- **A running session cannot be resynchronized.** A device in its application reads
  the host's MAGIC as a packet with a bad header and calls ``_leancom_error_handler()``.
  If that handler resets the device, the session recovers by itself: the device sends
  HELLO and the host, still waiting for ACK, sends MAGIC again. Otherwise reset the
  device, for example from the host with the ``reset`` argument of
  :meth:`~leancom.Device.synchronize` (``--reset-dtr`` in the command line tool).
- ``_leancom_rx`` must keep receiving after an overrun error, as bytes may arrive while
  the device transmits.

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
  followed by a packet with the remainder. When the size is a multiple of 63, the last
  packet is a full one: no empty packet follows. A transfer of 0 bytes, or an empty
  print, sends nothing at all. The host nevertheless accepts empty data packets.
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

The host decodes the print packets as one UTF-8 stream and writes the text to stdout:
a character split between two packets, which always happens with ``leancom_putchar``
and can happen at 63-byte boundaries with ``leancom_print``, is displayed once its
last byte arrived. An invalid byte is displayed as U+FFFD.

Overhead
--------

After the handshake, and leaving prints aside, lean-com adds one header byte to each
packet of up to 63 bytes. Data going to the device costs in addition one request byte
per packet, and the host sends a packet only after the request for it arrived. The
tables below compare a transfer of ``N`` bytes with sending the same bytes raw on the
link, first by counting bytes, then on a typical setup. In both, ``k`` is the number
of packets: ``N / 63`` rounded up.

Bytes on the link
~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 14 34 30

   * - Transfer
     - Raw
     - lean-com
     - Overhead
   * - ``N`` bytes, device to host
     - ``N``
     - ``N + k``
     - ``k`` bytes: 1 byte up to 63 bytes, 1.6 % for large transfers
   * - ``N`` bytes, host to device
     - ``N``
     - ``N + k`` to the device, ``k`` to the host
     - ``2k`` bytes, and ``k`` round trips
   * - Round trips
     - none
     - ``k`` for host to device, none for device to host
     -

For example, 4 bytes cost 5 bytes to the host and 5 + 1 bytes to the device; 1024 bytes
(``k`` = 17) cost 1041 bytes to the host, or 1041 + 17 bytes to the device.

The round trips are what matters in practice. Only the first packet to the device is
usually free of them: the device sends its request when it calls ``leancom_rx_data()``,
which is normally before the host calls :meth:`~leancom.Device.tx`, so the request is
already in the host's buffer. Each following packet is sent after its request travelled
from the device to the host.

Typical setup: Linux host, FTDI USB cable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The model used for the figures below:

- The UART runs at ``B`` baud, 10 bits per byte: a byte takes ``t`` = 10 / ``B``, that is
  87 µs at 115200 baud and 8.7 µs at 1 Mbaud.
- The FTDI chip forwards received bytes to the host in USB packets of 62 data bytes. A
  partial packet is held until the chip's latency timer expires, 16 ms by default on
  Linux (``/sys/bus/usb-serial/devices/ttyUSB0/latency_timer``, minimum 1 ms; also 1 ms
  after ``setserial /dev/ttyUSB0 low_latency``). A lone byte, such as a request, waits
  between 0 and ``L`` = 16 ms, 8 ms on average.
- Bytes written by the host go out in the next USB frame, about 1 ms, then are clocked
  on the UART at ``B``.
- The Linux process and pyserial take well under a millisecond, which is ignored.

Raw communication pays the same link costs once: ``N`` × ``t`` on the UART, 1 ms to start
a write, and up to ``L`` for the tail of a transfer to the host to be forwarded.

.. list-table::
   :header-rows: 1
   :widths: 24 24 28 24

   * - Transfer
     - Raw
     - lean-com
     - Difference
   * - ``N`` bytes, device to host
     - ``N`` × ``t`` + up to ``L``
     - (``N`` + ``k``) × ``t`` + up to ``L``
     - ``k`` × ``t``, about 1.6 %; same latency
   * - up to 63 bytes, host to device, device already waiting
     - 1 ms + ``N`` × ``t``
     - 1 ms + (``N`` + 1) × ``t``
     - one byte time
   * - ``N`` bytes, host to device, several packets
     - 1 ms + ``N`` × ``t``
     - about ``k`` × (``L`` / 2 + 1 ms + 64 × ``t``)
     - one request latency and one USB frame per packet

Estimates from this model for 1024 bytes to the device (``k`` = 17), not measurements:

.. list-table::
   :header-rows: 1

   * - Setup
     - Raw
     - lean-com
   * - 115200 baud, ``L`` = 16 ms
     - 90 ms
     - about 250 ms, 2.8 times slower
   * - 115200 baud, ``L`` = 1 ms
     - 90 ms
     - about 120 ms, 1.3 times slower
   * - 1 Mbaud, ``L`` = 16 ms
     - 11 ms
     - about 160 ms, 15 times slower
   * - 1 Mbaud, ``L`` = 1 ms
     - 11 ms
     - about 35 ms, 3 times slower

The same 1024 bytes to the host take 90 ms raw and 91 ms with lean-com at 115200 baud.
So the cost of lean-com is concentrated on bulk transfers to the device, where the
latency timer of the cable dominates: lowering it to 1 ms is the single most effective
setting. Two details of the same origin: a full packet of 64 bytes spans two USB packets,
so its last 2 bytes wait for the latency timer when nothing follows; and the host sends
the header and the payload of a packet in two writes, which can land in two USB frames.

In exchange, the device needs no receive buffer and no flow control: it is never sent a
byte it has not asked for, which is what raw communication at these rates would require.
