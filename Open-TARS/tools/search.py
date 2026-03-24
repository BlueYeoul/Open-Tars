"""SEARCH — search Google for a query."""

import urllib.parse

NAME = "SEARCH"
DESCRIPTION = "Search Google for a query and load the results page."
REQUIRED = ["query"]
PARAMS = {
    "query": "Search terms in any language",
}
EXAMPLE = '<toolbox name="SEARCH" query="MacBook Pro M5 Pro 64GB price"/>'
WHEN_TO_USE = "Use whenever the exact URL is unknown, uncertain, or a previous URL attempt gave a 404."


def run(params: dict) -> list[dict]:
    url = "https://www.google.com/search?q=" + urllib.parse.quote(params["query"])
    return [
        {"type": "applescript", "code": 'tell application "Safari" to activate'},
        {"type": "wait", "seconds": 1},
        {"type": "hotkey", "keys": "cmd l"},
        {"type": "type", "text": url},
        {"type": "hotkey", "keys": "return"},
        {"type": "wait", "seconds": 3},
        {"type": "checkpoint"},
    ]
