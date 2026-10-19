# Known issues

Issues found while writing the documentation (October 2026). The table and the heading of each
entry give its status. Each entry gives the location, what happens, and the fix applied or
possible. Line numbers refer to the code at the time of writing.

Severity: **High** breaks normal use, **Medium** breaks a plausible use or silently
corrupts data, **Low** is minor or affects tooling only.

| #  | Issue                                                     | Severity | Fixed  |
|----|-----------------------------------------------------------|----------|--------|
| 1  | Synchronization never completes with stale bytes          | High     | yes    |
| 2  | The C library assumes a little-endian device              | Medium   | yes    |
| 3  | `leancom.h` cannot be included from two C files           | Medium   | yes    |
| 4  | Non-ASCII prints abort the host                           | Medium   | yes    |
| 5  | Short reads from the transport are not detected           | Medium   | yes    |
| 6  | A zero-size `leancom_rx_data()` can hang                  | Low      | yes    |
| 7  | Command line tool: fixed baud rate, wrong program name    | Low      | yes    |
| 8  | The example's platform files are not tracked              | High     | yes    |
| 9  | `buildit_env` and `testit_env` call a missing script      | Medium   | yes    |
| 10 | The example's `Pipfile` is invalid                        | Medium   | yes    |
| 11 | VS Code configurations refer to missing items             | Low      | yes    |
| 12 | The Renode test waits for output the firmware never sends | Low      | no     |
| 13 | Leftovers from the project template                       | Low      | partly |

## Protocol and libraries

### 1. Synchronization never completes with stale bytes (High, fixed)

**Where:** `leancom_synchronize()` in [include/leancom.h](include/leancom.h),
`Device.synchronize()` in [leancom/__init__.py](leancom/__init__.py).

**What happened:** during the handshake, each side sent exactly one byte per byte it
received, with one extra byte in a recovery branch. The handshake could make up for one
missing byte, but could not drain surplus bytes:

- One byte lost, in either direction: recovered.
- Two or more bytes lost: both sides blocked in a read, forever.
- One or more stale bytes in a receive buffer when the handshake started (left over from
  a previous session, sent by a boot loader, a line glitch at power-up): the handshake
  never completed, and both sides kept exchanging bytes forever.

**How it was checked:** the device code compiled for the PC and connected to
`leancom.Device` through pipes. With one stale byte in either direction, the two sides
exchanged about 1.5 million bytes in 3 seconds without completing. With two lost bytes,
both sides blocked. A simulation of both algorithms gave the same results.

**Fix:** the handshake was replaced by the announce / match / ack / go sequence described
in the protocol documentation: four 8-byte frames, a sliding window on each side that
discards everything but the expected frame, a session id that lets a restarted host
join, and a final phase that drains surplus bytes. Stale bytes in either direction,
lost bytes and host restarts are tolerated; a device reset during a session is reported
as `DeviceRestartedError`; the optional `_leancom_rx_flush()` hook covers data retained
in the device across its own reset; `synchronize(reset=...)` and `--reset-dtr` reset the
device from the host. The former xfail tests are now regular tests in
`test/test_native.py`, and `test/syncsim.py` models both state machines.

### 2. The C library assumes a little-endian device (Medium, fixed)

**Where:** `leancom_synchronize()` and `leancom_putchar()` in [include/leancom.h](include/leancom.h).

**What happened:** both functions took bytes from the in-memory representation of a
multi-byte integer. On a big-endian device, the magic bytes went out in reverse order,
so the handshake never matched the Python host, and `leancom_putchar` sent the most
significant byte of the `int`, `0x00`, instead of the character.

**Fix:** the handshake frames are byte arrays, and `leancom_putchar` copies the character
into a `uint8_t` before sending it.

### 3. `leancom.h` cannot be included from two C files (Medium, fixed)

**Where:** `_leancom_rx8`, `_leancom_tx8` and `_leancom_raise_error` in
[include/leancom.h](include/leancom.h).

**What happened:** the three functions were defined in the header without `static`, so a
program with two C files including the header failed to link with "multiple definition"
errors. The header also had no include guard.

**Fix:** the three functions are `static`, like the rest of the header, and the header has
an include guard. `test_header_in_two_translation_units` links two files that include it.
The compile flag `-Wno-unused-function` that the test harness needed is gone too.

### 4. Non-ASCII prints abort the host (Medium, fixed)

**Where:** the display of print packets in [leancom/__init__.py](leancom/__init__.py).

**What happened:** the host decoded each print packet as UTF-8 on its own. A multi-byte
character split between two packets raised `UnicodeDecodeError` out of `tx()` or `rx()`,
which ended the session. `leancom_putchar`, used by `printf`, sends one byte per packet,
so any non-ASCII character triggered it; `leancom_print` triggered it when a character
spanned a 63-byte packet boundary.

**Fix:** the print packets are decoded as one stream by an incremental UTF-8 decoder kept
in the `Device`, so a split character is displayed once complete; an invalid byte is
displayed as U+FFFD instead of raising.

### 5. Short reads from the transport are not detected (Medium, fixed)

**Where:** the reads of [leancom/__init__.py](leancom/__init__.py).

**What happened:** `Device` assumed that `read(n)` returned exactly `n` bytes. A transport
could return fewer, for example `serial.Serial` opened with a `timeout`: `synchronize()`
raised `IndexError` on an empty read, `rx_packet()` read an empty result as header
`0x00`, and a short payload read left the following packets misread.

**Fix:** every read goes through `Device._read()`, which loops until the expected bytes
arrived and raises `RuntimeError` when the transport returns nothing (end of stream, or
timeout).

### 6. A zero-size `leancom_rx_data()` can hang (Low, fixed)

**Where:** `leancom_rx_data()`, `leancom_tx_data()` and `leancom_print()` in
[include/leancom.h](include/leancom.h).

**What happened:** `leancom_rx_data(buf, 0)` sent a request for 0 bytes and waited for
the answer. The host only answered it from within a `tx()` call that still had data to
send: `tx(b'')` returned at once without reading anything, and `rx()` raised
`RuntimeError`. Similarly, `leancom_tx_data(buf, 0)` sent an empty packet.

**Fix:** `leancom_rx_data()`, `leancom_tx_data()` and `leancom_print()` return immediately
when the size is 0, so nothing goes on the wire; the host keeps accepting empty data
packets. Tested by `test_zero_size_transfers_send_nothing` and the size 0 of `test_echo`.

### 7. Command line tool: fixed baud rate, wrong program name (Low, fixed)

**Where:** [leancom/cli.py](leancom/cli.py).

**What happened:** the serial port always opened at 9600 baud, the pyserial default, and no
option changed it. `--help` showed the program as `cli.py` instead of `leancom`, because
the parser was named after the source file.

**Fix:** `--baudrate` (default 9600, unchanged behaviour), and the parser is created with
`prog='leancom'`.

## Example and tooling

### 8. The example's platform files are not tracked (High, fixed)

**Where:** `.gitignore` (`target/`), `examples/basic/target/`.

**What happened:** the `target/` rule, from the Rust section of the template
`.gitignore`, also ignored `examples/basic/target/`. That directory holds the linker
scripts, startup code, CMake platform files and Renode scripts. `litex.cmake` and
`nucleo-u5a5zj-q.cmake` include files from it, so the example could not be built or run
from a fresh clone.

**Fix:** `!examples/basic/target/` added after the rule and the directory committed
(commit f9057ad).

### 9. `buildit_env` and `testit_env` call a missing script (Medium, fixed)

**Where:** [examples/basic/buildit_env](examples/basic/buildit_env),
[examples/basic/testit_env](examples/basic/testit_env).

**What happened:** both scripts ran `pipenv run ./build` from the top-level directory.
There, `build` is a build output directory, not a script; the script is `buildit`. Both
scripts stopped at that line. The VS Code tasks *Build U5A5* and *Build RV32IC* run
`buildit_env`.

**Fix:** they call `./buildit`. Not run here (they need the cross toolchain and Renode).

### 10. The example's `Pipfile` is invalid (Medium, fixed)

**Where:** [examples/basic/Pipfile](examples/basic/Pipfile).

**What happened:** the line `leancom` had no value, so the file was not valid TOML and
pipenv could not read it. Every `pipenv` command run in `examples/basic` failed,
including those in `buildit_env` and `testit_env`.

**Fix:** `leancom = {path = "../..", editable = true}`: the example uses the checkout.
The scripts still force-install the freshly built wheel on top of it.

### 11. VS Code configurations refer to missing items (Low, fixed)

**Where:** `.vscode/tasks.json`, `.vscode/launch.json`.

**What happened:** the tasks *Renode U5A5* and *Renode RV32IC* depended on a task
labelled `Build application`, which did not exist (the build tasks are *Build U5A5* and
*Build RV32IC*), and the launch configuration *Debug NUCLEO-U5A5ZJ-Q* pointed to
`examples/whole_fw/`, which does not exist.

**Fix:** each Renode task depends on its matching build task, and the launch
configuration points to `examples/basic/`.

### 12. The Renode test waits for output the firmware never sends (Low)

**Where:** [examples/basic/mytest.robot](examples/basic/mytest.robot).

**What happens:** the test waits up to 10 seconds for a line `END` on the device's
UART. The firmware never prints `END`. Moreover, with no host on the link, the
firmware blocks in `leancom_synchronize()`. This was found by reading the code; the
test was not run.

**Fix:** have the test play the host, for example by connecting `leancom` to the
Renode pseudo-terminal, and check the host's output instead.

**Status:** open. Such a test has to be designed and checked against Renode.

### 13. Leftovers from the project template (Low, partly fixed)

Fixed: `hatch.toml` named a package `usbman`, `__main__.spec` named the PyInstaller
executable `usbman`, isort's `known-first-party` in `pyproject.toml` was `hdrbg`, the
project URLs pointed to `github.com/sebastien-riou/leancom` instead of `lean-com`, and a
comment in `buildit` referred to a GitHub workflow that does not exist. The empty author
email in `pyproject.toml` was removed: an author entry needs only a name.

Left as they are:

- `examples/basic/expected_output.txt` (the text of *Le Petit Prince*) and its checksum
  file are not used anywhere; their purpose is unknown.
