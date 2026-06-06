from __future__ import annotations

import anthropic

# Sonnet 4.5 host-side pricing (USD per million tokens). Both adapters share the
# same model and meter cost identically, so the rates live in one place.
INPUT_USD_PER_MTOK = 3.0
OUTPUT_USD_PER_MTOK = 15.0


def usage_cost_usd(usage: anthropic.types.Usage) -> float:
    return (
        usage.input_tokens * INPUT_USD_PER_MTOK + usage.output_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def message_text(message: anthropic.types.Message) -> str:
    return "\n".join(block.text for block in message.content if block.type == "text")


__all__ = [
    "INPUT_USD_PER_MTOK",
    "OUTPUT_USD_PER_MTOK",
    "message_text",
    "usage_cost_usd",
]
