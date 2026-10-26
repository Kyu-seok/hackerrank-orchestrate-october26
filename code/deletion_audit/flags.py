"""Boolean-like values from environment variables and evidence fields."""


def flag(value):
    """True/False for a boolean-like value (bool, 0/1, "true"/"false", "yes"/"no", "on"/"off"),
    None when absent or unreadable."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return None
