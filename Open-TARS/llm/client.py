"""LLM API client and prompt loader with token tracking."""

import json
import urllib.request
import urllib.error
from pathlib import Path

API_URL = "http://localhost:1234/api/v1/chat"
# MODEL = "qwen3.5-4b-mlx"
MODEL = "qwen3.5-9b-mlx"
# MODEL = "qwen3.5-35b-a3b"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ── Token tracking ──
_token_counter = {"prompt": 0, "completion": 0, "total": 0}
_token_callback = None   # set by TUI to receive updates


def set_token_callback(fn):
    """Register a callback fn(total_tokens) called after each LLM call."""
    global _token_callback
    _token_callback = fn


def get_token_usage() -> dict:
    """Return cumulative token usage."""
    return dict(_token_counter)


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt from prompts/<name>.md, substituting {key} placeholders.

    Uses plain str.replace per key — safe against JSON examples or any other
    literal braces in the template that aren't registered placeholders.
    """
    text = (PROMPTS_DIR / f"{name}.md").read_text()
    for key, value in kwargs.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def call_llm(system: str, text: str, image: str = None, timeout: int = 180) -> str:
    """Call the local LLM. image should be a data URI string if provided."""
    if image:
        inp = [{"type": "image", "data_url": image}, {"type": "text", "content": text}]
    else:
        inp = text
    payload = {"model": MODEL, "system_prompt": system, "input": inp}
    req = urllib.request.Request(
        API_URL,
        json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read().decode())

    # ── Extract token usage if provided ──
    usage = data.get("usage", {})
    if usage:
        _token_counter["prompt"] += usage.get("prompt_tokens", 0)
        _token_counter["completion"] += usage.get("completion_tokens", 0)
        _token_counter["total"] += usage.get("total_tokens", 0)
    else:
        # Rough estimate: count content length as proxy
        prompt_est = len(system) // 4 + len(text) // 4
        _token_counter["prompt"] += prompt_est

    # Notify callback
    if _token_callback:
        try:
            _token_callback(_token_counter["total"])
        except Exception:
            pass

    for item in data["output"]:
        if item.get("type") == "message":
            content = item["content"].replace("<|im_end|>", "").strip()
            # Estimate completion tokens if not in usage
            if not usage:
                comp_est = len(content) // 4
                _token_counter["completion"] += comp_est
                _token_counter["total"] += comp_est + (len(system) // 4 + len(text) // 4)
                if _token_callback:
                    try:
                        _token_callback(_token_counter["total"])
                    except Exception:
                        pass
            return content
    content = data["output"][-1]["content"].replace("<|im_end|>", "").strip()
    return content
