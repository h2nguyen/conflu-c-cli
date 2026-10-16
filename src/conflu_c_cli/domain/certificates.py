"""Who a certificate was issued to and by, read from its DER bytes: enough to tell a person which authority is missing.

This is not a certificate validator. Trust decisions are made by the TLS library; this module only reads the names out of
what a server presented, for an error message. It never raises: a certificate it cannot read gives `None`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

_COMMON_NAME = bytes.fromhex("550403")  # OID 2.5.4.3
_ORGANIZATION = bytes.fromhex("55040a")  # OID 2.5.4.10
_MAX_NAME = 80
_MAX_CHAIN = 10


@dataclass(frozen=True)
class CertificateNames:
    subject: str
    issuer: str
    self_signed: bool  # the issuer is the subject itself: a root


def _tlv(data: bytes, position: int) -> tuple[int, int, int]:
    """`(tag, start of the value, end of the value)` of the element at `position`."""
    if position + 2 > len(data):
        raise ValueError("truncated")
    tag, length = data[position], data[position + 1]
    position += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or position + count > len(data):
            raise ValueError("bad length")
        length = int.from_bytes(data[position : position + count], "big")
        position += count
    end = position + length
    if end > len(data):
        raise ValueError("truncated")
    return tag, position, end


def _children(data: bytes, start: int, end: int) -> list[tuple[int, int, int, int]]:
    """`(tag, start of the element, start of its value, end of its value)` for each element between `start` and `end`."""
    found, position = [], start
    while position < end:
        tag, value_start, value_end = _tlv(data, position)
        found.append((tag, position, value_start, value_end))
        position = value_end
    return found


def _text(tag: int, raw: bytes) -> str:
    if tag == 0x1E:
        return raw.decode("utf-16-be", "replace")
    if tag == 0x0C:
        return raw.decode("utf-8", "replace")
    if tag in (0x13, 0x14, 0x16):
        return raw.decode("latin-1")
    return ""


def _clean(text: str) -> str:
    """The text with everything a terminal could act on taken out, and cut short."""
    cleaned = " ".join("".join(char if char.isprintable() else " " for char in text).split())
    return cleaned if len(cleaned) <= _MAX_NAME else cleaned[: _MAX_NAME - 3] + "..."


def _name(data: bytes, start: int, end: int) -> str:
    """The common name of a distinguished name, else the organisation, else nothing."""
    common = organization = ""
    for _, _, set_start, set_end in _children(data, start, end):
        for _, _, pair_start, pair_end in _children(data, set_start, set_end):
            parts = _children(data, pair_start, pair_end)
            if len(parts) < 2:
                continue
            oid = data[parts[0][2] : parts[0][3]]
            value = _text(parts[1][0], data[parts[1][2] : parts[1][3]])
            if oid == _COMMON_NAME and not common:
                common = value
            elif oid == _ORGANIZATION and not organization:
                organization = value
    return _clean(common or organization)


def certificate_names(der: bytes) -> CertificateNames | None:
    try:
        _, start, end = _tlv(der, 0)
        tbs = _children(der, start, end)[0]
        fields = _children(der, tbs[2], tbs[3])
        if fields and fields[0][0] == 0xA0:  # the explicit version
            fields = fields[1:]
        issuer, subject = fields[2], fields[4]  # after the serial number and the signature algorithm
        return CertificateNames(
            subject=_name(der, subject[2], subject[3]) or "(no name)",
            issuer=_name(der, issuer[2], issuer[3]) or "(no name)",
            self_signed=der[issuer[1] : issuer[3]] == der[subject[1] : subject[3]],
        )
    except (ValueError, IndexError, TypeError):
        return None


def untrusted_chain_note(chain: Sequence[bytes]) -> str:
    """One sentence on the chain a server presented, from its certificate to the authority at the top, for an error
    message. Empty when nothing in it can be read."""
    names = [item for item in map(certificate_names, list(chain)[:_MAX_CHAIN]) if item is not None]
    if not names:
        return ""
    steps = [f"'{item.subject}'" for item in names]
    if not names[-1].self_signed:
        steps.append(f"'{names[-1].issuer}' (not sent by the server)")
    return "The server presented this chain, from its own certificate up to the authority that vouches for it: " + " <- ".join(steps) + "."
