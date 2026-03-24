"""LLM API client and prompt loader."""

import json
import urllib.request
import urllib.error
from pathlib import Path

API_URL = "http://localhost:1234/api/v1/chat"
MODEL = "qwen3.5-9b-mlx"
PROMPTS_DIR = Path(__file__).parent / "prompts"


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
    for item in data["output"]:
        if item.get("type") == "message":
            return item["content"].replace("<|im_end|>", "").strip()
    return data["output"][-1]["content"].replace("<|im_end|>", "").strip()
