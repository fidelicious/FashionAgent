"""
Tests for the email parser registry.

Synthetic ``.eml`` fixtures are built in-test so we don't need to commit
real retailer emails (privacy) or carry binary blobs in the repo. Each
fixture mirrors the structure of a real confirmation: ``From``,
``Subject``, an HTML body with product rows, and inline image attachments
where applicable.

The retailer-specific regexes here are starting points — they pass
synthetic-canonical emails; real-world tuning happens when the operator
forwards a live email and reports a mismatch.
"""

from __future__ import annotations

import base64
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

from clawbot.inbox.email_parser import (
    EmailItem,
    ParseFailedError,
    UnknownRetailerError,
    parse_eml,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture builders — hand-crafted .eml writers
# ─────────────────────────────────────────────────────────────────────────────


def _write_eml(
    path: Path,
    *,
    from_addr: str,
    subject: str,
    html_body: str,
    images: list[tuple[str, bytes]] | None = None,
) -> Path:
    """Build a multipart/related .eml and write it to ``path``."""
    msg = MIMEMultipart("related")
    msg["From"] = from_addr
    msg["To"] = "operator@example.com"
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    for cid, data in images or []:
        img = MIMEImage(data, _subtype="jpeg")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.jpg")
        msg.attach(img)
    path.write_bytes(msg.as_bytes())
    return path


_TINY_JPG = base64.b64decode(
    # 1x1 JPEG. Just enough to satisfy "this is a jpg-shaped file".
    b"/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/9sAQwEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/8AAEQgAAQABAwEiAAIRAQMRAf/EAB8A"
    b"AAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFB"
    b"BhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldY"
    b"WVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfI"
    b"ycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/aAAwDAQACEQMRAD8A/v4oA//Z"
)


@pytest.fixture
def quince_order(tmp_path: Path) -> Path:
    return _write_eml(
        tmp_path / "quince.eml",
        from_addr="orders@quince.com",
        subject="Your Quince order is confirmed",
        html_body=(
            "<html><body>"
            '<div class="item">'
            '<img src="cid:item1" />'
            '<p class="product-name">Mongolian Cashmere Crewneck Sweater</p>'
            '<p class="price">$59.90</p>'
            "</div>"
            "</body></html>"
        ),
        images=[("item1", _TINY_JPG)],
    )


@pytest.fixture
def uniqlo_order(tmp_path: Path) -> Path:
    return _write_eml(
        tmp_path / "uniqlo.eml",
        from_addr="orderconfirmation@uniqlo.com",
        subject="UNIQLO Order Confirmation",
        html_body=(
            "<html><body>"
            '<table class="line-item">'
            '<tr><td><img src="cid:p1"></td>'
            '<td><span class="name">U Crew Neck T-Shirt</span></td>'
            '<td><span class="price">$19.90</span></td></tr>'
            "</table>"
            "</body></html>"
        ),
        images=[("p1", _TINY_JPG)],
    )


@pytest.fixture
def hm_order(tmp_path: Path) -> Path:
    return _write_eml(
        tmp_path / "hm.eml",
        from_addr="noreply@hm.com",
        subject="Thank you for your H&M order",
        html_body=(
            "<html><body>"
            "<table>"
            '<tr><td><img src="cid:hmimg1"/></td>'
            '<td><b>Wide-leg trousers</b><br/>'
            "USD 39.99</td></tr>"
            "</table>"
            "</body></html>"
        ),
        images=[("hmimg1", _TINY_JPG)],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-retailer happy paths
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_quince_single_item(quince_order: Path) -> None:
    items = parse_eml(quince_order)
    assert len(items) == 1
    it = items[0]
    assert isinstance(it, EmailItem)
    assert it.retailer == "quince"
    assert it.brand == "Quince"
    assert it.name == "Mongolian Cashmere Crewneck Sweater"
    assert it.price_usd == pytest.approx(59.90)
    assert it.image_bytes is not None
    assert it.image_ext == ".jpg"


def test_parse_uniqlo_single_item(uniqlo_order: Path) -> None:
    items = parse_eml(uniqlo_order)
    assert len(items) == 1
    it = items[0]
    assert it.retailer == "uniqlo"
    assert it.brand == "UNIQLO"
    assert it.name == "U Crew Neck T-Shirt"
    assert it.price_usd == pytest.approx(19.90)
    assert it.image_bytes is not None


def test_parse_hm_single_item(hm_order: Path) -> None:
    items = parse_eml(hm_order)
    assert len(items) == 1
    it = items[0]
    assert it.retailer == "hm"
    assert it.brand == "H&M"
    assert it.name == "Wide-leg trousers"
    assert it.price_usd == pytest.approx(39.99)
    assert it.image_bytes is not None


# ─────────────────────────────────────────────────────────────────────────────
# Multi-item
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_quince_multi_item(tmp_path: Path) -> None:
    eml = _write_eml(
        tmp_path / "multi.eml",
        from_addr="orders@quince.com",
        subject="Your Quince order is confirmed",
        html_body=(
            "<html><body>"
            '<div class="item">'
            '<img src="cid:item1" />'
            '<p class="product-name">Cashmere Crewneck</p>'
            '<p class="price">$59.90</p>'
            "</div>"
            '<div class="item">'
            '<img src="cid:item2" />'
            '<p class="product-name">Linen Wide-Leg Pant</p>'
            '<p class="price">$49.50</p>'
            "</div>"
            "</body></html>"
        ),
        images=[("item1", _TINY_JPG), ("item2", _TINY_JPG)],
    )
    items = parse_eml(eml)
    assert len(items) == 2
    assert {i.name for i in items} == {"Cashmere Crewneck", "Linen Wide-Leg Pant"}


# ─────────────────────────────────────────────────────────────────────────────
# Image-less email
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_quince_no_image(tmp_path: Path) -> None:
    """Sale alerts / wishlist drops often have no inline image."""
    eml = _write_eml(
        tmp_path / "saleq.eml",
        from_addr="hello@quince.com",
        subject="Price drop on items in your wishlist",
        html_body=(
            "<html><body>"
            '<div class="item">'
            '<p class="product-name">Mongolian Cashmere Wrap Coat</p>'
            '<p class="price">$229.00</p>'
            "</div>"
            "</body></html>"
        ),
    )
    items = parse_eml(eml)
    assert len(items) == 1
    assert items[0].image_bytes is None
    assert items[0].image_ext is None
    assert items[0].name == "Mongolian Cashmere Wrap Coat"
    assert items[0].price_usd == pytest.approx(229.0)


# ─────────────────────────────────────────────────────────────────────────────
# Failure modes
# ─────────────────────────────────────────────────────────────────────────────


def test_unknown_retailer_raises(tmp_path: Path) -> None:
    eml = _write_eml(
        tmp_path / "weirdshop.eml",
        from_addr="orders@some-boutique.example",
        subject="Your order",
        html_body="<html><body>nope</body></html>",
    )
    with pytest.raises(UnknownRetailerError, match="some-boutique"):
        parse_eml(eml)


def test_known_retailer_zero_items_raises(tmp_path: Path) -> None:
    """A Quince email whose body doesn't match any of the row patterns."""
    eml = _write_eml(
        tmp_path / "empty.eml",
        from_addr="orders@quince.com",
        subject="Your Quince newsletter",
        html_body="<html><body><h1>Hello.</h1></body></html>",
    )
    with pytest.raises(ParseFailedError, match="quince"):
        parse_eml(eml)


def test_parse_eml_handles_unicode_sender(tmp_path: Path) -> None:
    """`From: =?utf-8?Q?...?= <orders@quince.com>` should still match."""
    eml_path = tmp_path / "unicode.eml"
    raw = (
        b"From: =?UTF-8?Q?Quince=20Team?= <orders@quince.com>\r\n"
        b"To: operator@example.com\r\n"
        b"Subject: Order confirmed\r\n"
        b'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        b'<html><body><div class="item">'
        b'<p class="product-name">Silk Slip Dress</p>'
        b'<p class="price">$99.50</p>'
        b"</div></body></html>"
    )
    eml_path.write_bytes(raw)

    items = parse_eml(eml_path)
    assert len(items) == 1
    assert items[0].retailer == "quince"
    assert items[0].name == "Silk Slip Dress"
