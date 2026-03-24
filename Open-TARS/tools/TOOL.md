# Open-TARS Tool Reference

Tools are invoked using `<toolbox name="TOOL_NAME" param="value"/>` syntax.
New tools can be added by placing a Python script in the `tools/` directory.

---

## OPEN_URL
Navigate Safari to an exact, confirmed URL.

**Use when:** You know with certainty the URL exists and is correct.
**Do NOT use when:** URL is uncertain — use SEARCH instead.

| Param | Required | Description |
|-------|----------|-------------|
| url   | ✅       | Full URL starting with https:// or http:// |

```
<toolbox name="OPEN_URL" url="https://finance.yahoo.com/quote/AAPL"/>
```

---

## SEARCH
Search Google and load results.

**Use when:** The exact URL is unknown, unconfirmed, or a previous URL returned 404.
**Works for:** Any language query. Google handles Korean, Japanese, etc.

| Param | Required | Description |
|-------|----------|-------------|
| query | ✅       | Search terms in any language |

```
<toolbox name="SEARCH" query="MacBook Pro M5 Pro 64GB price"/>
<toolbox name="SEARCH" query="맥북 프로 M5 Pro 64GB 가격"/>
```

---

## READ_PAGE
Extract specific visible content from the current page and save to memory.

**Use when:** Target content is visible on screen. Scroll or navigate first if not visible.
**Result:** Saved to memory under `save_to` key for use in later steps.

| Param   | Required | Description |
|---------|----------|-------------|
| target  | ✅       | What to extract (e.g. "current price and percentage change") |
| save_to | ✅       | Memory key for the result |

```
<toolbox name="READ_PAGE" target="current AAPL stock price and change" save_to="aapl_price"/>
```

---

## Adding a New Tool

Create `tools/<toolname>.py` with:
```python
NAME = "TOOL_NAME"          # used in <toolbox name="..."/>
REQUIRED = ["param1"]       # required parameter names
DESCRIPTION = "..."
EXAMPLE = '<toolbox name="TOOL_NAME" param1="..."/>'

def run(params: dict) -> list[dict]:
    # return list of atomic actions
    return [{"type": "...", ...}]
```

The tool is automatically registered on next run. Add its documentation to this file.
