Development
===========

Example firmware
----------------

``examples/basic`` holds the application described in :doc:`usage`. Build it for the
NUCLEO-U5A5ZJ-Q board:

.. code-block:: console

   cd examples/basic
   ./buildit nucleo-u5a5zj-q.cmake debug

Run it in Renode with the VS Code launch configuration *Dbg Renode U5A5*. Renode
exposes the device's UART as the pseudo-terminal ``/tmp/leancom-uart``. Then, from the
top-level directory:

.. code-block:: console

   pipenv run python -m leancom.cli /tmp/leancom-uart tx00112233 rx4

The VS Code launch configuration *Python basic* runs the same command in the debugger.
The expected output is:

.. code-block:: text

   hello world!
   hello world from printf over lean-com!
   FF EE DD CC

Tests
-----

The test suite runs on the development machine alone: no board, no Renode, no serial port. It
compiles ``include/leancom.h`` with the machine's C compiler into a small stand-in device, and drives
it with the Python package through pipes and a pseudo-terminal. From the top-level directory:

.. code-block:: console

   ./testit

The first run creates a virtual environment in ``build/test-venv`` with pytest. Options go to pytest:

.. code-block:: console

   ./testit -k sync               # a selection of tests
   ./testit -m 'not native'       # the pure Python tests only, no C compiler needed
   ./testit --debug-friendly      # no timeouts, for single-step debugging

The tests in which the two sides wait for each other are bounded by a timeout, 5 seconds by default
(``--device-timeout`` changes it). ``--debug-friendly`` disables it, and skips the tests that only end
thanks to it; ``LEANCOM_DEBUG_FRIENDLY=1`` in the environment of a VS Code debug configuration has the
same effect. ``CC`` selects the C compiler (default ``cc``) and ``CFLAGS`` adds compiler flags.

A known bug listed in ``ISSUES.md`` gets a test marked as a strict expected failure, which reports
a failure once the bug is fixed, as a reminder to remove the mark.

Linting
-------

The ``lint`` script formats the code with black and checks it with ruff:

.. code-block:: console

   pipenv run ./lint

Documentation
-------------

The documentation is built with Sphinx, and published on Read the Docs according to
``.readthedocs.yaml``. To build it locally, from the top-level directory:

.. code-block:: console

   ./build-doc

Then open ``docs/_build/html/index.html``. The first run creates a virtual environment
in ``build/doc-venv`` with the documentation dependencies. Warnings are errors, as on
Read the Docs. Extra options go to ``sphinx-build``, for example ``./build-doc -n``
for nitpicky mode.
