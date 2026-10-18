# Known issues

Issues found while writing the documentation (October 2026). None is fixed yet. Each
entry gives the location, what happens, and a possible fix. Line numbers refer to the
code at the time of writing.

Severity: **High** breaks normal use, **Medium** breaks a plausible use or silently
corrupts data, **Low** is minor or affects tooling only.

| #  | Issue                                                        | Severity |
|----|--------------------------------------------------------------|----------|
| 1  | Synchronization never completes with stale bytes             | High     |
| 2  | The C library assumes a little-endian device                 | Medium   |
| 3  | `leancom.h` cannot be included from two C files              | Medium   |
| 4  | Non-ASCII prints abort the host                              | Medium   |
| 5  | Short reads from the transport are not detected              | Medium   |
| 6  | A zero-size `leancom_rx_data()` can hang                     | Low      |
| 7  | Command line tool: fixed baud rate, wrong program name       | Low      |
| 8  | The example's platform files are not tracked                 | High     |
| 9  | `buildit_env` and `testit_env` call a missing script         | Medium   |
| 10 | The example's `Pipfile` is invalid                           | Medium   |
| 11 | VS Code configurations refer to missing items                | Low      |
| 12 | The Renode test waits for output the firmware never sends    | Low      |
| 13 | Leftovers from the project template                          | Low      |

## Protocol and libraries

### 1. Synchronization never completes with stale bytes (High)

**Where:** `leancom_synchronize()` in [include/leancom.h](include/leancom.h#L96),
`Device.synchronize()` in [leancom/__init__.py](leancom/__init__.py#L50).

**What happens:** during the handshake, each side sends exactly one byte per byte it
receives. The only exception is the extra `M[7]` a side sends when it finds its peer
one byte ahead. The handshake can therefore make up for one missing byte, but cannot
drain surplus bytes:

- One byte lost, in either direction, for example the device's first magic byte sent
  before the host opened the port: recovered.
- Two or more bytes lost: both sides block in a read, forever.
- One or more stale bytes in a receive buffer when the handshake starts, for example
  left over from a previous session, sent by a boot loader, or produced by a line
  glitch at power-up: the handshake never completes, and both sides keep exchanging
  bytes forever.

**How it was checked:** the device code was compiled for the PC and connected to
`leancom.Device` through pipes. With one stale byte in either direction, the two sides
exchanged about 1.5 million bytes in 3 seconds without completing. With two lost
bytes, both sides blocked. A simulation of both algorithms gives the same results.

**Mitigation:** the documentation asks users to empty both receive paths before the
handshake: `reset_input_buffer()` on the host right before `synchronize()`; on the
device, discard received bytes before `leancom_synchronize()` and send nothing else
before it.

**Possible fix:** a fix needs a step in which one side can consume more bytes than it
sends, so that surplus bytes get drained. This changes the wire protocol on both
sides.

### 2. The C library assumes a little-endian device (Medium)

**Where:** [include/leancom.h:102](include/leancom.h#L102) (`(uint8_t*)&magic`) and
[include/leancom.h:72](include/leancom.h#L72) (`(const uint8_t*)&c`).

**What happens:** both functions take bytes from the in-memory representation of a
multi-byte integer. On a big-endian device:

- the magic bytes go out in reverse order, so the handshake never matches the Python
  host, which sends them in little-endian order;
- `leancom_putchar` sends the most significant byte of the `int`, `0x00`, instead of
  the character.

**Possible fix:** define the magic as a byte array
`{0xBC, 0x02, 0x9D, 0x8A, 0xA7, 0x3F, 0x44, 0xF2}`. In `leancom_putchar`, copy `c` into
a `uint8_t` and send that.

### 3. `leancom.h` cannot be included from two C files (Medium)

**Where:** [include/leancom.h:18-29](include/leancom.h#L18-L29).

**What happens:** `_leancom_rx8`, `_leancom_tx8` and `_leancom_raise_error` are defined
in the header without `static`. A program with two C files that include the header
fails to link with "multiple definition" errors (checked with gcc). The header also
has no include guard.

Related: with `-Wall`, a file that does not call `leancom_putchar` gets an
unused-function warning. `leancom_synchronize()` silences that warning for the other
functions, but not for this one.

**Possible fix:** declare the three functions `static` and add an include guard.

### 4. Non-ASCII prints abort the host (Medium)

**Where:** [leancom/__init__.py:141](leancom/__init__.py#L141) and
[leancom/__init__.py:173](leancom/__init__.py#L173) (`decode()` on each packet).

**What happens:** the host decodes each print packet as UTF-8 on its own. A
multi-byte character split between two packets raises `UnicodeDecodeError` out of
`tx()` or `rx()`, which ends the session. `leancom_putchar`, used by `printf`, sends
one byte per packet, so any non-ASCII character triggers it. `leancom_print` triggers
it when a character spans a 63-byte packet boundary.

**Possible fix:** decode with an incremental decoder stored in the `Device`
(`codecs.getincrementaldecoder('utf-8')(errors='replace')`), or write the raw bytes to
`sys.stdout.buffer`.

### 5. Short reads from the transport are not detected (Medium)

**Where:** [leancom/__init__.py:67](leancom/__init__.py#L67),
[leancom/__init__.py:106](leancom/__init__.py#L106),
[leancom/__init__.py:114](leancom/__init__.py#L114).

**What happens:** `Device` assumes that `read(n)` returns exactly `n` bytes. A
transport can return fewer, for example `serial.Serial` opened with a `timeout`. Then:

- `synchronize()` raises `IndexError` on an empty read;
- `rx_packet()` reads an empty result as header `0x00`, an empty data packet: `rx()`
  keeps polling, and `tx()` raises a misleading "Device is sending data" error;
- a short payload read returns fewer bytes than the header announced, and the
  following packets are misread.

**Possible fix:** read through a helper that loops until `n` bytes have arrived, and
raises a clear error at end of stream or on timeout.

### 6. A zero-size `leancom_rx_data()` can hang (Low)

**Where:** [include/leancom.h:43-44](include/leancom.h#L43-L44),
[leancom/__init__.py:137](leancom/__init__.py#L137).

**What happens:** `leancom_rx_data(buf, 0)` sends a request for 0 bytes and waits for
the answer. The host only answers it from within a `tx()` call that still has data to
send: `tx(b'')` returns at once without reading anything, and `rx()` raises
`RuntimeError`. Similarly, `leancom_tx_data(buf, 0)` sends an empty packet.

**Possible fix:** return immediately when the size is 0 in `leancom_rx_data()` and
`leancom_tx_data()`.

### 7. Command line tool: fixed baud rate, wrong program name (Low)

**Where:** [leancom/cli.py:13-14](leancom/cli.py#L13-L14),
[leancom/cli.py:28](leancom/cli.py#L28).

**What happens:**

- The serial port always opens at 9600 baud, the pyserial default, and no option
  changes it. This is fine for USB CDC-ACM ports and pseudo-terminals, but not for a
  physical UART at another rate.
- `--help` shows the program as `cli.py` instead of `leancom`, because the parser is
  named after the source file.

**Possible fix:** add a `--baudrate` option. Create the parser with
`argparse.ArgumentParser(prog='leancom')`.

## Example and tooling

### 8. The example's platform files are not tracked (High)

**Where:** [.gitignore:76](.gitignore#L76) (`target/`), `examples/basic/target/`.

**What happens:** the `target/` rule, from the Rust section of the template
`.gitignore`, also ignores `examples/basic/target/`. That directory holds the linker
scripts, startup code, CMake platform files and Renode scripts. `litex.cmake` and
`nucleo-u5a5zj-q.cmake` include files from it, so the example cannot be built or run
from a fresh clone.

**Fix:** remove the rule, or add `!examples/basic/target/` after it, then commit the
directory.

### 9. `buildit_env` and `testit_env` call a missing script (Medium)

**Where:** [examples/basic/buildit_env:5](examples/basic/buildit_env#L5),
[examples/basic/testit_env:9](examples/basic/testit_env#L9).

**What happens:** both scripts run `pipenv run ./build` from the top-level directory.
There, `build` is a build output directory, not a script; the script is `buildit`.
Both scripts stop at that line. The VS Code tasks *Build U5A5* and *Build RV32IC* run
`buildit_env`.

**Fix:** call `./buildit`.

### 10. The example's `Pipfile` is invalid (Medium)

**Where:** [examples/basic/Pipfile:15](examples/basic/Pipfile#L15).

**What happens:** the line `leancom` has no value, so the file is not valid TOML and
pipenv cannot read it. Every `pipenv` command run in `examples/basic` fails, including
those in `buildit_env` and `testit_env`.

**Fix:** give the package a source, for example `leancom = {path = "../..", editable = true}`.

### 11. VS Code configurations refer to missing items (Low)

**Where:** [.vscode/tasks.json:42-43](.vscode/tasks.json#L42-L43),
[.vscode/tasks.json:93-94](.vscode/tasks.json#L93-L94), `.vscode/launch.json`.

**What happens:**

- The tasks *Renode U5A5* and *Renode RV32IC* depend on a task labelled
  `Build application`, which does not exist. The build tasks are labelled
  *Build U5A5* and *Build RV32IC*. The *Dbg Renode* launch configurations, which the
  README uses to run the example, start these tasks.
- The launch configuration *Debug NUCLEO-U5A5ZJ-Q* points to `examples/whole_fw/`,
  which does not exist.

**Fix:** make each Renode task depend on the matching build task. Point the launch
configuration to `examples/basic/`.

### 12. The Renode test waits for output the firmware never sends (Low)

**Where:** [examples/basic/mytest.robot](examples/basic/mytest.robot).

**What happens:** the test waits up to 10 seconds for a line `END` on the device's
UART. The firmware never prints `END`. Moreover, with no host on the link, the
firmware blocks in `leancom_synchronize()`. This was found by reading the code; the
test was not run.

**Fix:** have the test play the host, for example by connecting `leancom` to the
Renode pseudo-terminal, and check the host's output instead.

### 13. Leftovers from the project template (Low)

- `hatch.toml`: the `lint` environment checks a package named `usbman`.
- `__main__.spec`: the PyInstaller executable is named `usbman`.
- `pyproject.toml`: isort's `known-first-party` is `hdrbg`. The project URLs point to
  `github.com/sebastien-riou/leancom`, while the repository is `lean-com`. The author
  email is empty.
- `buildit`: a comment refers to `.github/workflows/build.yml`, which does not exist.
- `examples/basic/expected_output.txt` (the text of *Le Petit Prince*) and its
  checksum file are not used anywhere.
