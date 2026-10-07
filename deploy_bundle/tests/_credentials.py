"""Synthetic test passwords exist only in memory and are regenerated per process."""
import secrets

LEGACY_PASSWORDS = {role: secrets.token_urlsafe(32) for role in ("sales_analyst", "inventory_lead")}
