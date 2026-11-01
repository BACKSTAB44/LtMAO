"""Resolve 4-byte vs 8-byte BIN Hash payloads from declared region sizes.

Port of LeagueToolkit's ltk_meta stream/layout/resolve.rs algorithm.
Offsets returned by resolve_object_hash_widths are relative to the supplied
object record (including its leading u32 size field).
"""
from __future__ import annotations

from dataclasses import dataclass


class HashWidthResolutionError(ValueError):
    """The declared BIN sizes do not determine a valid Hash-width layout."""


class AmbiguousHashWidthError(HashWidthResolutionError):
    """More than one hash-width assignment fits a map's declared size."""


# Current BIN property-kind numbering. These values deliberately mirror BINType.
NONE, BOOL, I8, U8, I16, U16, I32, U32, I64, U64 = range(10)
F32, VEC2, VEC3, VEC4, MTX44, RGBA, STRING, HASH, FILE = range(10, 19)
LIST, LIST2, POINTER, EMBED, LINK, OPTION, MAP, FLAG = range(128, 136)

_FIXED_WIDTHS = {
    NONE: 0,
    BOOL: 1,
    I8: 1,
    U8: 1,
    I16: 2,
    U16: 2,
    I32: 4,
    U32: 4,
    I64: 8,
    U64: 8,
    F32: 4,
    VEC2: 8,
    VEC3: 12,
    VEC4: 16,
    MTX44: 64,
    RGBA: 4,
    FILE: 8,
    LINK: 4,
    FLAG: 1,
}

BUDGET_PER_BYTE = 16
BUDGET_BASE = 1024


@dataclass
class _Choice:
    index: int
    at: int
    mark: int


@dataclass(frozen=True)
class _MapSide:
    kind: int
    width: int | None = None  # 4 or 8 when kind == HASH

    @property
    def fixed_width(self) -> int | None:
        return self.width if self.width is not None else _FIXED_WIDTHS.get(self.kind)


class _Search:
    def __init__(self, data: bytes | bytearray | memoryview):
        self.data = memoryview(data)
        self.wide: list[int] = []
        self.choices: list[_Choice] = []
        self.budget = len(self.data) * BUDGET_PER_BYTE + BUDGET_BASE
        self.ambiguous = False

    def _charge(self, steps: int = 1) -> bool:
        self.budget -= steps
        return self.budget >= 0

    def _bounded(self, pos: int, end: int) -> int | None:
        return pos if 0 <= pos <= end else None

    def _u8(self, pos: int, end: int) -> int | None:
        if pos < 0 or pos + 1 > end or pos + 1 > len(self.data):
            return None
        return int(self.data[pos])

    def _u16(self, pos: int, end: int) -> int | None:
        if pos < 0 or pos + 2 > end or pos + 2 > len(self.data):
            return None
        return int.from_bytes(self.data[pos:pos + 2], 'little')

    def _u32(self, pos: int, end: int) -> int | None:
        if pos < 0 or pos + 4 > end or pos + 4 > len(self.data):
            return None
        return int.from_bytes(self.data[pos:pos + 4], 'little')

    def _kind(self, pos: int, end: int) -> int | None:
        kind = self._u8(pos, end)
        if kind in _FIXED_WIDTHS or kind in (STRING, HASH, LIST, LIST2, POINTER, EMBED, OPTION, MAP):
            return kind
        return None

    def _item_kind(self, pos: int, end: int) -> int | None:
        kind = self._kind(pos, end)
        return None if kind in (LIST, LIST2, MAP, OPTION) else kind

    def _region(self, pos: int, end: int) -> tuple[int, int] | None:
        size = self._u32(pos, end)
        if size is None:
            return None
        body = pos + 4
        stop = self._bounded(body + size, end)
        return None if stop is None else (body, stop)

    def object(self) -> bool:
        size = self._u32(0, len(self.data))
        if size is None:
            return False
        end = self._bounded(size + 4, len(self.data))
        if end is None or end != len(self.data):
            return False
        # Object body starts after its size; it begins with path hash + property count.
        return self._object_body(4, end)

    def _object_body(self, pos: int, end: int) -> bool:
        count = self._u16(pos + 4, end)
        if count is None:
            return False
        return self._properties(pos + 6, end, count)

    def _properties(self, start: int, end: int, count: int) -> bool:
        floor = len(self.choices)
        result = self._properties_above(floor, start, end, count)
        del self.choices[floor:]
        return result

    def _properties_above(self, floor: int, start: int, end: int, count: int) -> bool:
        index, pos = 0, start
        while True:
            while index < count:
                nxt = self._property(index, pos, end)
                if nxt is None:
                    break
                pos = nxt
                index += 1
            if index == count and pos == end:
                return True

            while True:
                if len(self.choices) == floor:
                    return False
                choice = self.choices.pop()
                if not self._charge():
                    return False
                del self.wide[choice.mark:]
                nxt = self._bounded(choice.at + 8, end)
                if nxt is not None:
                    self.wide.append(choice.at)
                    index = choice.index + 1
                    pos = nxt
                    break

    def _property(self, index: int, pos: int, end: int) -> int | None:
        if not self._charge():
            return None
        kind = self._kind(pos + 4, end)
        if kind is None:
            return None
        at = pos + 5

        if kind == HASH:
            pass
        elif kind == OPTION:
            item_kind = self._item_kind(at, end)
            present = self._u8(at + 1, end)
            if item_kind is None or present is None:
                return None
            at += 2
            if not present:
                return at
            if item_kind != HASH:
                return self._value(item_kind, at, end)
        else:
            return self._value(kind, at, end)

        nxt = self._bounded(at + 4, end)
        if nxt is not None:
            self.choices.append(_Choice(index, at, len(self.wide)))
        return nxt

    def _value(self, kind: int, pos: int, end: int) -> int | None:
        if kind in _FIXED_WIDTHS:
            return self._bounded(pos + _FIXED_WIDTHS[kind], end)
        if kind == HASH:
            return self._bounded(pos + 4, end)
        if kind == STRING:
            length = self._u16(pos, end)
            return None if length is None else self._bounded(pos + 2 + length, end)
        if kind in (LIST, LIST2):
            item_kind = self._item_kind(pos, end)
            region = self._region(pos + 1, end)
            if item_kind is None or region is None:
                return None
            body, stop = region
            count = self._u32(body, stop)
            if count is None or not self._items(item_kind, count, body + 4, stop):
                return None
            return stop
        if kind == MAP:
            key_kind = self._kind(pos, end)
            value_kind = self._item_kind(pos + 1, end)
            region = self._region(pos + 2, end)
            if key_kind is None or value_kind is None or region is None:
                return None
            # LeagueToolkit's Kind::is_valid_map_key admits kinds 0..18
            # (None through WadChunkLink); ObjectLink and container kinds are excluded.
            if key_kind not in range(19):
                return None
            body, stop = region
            count = self._u32(body, stop)
            if count is None or not self._entries(key_kind, value_kind, count, body + 4, stop):
                return None
            return stop
        if kind in (POINTER, EMBED):
            class_hash = self._u32(pos, end)
            if class_hash is None:
                return None
            if class_hash == 0:
                return pos + 4
            region = self._region(pos + 4, end)
            if region is None:
                return None
            body, stop = region
            count = self._u16(body, stop)
            if count is None or not self._properties(body + 2, stop, count):
                return None
            return stop
        if kind == OPTION:
            item_kind = self._item_kind(pos, end)
            present = self._u8(pos + 1, end)
            if item_kind is None or present is None:
                return None
            if not present:
                return pos + 2
            return self._value(item_kind, pos + 2, end)
        return None

    def _items(self, item_kind: int, count: int, pos: int, end: int) -> bool:
        body_size = end - pos
        if item_kind == HASH:
            if count * 4 == body_size:
                return True
            if count * 8 == body_size:
                if not self._charge(count):
                    return False
                self.wide.extend(pos + index * 8 for index in range(count))
                return True
            return False
        fixed = _FIXED_WIDTHS.get(item_kind)
        if fixed is not None:
            return count * fixed == body_size
        for _ in range(count):
            if not self._charge():
                return False
            nxt = self._value(item_kind, pos, end)
            if nxt is None:
                return False
            pos = nxt
        return pos == end

    def _entries(self, key_kind: int, value_kind: int, count: int, pos: int, end: int) -> bool:
        if count == 0:
            return pos == end

        def options(kind: int):
            return (4, 8) if kind == HASH else (None,)

        resolved_mark: int | None = None
        for key_width in options(key_kind):
            for value_width in options(value_kind):
                mark = len(self.wide)
                key = _MapSide(key_kind, key_width)
                value = _MapSide(value_kind, value_width)
                fits = self._entries_with(key, value, count, pos, end)
                narrow = key_width != 8 and value_width != 8
                if fits and narrow:
                    return True
                if fits:
                    if resolved_mark is not None:
                        self.ambiguous = True
                        return False
                    resolved_mark = len(self.wide)
                del self.wide[resolved_mark if resolved_mark is not None else mark:]
        return resolved_mark is not None

    def _entries_with(self, key: _MapSide, value: _MapSide, count: int, pos: int, end: int) -> bool:
        key_size, value_size = key.fixed_width, value.fixed_width
        if key_size is not None and value_size is not None:
            pair_size = key_size + value_size
            if count * pair_size != end - pos:
                return False
            if key.width == 8 or value.width == 8:
                if not self._charge(count):
                    return False
                for index in range(count):
                    at = pos + index * pair_size
                    if key.width == 8:
                        self.wide.append(at)
                    if value.width == 8:
                        self.wide.append(at + key_size)
            return True

        for _ in range(count):
            if not self._charge():
                return False
            nxt = self._map_side(key, pos, end)
            if nxt is None:
                return False
            pos = nxt
            nxt = self._map_side(value, pos, end)
            if nxt is None:
                return False
            pos = nxt
        return pos == end

    def _map_side(self, side: _MapSide, pos: int, end: int) -> int | None:
        if side.width is None:
            return self._value(side.kind, pos, end)
        nxt = self._bounded(pos + side.width, end)
        if nxt is not None and side.width == 8:
            self.wide.append(pos)
        return nxt


def resolve_object_hash_widths(record: bytes | bytearray | memoryview) -> set[int]:
    """Return offsets of 8-byte Hash payloads in one sized object record.

    `record` starts at the object's u32 size field and must contain exactly
    `4 + declared_size` bytes. The returned offsets are relative to `record`.
    The search deliberately prefers 4-byte hashes whenever that layout fits.
    """
    search = _Search(record)
    if search.object():
        return set(search.wide)
    if search.ambiguous:
        raise AmbiguousHashWidthError("BIN object contains an ambiguous map hash width")
    raise HashWidthResolutionError("BIN object size does not match any valid 4/8-byte hash layout")


def resolve_value_hash_widths(data: bytes | bytearray | memoryview, kind: int) -> set[int]:
    """Resolve hash payload offsets in a sized standalone value.

    A top-level bare HASH with no enclosing size is intentionally treated as
    4-byte, matching LeagueToolkit. Nested sized structs/containers/maps can
    still contain and resolve 8-byte hashes.
    """
    search = _Search(data)
    end = len(search.data)

    # PTCH records provide an outer size for their value. A bare HASH has no
    # inner size of its own, so the record boundary is the only width signal.
    if kind == HASH:
        if end == 8:
            return {0}
        if end == 4:
            return set()
    if kind == OPTION and end >= 2:
        item_kind = search._item_kind(0, end)
        present = search._u8(1, end)
        if item_kind == HASH and present == 1:
            if end == 10:
                return {2}
            if end == 6:
                return set()

    nxt = search._value(kind, 0, end)
    if nxt == end:
        return set(search.wide)
    if search.ambiguous:
        raise AmbiguousHashWidthError("BIN value contains an ambiguous map hash width")
    raise HashWidthResolutionError("BIN value size does not match any valid hash-width layout")
