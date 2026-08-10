"""Bundesbank serves valid data through invalid XML. These pin each repair.

Every case here was a live failure, so the assertions check values rather than
merely that parsing did not raise.
"""

import math

import pytest
import sdmx

from conftest import parse, raw
from macro_mcp import bundesbank as bbk


def test_urn_repair_adds_missing_class_segment():
    before = b'urn="urn:sdmx:org.sdmx.infomodel.codelist=BBK:CL_X(1.0)"'
    assert bbk._repair(before) == b'urn="urn:sdmx:org.sdmx.infomodel.codelist.Codelist=BBK:CL_X(1.0)"'


def test_urn_repair_leaves_valid_urns_alone():
    valid = b'urn:sdmx:org.sdmx.infomodel.codelist.Codelist=BBK:CL_X(1.0)'
    assert bbk._repair(valid) == valid


def test_valueless_attribute_element_is_dropped():
    payload = (b'<generic:Value id="BBK_UNIT" value="PROZENT"></generic:Value>'
               b'<generic:Value id="BBK_UNIT_ENG"></generic:Value>')
    out = bbk._repair(payload)
    assert b'BBK_UNIT_ENG' not in out
    assert b'value="PROZENT"' in out  # the populated one survives


def test_codelist_fixture_needs_repair_and_then_yields_english_codes():
    payload = raw("bbk_codelist.xml")
    with pytest.raises(sdmx.exceptions.XMLParseError):
        parse(payload)

    cl = parse(bbk._repair(payload)).codelist["CL_BBK_STD_FREQ"]
    codes = {c.id: str(c.name) for c in cl}
    assert len(codes) == 6
    assert codes["D"] == "Daily"
    assert codes["A"] == "Annual"


def test_data_fixture_needs_repair_and_then_yields_yields():
    payload = raw("bbk_data.xml")
    with pytest.raises(sdmx.exceptions.XMLParseError):
        parse(payload)

    df = sdmx.to_pandas(parse(bbk._repair(payload))).reset_index()
    df.columns = [*df.columns[:-1], "value"]
    by_date = dict(zip(df["TIME_PERIOD"], df["value"]))
    # 10-year Bund yield, in percent.
    assert by_date["2024-01-02"] == pytest.approx(2.13)
    assert by_date["2024-01-03"] == pytest.approx(2.10)
    # New Year's Day carries OBS_STATUS=K and no value.
    assert math.isnan(by_date["2024-01-01"])


def test_dsd_fixture_has_dimensions_but_empty_inline_codelists():
    """Why _codes falls back for BBK: the codelist object exists but is empty,
    so a `cl is None` check would silently yield zero codes."""
    dsd = parse(bbk._repair(raw("bbk_dsd.xml"))).structure["BBK_SEIS"]
    dims = [d.id for d in dsd.dimensions.components]
    assert "BBK_STD_FREQ" in dims and "TIME_PERIOD" in dims

    freq = next(d for d in dsd.dimensions.components if d.id == "BBK_STD_FREQ")
    inline = getattr(getattr(freq, "local_representation", None), "enumerated", None)
    assert inline is not None
    assert len(inline) == 0


def test_data_query_requires_a_pinned_dimension(monkeypatch):
    """An unpinned BBSIS query returns >100MB, so it must never be attempted."""
    monkeypatch.setattr(bbk, "dimensions", lambda flow: ["BBK_STD_FREQ", "BBK_SEIS_ITEM"])
    called = []
    monkeypatch.setattr(bbk, "_get", lambda *a, **k: called.append(a))

    with pytest.raises(ValueError, match="at least one"):
        bbk.data("BBSIS", {}, {})
    assert not called

    bbk.data("BBSIS", {"BBK_STD_FREQ": "D"}, {})
    assert called and called[0][0] == "data/BBSIS/D."
