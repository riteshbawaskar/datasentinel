"""Single source of truth for the framework's identity.

Anything user-visible (HTML reports, JSON results, console banner) imports the
name from here, so renaming the framework is a one-line change.
"""

NAME = "DataSentinel"
TAGLINE = "Data comparison, validation and UI verification, driven by BDD"
VERSION = "1.1.0"

# Plain-text banner printed by the parallel runner.
BANNER = f"{NAME} v{VERSION} - {TAGLINE}"
