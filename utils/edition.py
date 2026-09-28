"""Identify the separately packaged customer edition."""

from pathlib import Path
import sys


def is_customer_edition() -> bool:
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).name.lower() == "duytriscustomer.exe"
