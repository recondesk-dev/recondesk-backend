"""Email domain verification using DNS MX record lookups."""

from __future__ import annotations

import logging
from typing import Optional

import dns.exception
import dns.resolver
from fastapi import HTTPException, status

_log = logging.getLogger(__name__)

# Standard error message required when email domain has no MX records
INVALID_EMAIL_DOMAIN_DETAIL = (
    "This email domain doesn't appear to accept mail — please check for typos"
)


def _get_dns_resolver(timeout: float = 3.0) -> dns.resolver.Resolver:
    """Instantiate a dns.resolver.Resolver with graceful fallback for missing resolv.conf."""
    try:
        resolver = dns.resolver.Resolver()
    except dns.resolver.NoResolverConfiguration:
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]

    resolver.timeout = timeout
    resolver.lifetime = timeout
    return resolver


def has_mx_record(email_or_domain: str, timeout: float = 3.0) -> bool:
    """
    Check whether the given email domain has at least one valid DNS MX record.

    Returns True if valid MX records exist for the domain.
    Returns False if domain does not exist (NXDOMAIN), has no MX records (NoAnswer),
    or resolution fails.
    """
    if not email_or_domain or not isinstance(email_or_domain, str):
        return False

    raw = email_or_domain.strip()
    if "@" in raw:
        domain = raw.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    else:
        domain = raw.lower().rstrip(".")

    if not domain or "." not in domain:
        return False

    try:
        resolver = _get_dns_resolver(timeout=timeout)
        answers = resolver.resolve(domain, "MX")
        return bool(answers and len(answers) > 0)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.resolver.LifetimeTimeout,
        dns.exception.DNSException,
    ):
        return False
    except Exception as exc:
        _log.debug("MX lookup exception for domain %s: %s", domain, exc)
        return False


def validate_email_mx(email: str, timeout: float = 3.0) -> None:
    """
    Validates MX record on the email domain before creating an account.
    Raises HTTPException(400) if no MX record exists.
    """
    if not has_mx_record(email, timeout=timeout):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_EMAIL_DOMAIN_DETAIL,
        )
