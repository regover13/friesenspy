"""Plausibilitäts-/Struktur-Validierung des kuratierten Flugzeug-Spec-Datensatzes."""
import math

from app import database
from app.llm import _build_result


def test_curated_specs_loadable_and_nonempty():
    specs = database.load_curated_specs()
    assert isinstance(specs, dict)
    assert len(specs) >= 100, "Datensatz sollte ~108 Typen enthalten"


def test_curated_specs_keys_normalized():
    specs = database.load_curated_specs()
    for code in specs:
        assert database.normalize_type_code(code) == code, f"Schlüssel nicht normalisiert: {code}"


def test_curated_specs_values_plausible():
    specs = database.load_curated_specs()
    for code, spec in specs.items():
        assert set(spec) >= {"make_model", "mtow_kg", "empty_kg", "fuel_full_kg"}, code
        mtow, empty, fuel = spec["mtow_kg"], spec["empty_kg"], spec["fuel_full_kg"]
        for v in (mtow, empty, fuel):
            assert isinstance(v, (int, float)) and math.isfinite(v) and v > 0, (code, v)
        assert empty < mtow, f"{code}: Leergewicht ({empty}) >= MTOW ({mtow})"
        assert isinstance(spec["make_model"], str) and spec["make_model"].strip(), code
        r = _build_result(spec["make_model"], float(mtow), float(empty), float(fuel))
        assert r["payload_kg"] >= 0, f"{code}: negative Zuladung"
