Installation
============

Requirements
------------

- Python 3.10 or newer.
- `pysatl <https://pypi.org/project/pysatl/>`_ and
  `pyserial <https://pypi.org/project/pyserial/>`_, installed automatically.

The package is installed from its git repository.

With pip
--------

.. code-block:: console

   pip install git+https://github.com/sebastien-riou/lean-com.git

A specific release can be selected with a tag, for example
``git+https://github.com/sebastien-riou/lean-com.git@v0.0.4``.

With pipenv
-----------

In the working directory of your project (run ``touch Pipfile`` first if it has no
pipenv environment yet):

.. code-block:: console

   pipenv install git+https://github.com/sebastien-riou/lean-com.git

The resulting entry in the ``Pipfile`` looks like this:

.. code-block:: toml

   leancom = {git = "git+https://github.com/sebastien-riou/lean-com.git"}

As a git submodule
------------------

The repository can also be added as a submodule. This gives access to the C header
``include/leancom.h`` for the device firmware, and to the Python package for the host.

Checking the installation
-------------------------

.. code-block:: console

   leancom --help
