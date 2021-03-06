"""Tests that need to be run under `fil-profile python`.

To run:

$ fil-profile python -m pytest python-benchmarks/fil-interpreter.py
"""

import sys
import os
from ctypes import c_void_p
import re
from pathlib import Path

import pytest
import numpy as np
import numpy.core.numeric
from pampy import _ as ANY, match
from IPython.core.displaypub import CapturingDisplayPublisher
from IPython.core.interactiveshell import InteractiveShell

from filprofiler._tracer import preload, start_tracing, stop_tracing
from filprofiler._testing import get_allocations, big, as_mb
from pymalloc import pymalloc


def test_no_profiling():
    """Neither memory tracking nor Python profiling happen by default."""
    address = pymalloc(365)
    # No information about size available, since it's not tracked:
    assert preload.pymemprofile_get_allocation_size(c_void_p(address)) == 0
    assert sys.getprofile() is None


def test_temporary_profiling(tmpdir):
    """Profiling can be run temporarily."""
    start_tracing(tmpdir)

    def f():
        arr = np.ones((1024, 1024, 4), dtype=np.uint64)  # 32MB

    f()
    stop_tracing(tmpdir)

    # Allocations were tracked:
    path = ((__file__, "f", 39), (numpy.core.numeric.__file__, "ones", ANY))
    allocations = get_allocations(tmpdir)
    assert match(allocations, {path: big}, as_mb) == pytest.approx(32, 0.1)

    # Profiling stopped:
    test_no_profiling()


def run_in_ipython_shell(code_cells):
    """Run a list of strings in IPython.

    Returns parsed allocations.
    """
    InteractiveShell.clear_instance()

    shell = InteractiveShell.instance(display_pub_class=CapturingDisplayPublisher)
    for code in code_cells:
        shell.run_cell(code)
    InteractiveShell.clear_instance()
    html = shell.display_pub.outputs[-1]["data"]["text/html"]
    assert "<iframe" in html
    [svg_path] = re.findall('src="([^"]*)"', html)
    assert svg_path.endswith("peak-memory.svg")
    resultdir = Path(svg_path).parent.parent

    return get_allocations(resultdir)


def test_ipython_profiling(tmpdir):
    """Profiling can be run via IPython magic."""
    cwd = os.getcwd()
    os.chdir(tmpdir)
    allocations = run_in_ipython_shell(
        [
            "%load_ext filprofiler",
            """\
%%filprofile
import numpy as np
arr = np.ones((1024, 1024, 4), dtype=np.uint64)  # 32MB
""",
        ]
    )

    # Allocations were tracked:
    path = (
        (re.compile("<ipython-input-1-.*"), "__magic_run_with_fil", 3),
        (numpy.core.numeric.__file__, "ones", ANY),
    )
    assert match(allocations, {path: big}, as_mb) == pytest.approx(32, 0.1)

    # Profiling stopped:
    test_no_profiling()


def test_ipython_exception_while_profiling(tmpdir):
    """
    Profiling can be run via IPython magic, still profiles and shuts down
    correctly on an exception.

    This will log a RuntimeError. That is expected.
    """
    cwd = os.getcwd()
    os.chdir(tmpdir)
    allocations = run_in_ipython_shell(
        [
            "%load_ext filprofiler",
            """\
%%filprofile
import numpy as np
arr = np.ones((1024, 1024, 2), dtype=np.uint64)  # 16MB
raise RuntimeError("The test will log this, it's OK.")
arr = np.ones((1024, 1024, 8), dtype=np.uint64)  # 64MB
""",
        ]
    )

    # Allocations were tracked:
    path = (
        (re.compile("<ipython-input-1-.*"), "__magic_run_with_fil", 3),
        (numpy.core.numeric.__file__, "ones", ANY),
    )
    assert match(allocations, {path: big}, as_mb) == pytest.approx(16, 0.1)

    # Profiling stopped:
    test_no_profiling()


def test_ipython_non_standard_indent(tmpdir):
    """
    Profiling can be run via IPython magic, still profiles and shuts down
    correctly on an exception.

    This will log a RuntimeError. That is expected.
    """
    cwd = os.getcwd()
    os.chdir(tmpdir)
    allocations = run_in_ipython_shell(
        [
            "%load_ext filprofiler",
            """\
%%filprofile
import numpy as np
def f():  # indented with 5 spaces what
     arr = np.ones((1024, 1024, 2), dtype=np.uint64)  # 16MB
f()
""",
        ]
    )

    # Allocations were tracked:
    path = (
        (re.compile("<ipython-input-1-.*"), "__magic_run_with_fil", 5),
        (re.compile("<ipython-input-1-.*"), "f", 4),
        (numpy.core.numeric.__file__, "ones", ANY),
    )
    assert match(allocations, {path: big}, as_mb) == pytest.approx(16, 0.1)

    # Profiling stopped:
    test_no_profiling()
