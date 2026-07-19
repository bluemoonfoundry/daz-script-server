# Sphinx configuration for dazpy documentation.

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# ── Project info ──────────────────────────────────────────────────────────────

project = "dazpy"
copyright = "2024, Blue Moon Foundry"
author = "Blue Moon Foundry"
release = "2.7.2"
version = release

# ── Extensions ────────────────────────────────────────────────────────────────

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

# ── autodoc settings ──────────────────────────────────────────────────────────

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}

autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
autoclass_content = "class"

suppress_warnings = ["ref.duplicate"]

# ── Napoleon (Google-style docstrings) ────────────────────────────────────────

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_attr_annotations = True

# ── Intersphinx ───────────────────────────────────────────────────────────────

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

# ── HTML output ───────────────────────────────────────────────────────────────

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
}

# ── General ───────────────────────────────────────────────────────────────────

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
templates_path = ["_templates"]
