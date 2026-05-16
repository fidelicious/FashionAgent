"""
Email parser registry.

Operator forwards retailer emails to a Gmail label → getmail/mbsync (or
manual SCP) drops the ``.eml`` files into ``inbox/email/`` → the inbox
sweep (Step 8) picks them up → this module turns each .eml into a
list of ``EmailItem``.

Each retailer parser is a function that takes the parsed
``email.message.EmailMessage`` and returns a list of ``EmailItem``.
The registry maps a "From" domain to a parser; an unknown sender
raises ``UnknownRetailerError`` so the watcher can quarantine.

V1 retailers: Quince, UNIQLO, H&M. The HTML/text patterns are
starting points tuned against synthetic emails — they'll need
real-world adjustment as the operator forwards live mail. Add a new
retailer by writing a parser function and registering it in
``RETAILER_PARSERS``.
"""

from __future__ import annotations

import email
import logging
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import getaddresses
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmailItem:
    """One product extracted from a retailer email.

    Either ``image_bytes`` is set (we found a product image to feed the
    pipeline) or it isn't (text-only sale alert / wishlist drop — the
    inbox processor will insert a row with no image and prompt the
    operator).
    """

    retailer: str
    brand: str
    name: Optional[str]
    price_usd: Optional[float]
    image_bytes: Optional[bytes]
    image_ext: Optional[str]
    source_path: Path


class UnknownRetailerError(Exception):
    """No retailer parser matched the email's From domain."""


class ParseFailedError(Exception):
    """Retailer parser ran but produced zero items (template drift)."""


# ─────────────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ─────────────────────────────────────────────────────────────────────────────


ParserFn = Callable[[EmailMessage, Path], list[EmailItem]]


def parse_eml(path: Path) -> list[EmailItem]:
    """Parse a .eml file. Returns 1..N ``EmailItem`` rows, never zero.

    Zero items from a *known* retailer indicates the email template
    changed; we raise ``ParseFailedError`` so the watcher can quarantine
    rather than silently swallow.
    """
    with path.open("rb") as f:
        msg: EmailMessage = email.message_from_binary_file(
            f, policy=default_policy
        )  # type: ignore[assignment]

    sender_domain = _sender_domain(msg)
    parser = _resolve_parser(sender_domain)
    if parser is None:
        raise UnknownRetailerError(
            f"No retailer parser registered for sender domain {sender_domain!r}. "
            f"Add a parser in clawbot.inbox.email_parser to support it."
        )

    items = parser(msg, path)
    if not items:
        retailer = _resolve_retailer_name(sender_domain) or sender_domain
        raise ParseFailedError(
            f"Retailer {retailer!r} parser found zero items in "
            f"{path.name} — template may have changed."
        )
    return items


def _sender_domain(msg: EmailMessage) -> str:
    """Return the lower-cased domain of the From address, or ''."""
    addrs = getaddresses([msg.get("From", "")])
    if not addrs or not addrs[0][1]:
        return ""
    addr = addrs[0][1]
    _, _, domain = addr.partition("@")
    return domain.lower().strip()


def _resolve_parser(domain: str) -> Optional[ParserFn]:
    """Match a From-domain (or its subdomain) to a registered parser."""
    if not domain:
        return None
    if domain in RETAILER_PARSERS:
        return RETAILER_PARSERS[domain]
    # Allow subdomain matches: orderconfirmation.uniqlo.com → uniqlo.com.
    for known, parser in RETAILER_PARSERS.items():
        if domain == known or domain.endswith("." + known):
            return parser
    return None


def _resolve_retailer_name(domain: str) -> Optional[str]:
    for known, name in _DOMAIN_TO_NAME.items():
        if domain == known or domain.endswith("." + known):
            return name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Body / image helpers shared across retailers
# ─────────────────────────────────────────────────────────────────────────────


def _html_body(msg: EmailMessage) -> str:
    """Best-effort HTML extraction. Falls back to text/plain."""
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is not None:
        return html_part.get_content()
    text_part = msg.get_body(preferencelist=("plain",))
    return text_part.get_content() if text_part is not None else ""


def _inline_images(msg: EmailMessage) -> dict[str, tuple[bytes, str]]:
    """Return ``{content_id: (bytes, ext)}`` for every inline image."""
    out: dict[str, tuple[bytes, str]] = {}
    for part in msg.walk():
        ctype = part.get_content_type()
        if not ctype.startswith("image/"):
            continue
        cid = (part.get("Content-ID") or "").strip("<>")
        if not cid:
            continue
        ext = "." + ctype.split("/", 1)[1].split(";")[0].strip()
        # Normalize the common case (jpeg → jpg).
        if ext == ".jpeg":
            ext = ".jpg"
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        out[cid] = (payload, ext)
    return out


def _first_attachment_image(msg: EmailMessage) -> Optional[tuple[bytes, str]]:
    """Fallback: first ``image/*`` part regardless of Content-ID."""
    for part in msg.walk():
        if not part.get_content_type().startswith("image/"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        ext = "." + part.get_content_type().split("/", 1)[1].split(";")[0]
        return payload, (".jpg" if ext == ".jpeg" else ext)
    return None


# Price regex shared by all parsers. Accepts $59.90, $1,299.00, USD 39.99.
_PRICE_RE = re.compile(
    r"(?:\$|USD\s*)\s*([0-9][0-9,]*\.[0-9]{2})", re.IGNORECASE
)


def _parse_price(text: str) -> Optional[float]:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _resolve_cid_image(
    html: str, images: dict[str, tuple[bytes, str]]
) -> Optional[tuple[bytes, str]]:
    """Find ``<img src='cid:foo'>`` in ``html`` and return the matching bytes."""
    m = re.search(r'src=["\']cid:([^"\']+)["\']', html)
    if not m:
        return None
    return images.get(m.group(1))


# ─────────────────────────────────────────────────────────────────────────────
# Retailer parsers
# ─────────────────────────────────────────────────────────────────────────────


# Pattern: <div class="item"> ... <p class="product-name">NAME</p>
#                                <p class="price">$NN.NN</p>     </div>
_QUINCE_ROW_RE = re.compile(
    r'<div[^>]*class="[^"]*item[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_QUINCE_NAME_RE = re.compile(
    r'<p[^>]*class="[^"]*product-name[^"]*"[^>]*>([^<]+)</p>',
    re.IGNORECASE | re.DOTALL,
)


def parse_quince(msg: EmailMessage, source_path: Path) -> list[EmailItem]:
    html = _html_body(msg)
    images = _inline_images(msg)

    items: list[EmailItem] = []
    for block in _QUINCE_ROW_RE.findall(html):
        name_m = _QUINCE_NAME_RE.search(block)
        name = name_m.group(1).strip() if name_m else None
        price = _parse_price(block)
        img = _resolve_cid_image(block, images)

        items.append(
            EmailItem(
                retailer="quince",
                brand="Quince",
                name=name,
                price_usd=price,
                image_bytes=img[0] if img else None,
                image_ext=img[1] if img else None,
                source_path=source_path,
            )
        )
    return items


# UNIQLO: order confirmation puts each item in a <table class="line-item"> row.
_UNIQLO_ROW_RE = re.compile(
    r'<table[^>]*class="[^"]*line-item[^"]*"[^>]*>(.*?)</table>',
    re.IGNORECASE | re.DOTALL,
)
_UNIQLO_NAME_RE = re.compile(
    r'<span[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)


def parse_uniqlo(msg: EmailMessage, source_path: Path) -> list[EmailItem]:
    html = _html_body(msg)
    images = _inline_images(msg)

    items: list[EmailItem] = []
    for block in _UNIQLO_ROW_RE.findall(html):
        name_m = _UNIQLO_NAME_RE.search(block)
        name = name_m.group(1).strip() if name_m else None
        price = _parse_price(block)
        img = _resolve_cid_image(block, images)

        items.append(
            EmailItem(
                retailer="uniqlo",
                brand="UNIQLO",
                name=name,
                price_usd=price,
                image_bytes=img[0] if img else None,
                image_ext=img[1] if img else None,
                source_path=source_path,
            )
        )
    return items


# H&M: each line is a <tr> with <b>Name</b><br/>USD NN.NN. Looser template, so
# we anchor on the bold name + the next price string within the same row.
_HM_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HM_NAME_RE = re.compile(r"<b[^>]*>([^<]+)</b>", re.IGNORECASE | re.DOTALL)


def parse_hm(msg: EmailMessage, source_path: Path) -> list[EmailItem]:
    html = _html_body(msg)
    images = _inline_images(msg)

    items: list[EmailItem] = []
    for block in _HM_ROW_RE.findall(html):
        name_m = _HM_NAME_RE.search(block)
        if not name_m:
            continue  # ignore header/footer rows that don't have a <b>
        name = name_m.group(1).strip()
        price = _parse_price(block)
        img = _resolve_cid_image(block, images)

        items.append(
            EmailItem(
                retailer="hm",
                brand="H&M",
                name=name,
                price_usd=price,
                image_bytes=img[0] if img else None,
                image_ext=img[1] if img else None,
                source_path=source_path,
            )
        )
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


RETAILER_PARSERS: dict[str, ParserFn] = {
    "quince.com": parse_quince,
    "uniqlo.com": parse_uniqlo,
    "hm.com": parse_hm,
}

_DOMAIN_TO_NAME: dict[str, str] = {
    "quince.com": "quince",
    "uniqlo.com": "uniqlo",
    "hm.com": "hm",
}
