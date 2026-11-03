"""Minimal BER codec for SNMPv2c GetBulk. Enough to walk WLC tables."""

from __future__ import annotations

END_OF_MIB = object()


class BerError(ValueError):
    pass


def _len(n: int) -> bytes:
    if n < 0:
        raise BerError("negative length")
    if n < 128:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def enc_int(n: int) -> bytes:
    if n == 0:
        body = b"\x00"
    elif n > 0:
        body = n.to_bytes((n.bit_length() + 7) // 8, "big")
        if body[0] & 0x80:
            body = b"\x00" + body
    else:
        bits = n.bit_length() + 1
        body = n.to_bytes((bits + 7) // 8, "big", signed=True)
    return tlv(0x02, body)


def enc_str(text: str | bytes) -> bytes:
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return tlv(0x04, raw)


def enc_null() -> bytes:
    return b"\x05\x00"


def enc_oid(oid: str) -> bytes:
    parts = [int(part) for part in oid.split(".") if part != ""]
    if len(parts) < 2:
        raise BerError("oid")
    body = bytes([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        if part < 0:
            raise BerError("oid")
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        body += bytes(reversed(chunk))
    return tlv(0x06, body)


def enc_ip(text: str) -> bytes:
    nums = [int(part) for part in text.split(".")]
    if len(nums) != 4 or any(n < 0 or n > 255 for n in nums):
        raise BerError("ip")
    return tlv(0x40, bytes(nums))


def read_tlv(buf: bytes, pos: int) -> tuple[int, bytes, int]:
    if pos >= len(buf):
        raise BerError("truncated")
    tag = buf[pos]
    pos += 1
    if pos >= len(buf):
        raise BerError("truncated")
    first = buf[pos]
    pos += 1
    if first < 128:
        length = first
    else:
        count = first & 0x7F
        if count == 0 or pos + count > len(buf):
            raise BerError("length")
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    end = pos + length
    if end > len(buf):
        raise BerError("truncated")
    return tag, buf[pos:end], end


def dec_int(body: bytes) -> int:
    if not body:
        raise BerError("integer")
    return int.from_bytes(body, "big", signed=True)


def dec_oid(body: bytes) -> str:
    if not body:
        raise BerError("oid")
    first = body[0]
    parts = [str(first // 40), str(first % 40)]
    pos = 1
    while pos < len(body):
        value = 0
        while True:
            if pos >= len(body):
                raise BerError("oid")
            byte = body[pos]
            pos += 1
            value = (value << 7) | (byte & 0x7F)
            if not byte & 0x80:
                break
        parts.append(str(value))
    return ".".join(parts)


def decode_value(tag: int, body: bytes):
    if tag == 0x02:
        return dec_int(body)
    if tag == 0x04:
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.hex()
    if tag == 0x05:
        return None
    if tag == 0x06:
        return dec_oid(body)
    if tag == 0x40 and len(body) == 4:
        return ".".join(str(b) for b in body)
    if tag in (0x41, 0x42, 0x43):
        return int.from_bytes(body, "big")
    if tag == 0x46:
        return int.from_bytes(body, "big")
    if tag in (0x80, 0x81, 0x82):
        return END_OF_MIB
    if tag == 0x30:
        return body
    return body.hex()


def decode_any(buf: bytes, pos: int = 0):
    tag, body, end = read_tlv(buf, pos)
    if tag == 0x30 or (tag & 0x20 and tag not in (0xA0, 0xA2, 0xA5)):
        items = []
        cursor = 0
        while cursor < len(body):
            item, cursor = decode_any(body, cursor)
            items.append(item)
        return (tag, items), end
    if tag in (0xA2, 0xA5):
        items = []
        cursor = 0
        while cursor < len(body):
            item, cursor = decode_any(body, cursor)
            items.append(item)
        return (tag, items), end
    return (tag, decode_value(tag, body)), end


def varbind(oid: str, value: bytes | None = None) -> bytes:
    payload = enc_null() if value is None else value
    return tlv(0x30, enc_oid(oid) + payload)


def encode_getbulk(community: str, oid: str, request_id: int, max_reps: int) -> bytes:
    pdu_body = enc_int(request_id) + enc_int(0) + enc_int(max_reps) + tlv(0x30, varbind(oid))
    message = enc_int(1) + enc_str(community) + tlv(0xA5, pdu_body)
    return tlv(0x30, message)


def encode_response(community: str, request_id: int, binds: list[tuple[str, bytes]]) -> bytes:
    seq = b"".join(varbind(oid, value) for oid, value in binds)
    pdu_body = enc_int(request_id) + enc_int(0) + enc_int(0) + tlv(0x30, seq)
    message = enc_int(1) + enc_str(community) + tlv(0xA2, pdu_body)
    return tlv(0x30, message)


def _flat_int(item) -> int:
    tag, value = item
    if tag != 0x02 or not isinstance(value, int):
        raise BerError("expected integer")
    return value


def decode_message(packet: bytes) -> dict:
    (tag, items), end = decode_any(packet)
    if tag != 0x30 or end != len(packet) or len(items) < 3:
        raise BerError("message")
    version = _flat_int(items[0])
    community = items[1][1]
    if not isinstance(community, str):
        community = ""
    pdu_tag, pdu = items[2]
    if not isinstance(pdu, list) or len(pdu) < 4:
        raise BerError("pdu")
    binds = []
    raw_binds = pdu[3][1]
    if isinstance(raw_binds, list):
        for entry in raw_binds:
            if not isinstance(entry, tuple) or entry[0] != 0x30:
                continue
            pair = entry[1]
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            oid = pair[0][1]
            if not isinstance(oid, str):
                continue
            binds.append((oid, pair[1][1]))
    requested = ""
    if pdu_tag == 0xA5 and binds:
        requested = binds[0][0]
    return {
        "version": version,
        "community": community,
        "pdu": pdu_tag,
        "request_id": _flat_int(pdu[0]),
        "error": _flat_int(pdu[1]),
        "binds": binds,
        "requested": requested,
    }


def oid_tuple(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split(".") if part != "")


def under(oid: str, base: str) -> bool:
    return oid == base or oid.startswith(base + ".")
