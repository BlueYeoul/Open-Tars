"""OPEN_URL — navigate Safari to a confirmed URL."""

NAME = "OPEN_URL"
DESCRIPTION = "Navigate Safari to an exact, confirmed URL."
REQUIRED = ["url"]
PARAMS = {
    "url": "Full URL starting with https:// or http://",
}
EXAMPLE = '<toolbox name="OPEN_URL" url="https://finance.yahoo.com/quote/AAPL"/>'
WHEN_TO_USE = "Use only when you are certain the URL exists. For unknown URLs, use SEARCH instead."


def run(params: dict) -> list[dict]:
    return [
        {"type": "applescript", "code": 'tell application "Safari" to activate'},
        {"type": "wait", "seconds": 1},
        {"type": "hotkey", "keys": "cmd l"},
        {"type": "type", "text": params["url"]},
        {"type": "hotkey", "keys": "return"},
        {"type": "wait", "seconds": 3},
        {"type": "checkpoint"},
    ]
