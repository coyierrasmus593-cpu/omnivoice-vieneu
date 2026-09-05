# -*- coding: utf-8 -*-
"""License domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class LicenseStatus(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    TRIAL = "trial"
    EXPIRED = "expired"
    INVALID = "invalid"
    NO_LICENSE = "no_license"


class LicenseTier(str, Enum):
    FREE = "free"
    TRIAL = "trial"
    STANDARD = "standard"
    PROFESSIONAL = "professional"


@dataclass
class LicenseInfo:
    """Domain model for license information."""

    status: LicenseStatus = LicenseStatus.UNKNOWN
    tier: LicenseTier = LicenseTier.FREE
    license_key: str = ""
    username: str = ""
    email: str = ""
    expires_at: Optional[str] = None
    machine_id: str = ""
    message: str = ""
    days_remaining: int = -1
    features: list = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status in (LicenseStatus.VALID, LicenseStatus.TRIAL)

    @property
    def is_expired(self) -> bool:
        return self.status == LicenseStatus.EXPIRED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "tier": self.tier.value,
            "license_key": self.license_key,
            "username": self.username,
            "email": self.email,
            "expires_at": self.expires_at,
            "machine_id": self.machine_id,
            "message": self.message,
            "days_remaining": self.days_remaining,
            "features": self.features,
        }

    @classmethod
    def from_verify_result(cls, result: dict) -> "LicenseInfo":
        """Create LicenseInfo from LicenseManager.verify() result dict."""
        info = cls()
        if result.get("valid"):
            info.status = LicenseStatus.VALID
            info.tier = LicenseTier.STANDARD
        else:
            info.status = LicenseStatus.INVALID

        info.license_key = result.get("license_key", "")
        info.username = result.get("username", "")
        info.email = result.get("email", "")
        info.message = result.get("message", "")
        info.days_remaining = result.get("days_left", -1)
        info.machine_id = result.get("machine_id", "")

        exp = result.get("expiry")
        if exp:
            from datetime import datetime, timezone
            try:
                info.expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                info.expires_at = str(exp)

        return info
