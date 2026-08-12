"""Reference implementation for the draft verifiable-release study.

The package keeps pilot-only cryptographic dependencies lazy so that the
production GitHub CLI adapter can be exercised in a minimal offline runtime.
"""

from typing import Any

__all__ = ["ImplementationIdentity", "verify_release"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .verifier import ImplementationIdentity, verify_release

        return {
            "ImplementationIdentity": ImplementationIdentity,
            "verify_release": verify_release,
        }[name]
    raise AttributeError(name)
