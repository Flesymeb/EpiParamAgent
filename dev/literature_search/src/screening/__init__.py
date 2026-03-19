"""Screening package.

Submodules are imported explicitly to keep CLI cold-start light and avoid
pulling heavy LLM/full-text dependencies during simple operations such as
`--help`.
"""

__all__: list[str] = []
