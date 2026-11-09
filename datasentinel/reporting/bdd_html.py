"""Branded version of the standard behave HTML report (behave-html-formatter).

The stock formatter is excellent but anonymous; subclassing only to change the title/heading
keeps all of its behaviour (and future upgrades) while showing the framework name.
Registered as the `html` formatter in behave.ini.
"""
from behave_html_formatter.html import HTMLFormatter

from datasentinel.branding import NAME, TAGLINE, VERSION


class BrandedHTMLFormatter(HTMLFormatter):
    # The base class reads this class attribute for both <title> and the page <h1>.
    title = f"{NAME} v{VERSION} - BDD Report ({TAGLINE})"
