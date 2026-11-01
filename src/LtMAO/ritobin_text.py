"""Metadata-driven hash-string compatibility for LtMAO's ritobin-tools path.

The BIN format stores a Hash value's bytes, not the algorithm used to create
those bytes. LeagueToolkit's lol-meta-classes database records the hasher for
individual scalar Hash properties and keeps historical revisions.

Before calling ritobin-tools, this module prepares a temporary copy of the
user's text and adds the algorithm annotation required by ritobin-tools when a
known Hash property contains a quoted string. The original source file is
never modified.

The official ritobin-tools converter remains responsible for calculating the
hash. Unknown or unsupported hashers are never guessed.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.request
from typing import Any


META_DB_URL = (
    "https://raw.githubusercontent.com/LeagueToolkit/lol-meta-classes/main/"
    "db/meta.db.json"
)
def _default_cache_dir() -> str:
    # Keep the downloaded schema outside the Git repository so it never appears
    # as an untracked LtMAO project file.
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "LtMAO", "cache", "lol-meta-classes")


META_CACHE_DIR = _default_cache_dir()
META_CACHE_FILE = os.path.join(META_CACHE_DIR, "meta.db.json")
TARGET_BUILD_FILE = os.path.join(META_CACHE_DIR, "target-build.txt")
# Refresh the full upstream metadata at most once per 12-hour cooldown.
# Between refreshes, a compact local index is used instead of parsing the
# much larger upstream database on every fresh LtMAO process.
META_REFRESH_COOLDOWN_SECONDS = 12 * 60 * 60
META_CACHE_TTL_SECONDS = META_REFRESH_COOLDOWN_SECONDS  # Backwards-compatible alias
META_INDEX_FILE = os.path.join(META_CACHE_DIR, "meta.hash-index.json")
META_CHECK_FILE = os.path.join(META_CACHE_DIR, "meta.last-check")
MAX_META_DB_BYTES = 50 * 1024 * 1024

# Riot's metadata enum -> ritobin-tools' explicit algorithm spelling.
ALGORITHM_NAMES = {
    "fnv1a32": "fnv1a",
    "xxh64": "xxh64",
    "xxh3": "xxh3",
}

_IDENTIFIER = r"(?:0x[0-9a-fA-F]+|[A-Za-z_][A-Za-z0-9_]*)"
_QUOTED = r'"(?:\\.|[^"\\])*"'

# Top-level BIN entries and map values containing an Embed/Pointer.
_ENTRY_CLASS_RE = re.compile(
    rf'^\s*(?:{_QUOTED}|{_IDENTIFIER})\s*=\s*(?P<class>{_IDENTIFIER})\s*\{{'
)
# A direct Pointer/Embed field whose value opens a nested class object.
_FIELD_CLASS_RE = re.compile(
    rf'^\s*{_IDENTIFIER}\s*:\s*(?:pointer|embed)\s*=\s*(?P<class>{_IDENTIFIER})\s*\{{',
    re.IGNORECASE,
)
# An Embed/Pointer value inside a List/List2/Map, where the class token is
# printed without a property name (e.g. `0x12345678 { ... }`).
_BARE_CLASS_RE = re.compile(rf'^\s*(?P<class>{_IDENTIFIER})\s*\{{')

_HASH_STRING_FIELD_RE = re.compile(
    rf'^(?P<prefix>\s*(?P<field>{_IDENTIFIER})\s*:\s*)'
    r'(?P<type>hash(?:\s*\[\s*u(?:32|64)\s*\])?)'
    rf'(?P<assign>\s*=\s*)(?P<value>{_QUOTED})(?P<suffix>\s*(?:#.*)?)$',
    re.IGNORECASE,
)
_HASH_TYPE_RE = re.compile(r"^hash(?:\s*\[\s*(u32|u64)\s*\])?$", re.IGNORECASE)


class MetadataError(RuntimeError):
    """Metadata cannot safely describe a string-valued Hash property."""


class UnsupportedHasherError(MetadataError):
    """Metadata identifies a hasher that ritobin-tools cannot express."""


_METADATA_DB: dict[str, Any] | None = None
_METADATA_SOURCE: str | None = None
_METADATA_LOADED = False


def _log(message: str) -> None:
    print(f"ritobin: {message}")


def _valid_meta_db(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("formatVersion") == 1
        and isinstance(data.get("latest"), int)
        and isinstance(data.get("classes"), dict)
    )


def _read_json_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        return data if _valid_meta_db(data) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _download_meta_db() -> dict[str, Any]:
    request = urllib.request.Request(
        META_DB_URL,
        headers={
            "User-Agent": "LtMAO-ritobin-metadata-preprocessor/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(MAX_META_DB_BYTES + 1)
    if len(raw) > MAX_META_DB_BYTES:
        raise MetadataError(
            f"LeagueToolkit metadata database exceeds {MAX_META_DB_BYTES} bytes."
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MetadataError(f"Downloaded metadata is not valid UTF-8 JSON: {exc}") from exc
    if not _valid_meta_db(data):
        raise MetadataError("Downloaded metadata has an unsupported or invalid format.")
    return data


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix="meta_db_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise


def reset_metadata_cache_for_tests() -> None:
    global _METADATA_DB, _METADATA_SOURCE, _METADATA_LOADED
    _METADATA_DB = None
    _METADATA_SOURCE = None
    _METADATA_LOADED = False


def _compact_metadata_database(database: dict[str, Any]) -> dict[str, Any]:
    """Keep only scalar-Hash property revisions and class inheritance data.

    The full upstream JSON contains many unrelated properties and metadata
    fields. This compact form is sufficient for the resolver below and is much
    faster to read in a new LtMAO process.
    """
    compact_classes: dict[str, Any] = {}
    for class_key, class_record in database.get("classes", {}).items():
        if not isinstance(class_record, dict):
            continue
        compact_record: dict[str, Any] = {}
        if isinstance(class_record.get("name"), str):
            compact_record["name"] = class_record["name"]

        class_revisions = class_record.get("revisions")
        if isinstance(class_revisions, list):
            compact_record["revisions"] = [
                {key: revision[key] for key in ("from", "to", "bases") if key in revision}
                for revision in class_revisions
                if isinstance(revision, dict) and isinstance(revision.get("from"), int)
            ]

        compact_properties: dict[str, Any] = {}
        properties = class_record.get("properties", {})
        if isinstance(properties, dict):
            for property_key, property_record in properties.items():
                if not isinstance(property_record, dict):
                    continue
                revisions = property_record.get("revisions")
                if not isinstance(revisions, list):
                    continue
                # Keep all revisions for properties that are Hash in at least
                # one build, including non-Hash revisions needed for safe
                # historical type validation.
                if not any(
                    isinstance(revision, dict)
                    and isinstance(revision.get("type"), list)
                    and revision["type"]
                    and revision["type"][0] == "Hash"
                    for revision in revisions
                ):
                    continue
                compact_property: dict[str, Any] = {}
                if isinstance(property_record.get("name"), str):
                    compact_property["name"] = property_record["name"]
                compact_property["revisions"] = [
                    {key: revision[key] for key in ("from", "to", "type", "hasher", "default") if key in revision}
                    for revision in revisions
                    if isinstance(revision, dict) and isinstance(revision.get("from"), int)
                ]
                compact_properties[property_key] = compact_property
        compact_record["properties"] = compact_properties
        compact_classes[class_key] = compact_record

    return {
        "formatVersion": 1,
        "latest": int(database["latest"]),
        "classes": compact_classes,
    }


def _check_is_recent(path: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(path)) < META_REFRESH_COOLDOWN_SECONDS
    except OSError:
        return False


def _mark_metadata_checked() -> None:
    directory = os.path.dirname(os.path.abspath(META_CHECK_FILE))
    os.makedirs(directory, exist_ok=True)
    with open(META_CHECK_FILE, "w", encoding="ascii", newline="\n") as stream:
        stream.write(str(int(time.time())))


def _remember_metadata(database: dict[str, Any] | None, source: str) -> tuple[dict[str, Any] | None, str]:
    global _METADATA_DB, _METADATA_SOURCE, _METADATA_LOADED
    _METADATA_DB = database
    _METADATA_SOURCE = source
    _METADATA_LOADED = True
    return database, source


def _load_default_metadata_database(force_refresh: bool = False) -> tuple[dict[str, Any] | None, str]:
    """Use a compact local index for 12 hours between upstream refresh checks."""
    # This is the fast path for a new Python process: read only the compact
    # index and do not touch the large upstream JSON or network during cooldown.
    if not force_refresh and _check_is_recent(META_CHECK_FILE):
        indexed = _read_json_file(META_INDEX_FILE)
        if indexed is not None:
            return _remember_metadata(indexed, f"local index (build {indexed['latest']}; refresh cooldown)")
        # A previous refresh attempt may have failed before any database was
        # available. Honour its cooldown too, so offline conversions do not
        # repeat the network timeout on every launch.
        cached_during_cooldown = _read_json_file(META_CACHE_FILE)
        if cached_during_cooldown is None:
            return _remember_metadata(None, "unavailable (previous refresh attempt is still in cooldown)")
        compact_during_cooldown = _compact_metadata_database(cached_during_cooldown)
        try:
            _atomic_write_json(META_INDEX_FILE, compact_during_cooldown)
        except OSError as exc:
            _log(f"Warning: could not persist compact metadata index: {exc}")
        return _remember_metadata(compact_during_cooldown, f"local metadata cache (build {compact_during_cooldown['latest']}; refresh cooldown)")

    cached_full = _read_json_file(META_CACHE_FILE)
    cached_full_recent = cached_full is not None and _check_is_recent(META_CACHE_FILE)

    # If our full cache was written within the cooldown, rebuild the index
    # locally without making another request.
    database: dict[str, Any] | None = cached_full if cached_full_recent and not force_refresh else None
    source = ""
    if database is not None:
        source = f"local metadata cache (build {database['latest']})"
    else:
        try:
            database = _download_meta_db()
            try:
                _atomic_write_json(META_CACHE_FILE, database)
            except OSError as exc:
                _log(f"Warning: metadata downloaded but could not be cached: {exc}")
            source = f"downloaded (build {database['latest']})"
            _log(f"Refreshed LeagueToolkit property-hasher metadata: {source}.")
        except Exception as exc:
            if cached_full is not None:
                database = cached_full
                source = f"stale metadata cache (build {database['latest']}; refresh failed: {exc})"
                _log(f"Warning: using {source}.")
            else:
                database = None
                source = f"unavailable (download failed: {exc})"
                _log(f"Warning: LeagueToolkit property-hasher metadata is {source}.")

    try:
        if database is not None:
            compact = _compact_metadata_database(database)
            _atomic_write_json(META_INDEX_FILE, compact)
        # Record failed checks too. Otherwise an offline machine would retry
        # the 15-second network request on every conversion.
        _mark_metadata_checked()
    except OSError as exc:
        _log(f"Warning: could not persist metadata cache/cooldown marker: {exc}")

    if database is None:
        return _remember_metadata(None, source)

    compact = _read_json_file(META_INDEX_FILE)
    if compact is None:
        # Index persistence may fail because of permissions; continue using the
        # compact object in memory for this process.
        compact = _compact_metadata_database(database)
    return _remember_metadata(compact, source)


def load_metadata_database(
    *,
    cache_path: str | None = None,
    force_refresh: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Load LeagueToolkit metadata, refreshing at most every 12 hours.

    Normal LtMAO conversions use a compact local index during the cooldown,
    avoiding repeated parsing of the full metadata database in new processes.
    A stale full cache is used if refresh fails. Tests may supply ``cache_path``
    to exercise the original standalone cache behavior in an isolated folder.
    """
    global _METADATA_DB, _METADATA_SOURCE, _METADATA_LOADED
    if _METADATA_LOADED and cache_path is None and not force_refresh:
        return _METADATA_DB, _METADATA_SOURCE or "unavailable"

    if cache_path is None:
        return _load_default_metadata_database(force_refresh=force_refresh)

    cached = _read_json_file(cache_path)
    cache_fresh = False
    if cached is not None:
        try:
            cache_fresh = (time.time() - os.path.getmtime(cache_path)) < META_REFRESH_COOLDOWN_SECONDS
        except OSError:
            cache_fresh = False

    if cached is not None and cache_fresh and not force_refresh:
        return cached, f"cache (build {cached['latest']})"

    try:
        downloaded = _download_meta_db()
        try:
            _atomic_write_json(cache_path, downloaded)
        except OSError as exc:
            _log(f"Warning: metadata downloaded but could not be cached: {exc}")
        return downloaded, f"downloaded (build {downloaded['latest']})"
    except Exception as exc:
        if cached is not None:
            return cached, f"stale cache (build {cached['latest']}; refresh failed: {exc})"
        return None, f"unavailable (download failed: {exc})"


def refresh_metadata_for_retry() -> tuple[bool, str]:
    """Bypass the normal cooldown and attempt one immediate metadata refresh.

    Returns ``(True, source)`` only when a fresh upstream database was
    downloaded successfully. If the network request fails, the normal loader
    may continue using its stale cache, but callers should not retry a failed
    conversion against that unchanged metadata.
    """
    # Suppress routine cache/download messages here: the retry path is meant
    # to be transparent unless the converter still fails on its second attempt.
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        database, source = load_metadata_database(force_refresh=True)
    refreshed = database is not None and source.startswith("downloaded ")
    return refreshed, source


def _target_build(database: dict[str, Any]) -> int:
    """Select a schema build. Environment override wins over the local config."""
    override = os.environ.get("LTMAO_RITOBIN_META_BUILD", "").strip()
    if not override:
        try:
            with open(TARGET_BUILD_FILE, "r", encoding="utf-8") as stream:
                override = stream.read().strip()
        except OSError:
            override = ""
    if override:
        try:
            build = int(override, 10)
            if build > 0:
                return build
        except ValueError:
            _log(
                f"Warning: invalid target build {override!r} in {TARGET_BUILD_FILE}; "
                f"using metadata latest build {database['latest']}."
            )
    return int(database["latest"])


def _fnv1a_lower(text: str) -> int:
    value = 0x811C9DC5
    for byte in text.lower().encode("ascii"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _metadata_hash_key(token: str) -> str | None:
    token = token.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", token):
        try:
            return f"0x{int(token, 16):x}"
        except ValueError:
            return None
    try:
        return f"0x{_fnv1a_lower(token):x}"
    except (UnicodeEncodeError, AttributeError):
        return None


def _active_revision(revisions: Any, build: int) -> dict[str, Any] | None:
    if not isinstance(revisions, list):
        return None
    active = [
        revision for revision in revisions
        if isinstance(revision, dict)
        and isinstance(revision.get("from"), int)
        and revision["from"] <= build
        and (revision.get("to") is None or (
            isinstance(revision.get("to"), int) and build <= revision["to"]
        ))
    ]
    if not active:
        return None
    # Revision arrays are chronological in the source database. Choosing the
    # greatest `from` also handles classes with multiple historical revisions.
    return max(active, key=lambda revision: revision["from"])


def _lookup_property_revision(
    database: dict[str, Any],
    class_token: str,
    field_token: str,
    build: int,
) -> tuple[dict[str, Any] | None, str | None]:
    classes = database.get("classes", {})
    class_key = _metadata_hash_key(class_token)
    field_key = _metadata_hash_key(field_token)
    if not class_key or not field_key:
        return None, None

    visited: set[str] = set()

    def visit(key: str) -> tuple[dict[str, Any] | None, str | None]:
        if key in visited:
            return None, None
        visited.add(key)
        class_record = classes.get(key)
        if not isinstance(class_record, dict):
            return None, None

        properties = class_record.get("properties", {})
        property_record = properties.get(field_key) if isinstance(properties, dict) else None
        if isinstance(property_record, dict):
            revision = _active_revision(property_record.get("revisions"), build)
            if revision is not None:
                class_name = class_record.get("name") or key
                field_name = property_record.get("name") or field_key
                return revision, f"{class_name}.{field_name}"

        class_revision = _active_revision(class_record.get("revisions"), build)
        inherited: list[tuple[dict[str, Any], str | None]] = []
        if class_revision:
            for base_key in class_revision.get("bases", []):
                normalized_base = _metadata_hash_key(str(base_key))
                if normalized_base:
                    result, label = visit(normalized_base)
                    if result is not None:
                        inherited.append((result, label))
        if not inherited:
            return None, None
        first_revision = inherited[0][0]
        if any(
            result.get("type") != first_revision.get("type")
            or result.get("hasher") != first_revision.get("hasher")
            for result, _ in inherited[1:]
        ):
            raise UnsupportedHasherError(
                f"Multiple base classes of {class_record.get('name') or key} define "
                f"{field_key} with conflicting hash metadata. No algorithm was guessed."
            )
        return inherited[0]

    return visit(class_key)


def _rule_from_revision(
    revision: dict[str, Any],
    label: str,
) -> dict[str, Any] | None:
    value_type = revision.get("type")
    if not isinstance(value_type, list) or not value_type or value_type[0] != "Hash":
        return None

    hasher = revision.get("hasher")
    is_default = hasher is None
    if hasher is None:
        # The metadata format defines an omitted hasher as FNV-1a 32 over a
        # lowercased string, stored in 4 bytes.
        hasher = {"width": 4, "algorithm": "Fnv1a32", "lowercased": True}
    if not isinstance(hasher, dict):
        raise UnsupportedHasherError(f"{label}: invalid hasher metadata {hasher!r}.")

    width = hasher.get("width")
    algorithm = hasher.get("algorithm")
    lowercased = hasher.get("lowercased")
    algorithm_token = ALGORITHM_NAMES.get(str(algorithm).lower())
    if width not in (4, 8):
        raise UnsupportedHasherError(
            f"{label}: metadata specifies unsupported hash width {width!r} bytes."
        )
    if algorithm_token is None:
        raise UnsupportedHasherError(
            f"{label}: metadata specifies unsupported/unknown hash algorithm {algorithm!r}. "
            "No algorithm was guessed."
        )
    if lowercased is not True:
        raise UnsupportedHasherError(
            f"{label}: metadata has lowercased={lowercased!r}, but ritobin-tools string "
            "hash syntax hashes lowercased strings. No potentially incorrect hash was written."
        )
    return {
        "width": width,
        "algorithm": algorithm_token,
        "lowercased": lowercased,
        "is_default": is_default,
        "label": label,
    }


def _brace_delta(line: str) -> int:
    """Count structural braces, ignoring quoted strings and # comments."""
    depth = 0
    in_string = False
    escaped = False
    for char in line:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "#":
            break
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def _class_opening_token(line: str) -> str | None:
    for pattern in (_ENTRY_CLASS_RE, _FIELD_CLASS_RE, _BARE_CLASS_RE):
        match = pattern.match(line)
        if match:
            token = match.group("class")
            if token.lower() not in ("null", "true", "false"):
                return token
    return None


def _type_width(type_text: str) -> int | None:
    match = _HASH_TYPE_RE.match(type_text.strip())
    if not match:
        return None
    if match.group(1) is None:
        return None
    return 4 if match.group(1).lower() == "u32" else 8


def add_metadata_hash_algorithms(
    text: str,
    database: dict[str, Any] | None,
    build: int | None = None,
) -> tuple[str, int]:
    """Annotate quoted Hash scalar values using the active property hasher.

    Supports any class/property present in lol-meta-classes, including classes
    reached through Embed/Pointer values and embedded objects inside containers.
    It does not infer algorithms from width or class names.
    """
    output: list[str] = []
    contexts: list[tuple[str, int]] = []  # (class token, brace depth at class body)
    depth = 0
    replacements = 0
    if database is not None:
        build = int(build if build is not None else database["latest"])

    for original_line in text.splitlines(keepends=True):
        # Trim only the line ending; all other source bytes are retained.
        if original_line.endswith("\r\n"):
            line, ending = original_line[:-2], "\r\n"
        elif original_line.endswith(("\n", "\r")):
            line, ending = original_line[:-1], original_line[-1:]
        else:
            line, ending = original_line, ""

        while contexts and depth < contexts[-1][1]:
            contexts.pop()

        if contexts and depth == contexts[-1][1]:
            match = _HASH_STRING_FIELD_RE.match(line)
            if match:
                class_token = contexts[-1][0]
                field_token = match.group("field")
                type_text = match.group("type")
                rule = None
                label = f"{class_token}.{field_token}"

                if database is None:
                    raise MetadataError(
                        f"{label}: LeagueToolkit property-hasher metadata is unavailable. "
                        "The hasher cannot be determined safely, so no algorithm was guessed. "
                        "Restore the metadata cache or reconnect and retry the conversion."
                    )

                revision, resolved_label = _lookup_property_revision(
                    database, class_token, field_token, int(build)
                )
                if revision is not None:
                    label = resolved_label or label
                    property_type = revision.get("type")
                    if not isinstance(property_type, list) or not property_type or property_type[0] != "Hash":
                        raise MetadataError(
                            f"{label}: metadata for build {build} describes this property as "
                            f"{property_type[0] if isinstance(property_type, list) and property_type else 'an unknown type'}, "
                            "not Hash. Check the selected target build before converting."
                        )
                    rule = _rule_from_revision(revision, label)

                if rule is not None:
                    declared_width = _type_width(type_text)
                    has_explicit_width = "[" in type_text
                    expected_width = int(rule["width"])
                    # A bare hash with the metadata default (FNV-1a 32,
                    # lowercased) is already valid Ritobin syntax. Only an
                    # explicitly sized hash needs the algorithm annotation.
                    if not (rule.get("is_default") and not has_explicit_width):
                        # Bare `hash` defaults to 4 bytes in Ritobin. When
                        # metadata says otherwise, supply the explicit width.
                        if declared_width is not None and declared_width != expected_width:
                            raise UnsupportedHasherError(
                                f"{label}: text declares hash[u{32 if declared_width == 4 else 64}] "
                                f"but metadata for build {build} requires {expected_width * 8}-bit Hash. "
                                "The declaration was not silently changed; check the selected game build."
                            )
                        expected_width_name = "u32" if expected_width == 4 else "u64"
                        replacement_type = f"hash[{expected_width_name},{rule['algorithm']}]"
                        prefix = match.group("prefix")
                        assignment = match.group("assign")
                        value = match.group("value")
                        suffix = match.group("suffix")
                        line = f"{prefix}{replacement_type}{assignment}{value}{suffix}"
                        replacements += 1
                elif "[" in type_text:
                    # Upstream cannot convert a quoted string in an explicitly
                    # sized hash without an algorithm. Fail here with the
                    # schema/build context instead of silently guessing.
                    raise MetadataError(
                        f"No usable hasher metadata was found for {label} at build {build}. "
                        "ritobin-tools requires an explicit algorithm for a quoted hash[u32/u64] "
                        "string. Check the target build or specify the algorithm manually, "
                        "for example hash[u64,xxh3]."
                    )

        output.append(line + ending)
        opened_class = _class_opening_token(line)
        next_depth = depth + _brace_delta(line)
        if opened_class is not None and next_depth > depth:
            contexts.append((opened_class, next_depth))
        depth = next_depth
        while contexts and depth < contexts[-1][1]:
            contexts.pop()

    return "".join(output), replacements


def make_temporary_conversion_input(input_path: str) -> tuple[str, str | None, int]:
    """Return (effective_input, temporary_path, replacement_count).

    The source file is never modified. If a known string-valued Hash field
    needs an algorithm annotation, a temporary `.py`/Ritobin file is created;
    the caller must delete it after the converter finishes.
    """
    with open(input_path, "r", encoding="utf-8", newline="") as stream:
        source = stream.read()

    # Metadata is needed only for explicitly sized scalar Hash properties
    # whose value is a quoted string and whose algorithm is not already stated.
    # Numeric hashes need no algorithm, bare `hash` keeps Ritobin's default,
    # and `hash[u64,xxh3]` is already self-describing. This inexpensive local
    # scan must happen BEFORE any cache/index lookup or network check.
    has_metadata_candidate = any(
        (match := _HASH_STRING_FIELD_RE.match(line)) is not None
        and _type_width(match.group("type")) is not None
        for line in source.splitlines()
    )
    if not has_metadata_candidate:
        return input_path, None, 0

    database, source_description = load_metadata_database()
    build = _target_build(database) if database is not None else None
    rewritten, replacements = add_metadata_hash_algorithms(source, database, build)

    if replacements == 0:
        return input_path, None, 0

    _log(
        f"Prepared {replacements} metadata-defined hash string field(s) for build "
        f"{build} ({source_description})."
    )
    suffix = os.path.splitext(input_path)[1] or ".py"
    fd, temporary_path = tempfile.mkstemp(prefix="ltmao_ritobin_", suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(rewritten)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise

    return temporary_path, temporary_path, replacements
