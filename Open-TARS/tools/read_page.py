"""READ_PAGE — extract visible content from the current page."""

NAME = "READ_PAGE"
DESCRIPTION = "Extract specific visible content from the current page and save to memory."
REQUIRED = ["target", "save_to"]
PARAMS = {
    "target": "Description of what to extract (e.g. 'current stock price and change')",
    "save_to": "Memory key to store the result under",
}
EXAMPLE = '<toolbox name="READ_PAGE" target="current AAPL stock price" save_to="aapl_price"/>'
WHEN_TO_USE = "Use when the target content is visible on the current page. Navigate first if needed."


def run(params: dict) -> list[dict]:
    return [
        {"type": "read", "target": params["target"], "save_to": params["save_to"]},
        {"type": "checkpoint"},
    ]
