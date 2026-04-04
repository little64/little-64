project = "Little-64"
author = "Little-64 contributors"

extensions = [
    "myst_parser",
]

source_suffix = {
    ".md": "markdown",
}

master_doc = "index"
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

myst_heading_anchors = 3

html_theme = "furo"
html_title = "Little-64 Documentation"
