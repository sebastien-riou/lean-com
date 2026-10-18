# Configuration file for the Sphinx documentation builder.
# See https://www.sphinx-doc.org/en/master/usage/configuration.html

from importlib.metadata import PackageNotFoundError, version as package_version

project = 'lean-com'
author = 'Sebastien Riou'
copyright = '2026, Sebastien Riou'  # noqa: A001

try:
    release = package_version('leancom')
except PackageNotFoundError:
    release = 'unknown'
version = release

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
]

autodoc_member_order = 'bysource'
napoleon_google_docstring = True
napoleon_numpy_docstring = False

exclude_patterns = ['_build']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']
