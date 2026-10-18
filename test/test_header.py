"""Consistency of the copies of the C header."""

from harness import EXAMPLE_HEADER, HEADER


def test_example_header_is_identical_copy():
    assert HEADER.read_bytes() == EXAMPLE_HEADER.read_bytes(), f'{EXAMPLE_HEADER} differs from {HEADER}'
