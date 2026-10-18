lean-com
========

lean-com is a small library for communication between an embedded device and a
host computer over a byte stream such as a UART, a USB CDC-ACM port or an emulator's
pseudo-terminal.

It has two halves:

- the **host side**, the ``leancom`` Python package documented here, which also
  provides a command line tool;
- the **device side**, the header-only C library ``include/leancom.h``.

Features:

- **Rendez-vous**: synchronization of host and device.
- **Data transfer**: bi-directional transfer of binary data.
- **Debug prints**: strings sent by the device are displayed by the host, and the
  C library can back ``printf``.

The device drives every exchange: the host only sends data the device has asked for.
The device therefore never receives unsolicited bytes, and needs neither receive
buffers nor interrupts, only blocking functions that send and receive bytes.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   installation
   usage
   cli
   protocol
   api
   development
