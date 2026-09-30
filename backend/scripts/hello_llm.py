"""Phase 0 smoke test: send one message to the LLM and print the reply.

Run from the backend/ folder (with the virtual environment active):
    python -m scripts.hello_llm
"""

import logging
import sys

from langchain_core.messages import HumanMessage

from app.config import settings
from app.rag.llm import LLMError, invoke_llm, routed_model_id


def main() -> int:
    """Ask the LLM to say hello. Returns an exit code (0 = success, 1 = failure)."""
    logging.basicConfig(level=logging.WARNING)
    print(f"Asking {routed_model_id()} via Hugging Face Inference Providers...")
    try:
        reply = invoke_llm([HumanMessage(content="Say hello in one sentence.")])
    except LLMError as error:
        print(f"Error: {error}")
        return 1
    print(f"Reply: {reply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
