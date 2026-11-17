"""A minimal external content package, used by `tests/test_content.py`.

It adds one module and one kit to the built-in preset `pressure` (from the folder
`content/` inside the package), and, through a callable, content for a preset that
is not installed, which the toolkit ignores. It is registered through
`../mpc_iml_example_content-0.1.0.dist-info/entry_points.txt`.
"""

from mpc_iml.content import Content

CONTENT = Content(preset="pressure", root="mpc_iml_example_content:content")


def ghost_content() -> Content:
    """Content for a preset that is not installed; its broken kit is never read."""
    return Content(preset="not-installed", root="mpc_iml_example_content:content")
