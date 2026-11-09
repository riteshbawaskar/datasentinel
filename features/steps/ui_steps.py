"""Step definitions: Playwright UI automation.

Selectors are Playwright selectors: CSS ("#id", ".class", "table tr"), text ("text=Save"),
role ("role=button[name='Save']") or data attributes ("[data-testid=submit]").
Every UI scenario should carry the @ui tag. A browser is only launched when the first UI step
runs, so non-UI scenarios in the same run pay nothing.

Assertions use Playwright's auto-retrying `expect`, so they wait up to `timeout_ms`
(config/ui.yml) for the page to reach the expected state instead of failing instantly.
"""
from behave import given, then, when

from datasentinel.bdd import checkpoint
from datasentinel.config_loader import ConfigError
from datasentinel.connectors import fetch_dataset
from datasentinel.ui.browser import resolve_url
from datasentinel.ui.session import get_manager, get_page


def _expect():
    """Import Playwright's `expect` lazily (Playwright is optional for non-UI users)."""
    try:
        from playwright.sync_api import expect
    except ImportError as exc:
        raise ConfigError("Playwright is not installed: pip install playwright && "
                          "playwright install chromium") from exc
    return expect


def _assert_ui(context, name, expected, check):
    """Run a Playwright expectation and record it as a checkpoint.

    `check` is a zero-arg callable that raises AssertionError on failure; the message becomes the
    checkpoint's explanation (Playwright's messages already include expected vs actual text).
    """
    try:
        check()
    except AssertionError as exc:
        checkpoint(context, name, False, expected, "see message", str(exc).strip().splitlines()[0][:300])
    except Exception as exc:                                    # timeouts, closed pages ...
        checkpoint(context, name, False, expected, type(exc).__name__, str(exc).strip().splitlines()[0][:300])
    else:
        checkpoint(context, name, True, expected, "as expected")


# ----------------------------------------------------------------------- navigation
@given('I open the page "{url}"')
def step_open(context, url):
    page = get_page(context)
    target = resolve_url(url, get_manager(context).settings.base_url)
    page.goto(target)
    context.store.info("Page", target)


# ----------------------------------------------------------------------- actions
@when('I click "{selector}"')
def step_click(context, selector):
    get_page(context).click(selector)


@when('I fill "{selector}" with "{value}"')
def step_fill(context, selector, value):
    get_page(context).fill(selector, value)


@when('I select "{option}" from "{selector}"')
def step_select(context, option, selector):
    get_page(context).select_option(selector, label=option)


@when('I wait for "{selector}" to be visible')
def step_wait(context, selector):
    get_page(context).wait_for_selector(selector, state="visible")


@when('I take a screenshot named "{name}"')
def step_screenshot(context, name):
    # Embedded (base64) into the standalone HTML report.
    context.store.attach_image(name, get_page(context).screenshot(full_page=True))


# ----------------------------------------------------------------------- assertions
@then('the page title should be "{title}"')
def step_title(context, title):
    _assert_ui(context, "Page title", title, lambda: _expect()(get_page(context)).to_have_title(title))


@then('the element "{selector}" should be visible')
def step_visible(context, selector):
    _assert_ui(context, f"{selector} is visible", "visible",
               lambda: _expect()(get_page(context).locator(selector).first).to_be_visible())


@then('the element "{selector}" should contain the text "{text}"')
def step_contains(context, selector, text):
    _assert_ui(context, f"{selector} contains text", text,
               lambda: _expect()(get_page(context).locator(selector).first).to_contain_text(text))


@then('the element "{selector}" should have the value "{value}"')
def step_value(context, selector, value):
    _assert_ui(context, f"{selector} has value", value,
               lambda: _expect()(get_page(context).locator(selector).first).to_have_value(value))


@then('there should be {count:d} elements matching "{selector}"')
def step_count(context, count, selector):
    _assert_ui(context, f"{selector} count", str(count),
               lambda: _expect()(get_page(context).locator(selector)).to_have_count(count))


# ------------------------------------------------------- UI vs database cross-check
@then('the text of "{selector}" should equal the value returned by "{query}" on connection "{connection}"')
def step_text_equals_query(context, selector, query, connection):
    """Compare a single on-screen value with the first cell of a database query.

    Numbers are compared numerically ("1,234.50" == 1234.5) so display formatting is ignored.
    """
    ui_text = get_page(context).locator(selector).first.inner_text().strip()
    db_value = str(fetch_dataset({"connection": connection, "query": query}).iloc[0, 0]).strip()

    def _num(v):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return v
    checkpoint(context, f"UI value of {selector} equals database value", _num(ui_text) == _num(db_value),
               f"{db_value} (database)", f"{ui_text} (UI)")
