from __future__ import annotations


def tag_signal_mechanisms(signal: dict, mechanisms: list[dict]) -> list[str]:
    """Tag a signal with HF mechanisms.

    TODO: replace this keyword placeholder with LLM/tool-assisted tagging.
    """
    text = " ".join(str(signal.get(key, "")) for key in ("signal_name", "market_intuition", "hypothesis")).lower()
    tags: list[str] = []
    for item in mechanisms:
        mechanism_id = str(item.get("id", ""))
        name = str(item.get("name", "")).lower()
        if mechanism_id and (mechanism_id.lower() in text or name in text):
            tags.append(mechanism_id)
    return tags