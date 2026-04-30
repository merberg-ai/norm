"""Safety helpers for beta2.

Pre1 does not control hardware. This module exists now so future body/GPIO plugins have
one obvious place to plug into instead of inventing unsafe shortcuts.
"""

SAFE_MODE_REASON = "safe_mode_enabled"
