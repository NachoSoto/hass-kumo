"""Preserve device credentials omitted by Kumo's cloud API."""


def _units(kumo_dict):
    if not isinstance(kumo_dict, list) or len(kumo_dict) < 3:
        return {}

    def visit(node):
        yield from node.get("zoneTable", {}).items()
        for child in node.get("children", []):
            yield from visit(child)

    return dict(visit(kumo_dict[2]))


def preserve_cached_credentials(fresh, cached):
    """Fill missing credentials by serial, returning whether all units are usable.

    Fresh nonempty credentials take precedence. Only the fresh response is
    modified; devices absent from that response are never restored from cache.
    """
    fresh_units = _units(fresh)
    cached_units = _units(cached)
    for serial, unit in fresh_units.items():
        previous = cached_units.get(serial, {})
        for field in ("password", "cryptoSerial"):
            if not unit.get(field) and previous.get(field):
                unit[field] = previous[field]
    return bool(fresh_units) and all(
        unit.get("password") and unit.get("cryptoSerial")
        for unit in fresh_units.values()
    )
