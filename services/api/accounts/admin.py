"""Admin for the accounts app.

Everything worth administering lives in :mod:`core.admin`, which is imported
here so Django finds it. Accounts are one subject among several, not a special
case, and splitting them across six files made them harder to keep consistent.
"""

from core.admin import *  # noqa: F403
