from __future__ import annotations

DEFAULT_SANDBOX_IMAGE = "coding-eval-sandbox:latest"
DOCKERFILE_SANDBOX = "Dockerfile.sandbox"


def sandbox_image_tag(tag: str = "latest") -> str:
    return f"coding-eval-sandbox:{tag}"


__all__ = ["DEFAULT_SANDBOX_IMAGE", "DOCKERFILE_SANDBOX", "sandbox_image_tag"]
