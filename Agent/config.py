from __future__ import annotations

import os
from pathlib import Path


class Config:
    """Runtime configuration for the LangChain AzureChatOpenAI demo."""

    # Matches the names you provided in your snippet
    INFERENCE_MODEL: str = ""
    OPENAI_API_VERSION: str = ""
    OPENAI_API_URL: str = ""
    OPENAI_API_KEY: str = ""

    @classmethod
    def _load_dotenv(cls) -> None:
        """Best-effort .env loading (does not override real env vars)."""
        try:
            from dotenv import load_dotenv  # type: ignore
        except Exception:
            return

        root = Path(__file__).resolve().parent
        for name in [".env", ".env.local", ".env.development"]:
            p = root / name
            if p.exists():
                load_dotenv(dotenv_path=p, override=False)

        # Also allow python-dotenv to walk up from CWD if user runs elsewhere.
        load_dotenv(override=False)

    @classmethod
    def refresh(cls) -> None:
        cls._load_dotenv()
        cls.INFERENCE_MODEL = os.getenv("INFERENCE_MODEL", "")
        cls.OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "")
        cls.OPENAI_API_URL = os.getenv("OPENAI_API_URL", "")
        cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    @classmethod
    def validate_azure(cls) -> None:
        cls.refresh()
        missing = []
        if not cls.INFERENCE_MODEL:
            missing.append("INFERENCE_MODEL")
        if not cls.OPENAI_API_VERSION:
            missing.append("OPENAI_API_VERSION")
        if not cls.OPENAI_API_URL:
            missing.append("OPENAI_API_URL")
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if missing:
            raise RuntimeError(
                "Missing Azure OpenAI config env vars: "
                + ", ".join(missing)
                + ". Set them and retry (see README)."
            )

