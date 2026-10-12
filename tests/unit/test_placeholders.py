import pytest

from bankrec.parsers.placeholders import contains_placeholder, is_placeholder


@pytest.mark.parametrize(
    "v",
    [
        "NaN",
        "NaN%",
        "$",
        " $ ",
        "--",
        "—",
        "{{apy}}",
        "${rate}",
        "Loading",
        "loading...",
        "",
        None,
        "undefined",
        "%",
    ],
)
def test_placeholders(v: str | None) -> None:
    assert is_placeholder(v)


@pytest.mark.parametrize("v", ["4.00%", "$95", "None", "0%", "No annual fee"])
def test_not_placeholders(v: str) -> None:
    assert not is_placeholder(v)


def test_inline_placeholders() -> None:
    assert contains_placeholder("APY: NaN%")
    assert contains_placeholder("APR $ Variable")
    assert contains_placeholder("Rate {{rate}}")
    assert not contains_placeholder("APR 19.99% Variable")
    assert not contains_placeholder("Annual fee $95")
