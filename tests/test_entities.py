"""GLEIF, the only free key that joins companies across jurisdictions.

Every response here was recorded from the live API rather than written, because
the shapes that matter are the ones GLEIF actually sends: a legal name in the
native script with the Latin one filed as an alias, and a missing parent
returned as a 404 error document rather than a null field.
"""

import pytest
import requests

from conftest import GLEIF_ROUTES, TOYOTA, TOYOTA_CHILD, replay
from macro_mcp import entities


@pytest.fixture
def gleif(monkeypatch):
    return replay(monkeypatch, GLEIF_ROUTES)


def test_a_legal_name_comes_back_in_the_script_it_is_registered_in(gleif):
    """Toyota's legal name is トヨタ自動車株式会社. An agent that reported only
    this would be right and useless, so the Latin name travels with it."""
    got = entities.get(TOYOTA)
    assert got["name"] == "トヨタ自動車株式会社"
    assert got["other_names"] == ["Toyota Motor Corporation"]
    assert got["lei"] == TOYOTA
    assert got["country"] == "JP" and got["jurisdiction"] == "JP"
    assert got["status"] == "ACTIVE"
    assert got["bic"] == ["TOMCJP22XXX"]


def test_search_asks_over_names_rather_than_fulltext_or_the_legal_name(gleif):
    """Three filters were on the table and only one is right. `legalName` misses
    Toyota, whose legal name is Japanese. `fulltext` also matches addresses, so
    it answered "Banco Santander" with an unrelated company near the Spanish
    city of that name and did not return the bank in twenty-five hits.
    `entity.names` covers the legal name and the other names, which is what the
    Japanese case needed all along. A wrong filter name is ignored by GLEIF
    rather than rejected, so this asserts the URL."""
    entities.search("Toyota Motor", "jp", 5)
    url = gleif.urls[-1]
    assert "filter%5Bentity.names%5D=Toyota+Motor" in url
    assert "fulltext" not in url and "legalName" not in url
    assert "filter%5Bentity.legalAddress.country%5D=JP" in url  # upper-cased


def test_more_hits_are_fetched_than_are_returned_so_ranking_has_something_to_do(gleif):
    """One page in, the best five out. Ranking a page of five cannot rescue an
    entity that was never on it, and "Banco Santander" matches 41 records
    without the bank among the first five."""
    entities.search("Toyota Motor", "JP", 5)
    assert "page%5Bsize%5D=25" in gleif.urls[-1]


def test_search_reports_the_provider_s_total_not_the_page_size(gleif):
    """The count an agent needs is how many matched, not how many were shown."""
    got = entities.search("Toyota Motor", "JP", 5)
    assert got["total"] == 1
    assert [h["lei"] for h in got["hits"]] == [TOYOTA]
    assert got["hits"][0]["name"] == "トヨタ自動車株式会社"


def test_a_country_filter_is_optional_and_omitted_when_absent(gleif):
    entities.search("Toyota Motor")
    assert "legalAddress.country" not in gleif.urls[-1]


def test_the_json_api_accept_header_is_sent_on_every_request(gleif):
    entities.get(TOYOTA)
    assert gleif.asked[-1].headers["Accept"] == "application/vnd.api+json"


def test_a_missing_parent_is_reported_as_absent_rather_than_raising(gleif):
    """GLEIF answers 404 with an error document for a relationship that does
    not exist. Toyota is the top of its own tree, so both parents are absent
    and it still has children."""
    got = entities.ownership(TOYOTA)
    assert got["lei"] == TOYOTA
    assert got["direct_parent"] is None
    assert got["ultimate_parent"] is None
    assert len(got["direct_children"]) == 11
    assert "KOROMO UK 2 PLC" in [c["name"] for c in got["direct_children"]]


def test_a_child_resolves_to_its_parent_and_to_no_children_of_its_own(gleif):
    """The other side of the same 404: a leaf has parents and no children, and
    both branches have to survive it."""
    got = entities.ownership(TOYOTA_CHILD)
    assert got["direct_parent"]["lei"] == TOYOTA
    assert got["ultimate_parent"]["name"] == "トヨタ自動車株式会社"
    assert got["direct_children"] == []


def test_ownership_costs_three_requests_and_names_them(gleif):
    """GLEIF publishes each relationship as its own resource, so there is no
    one call for a tree."""
    entities.ownership(TOYOTA)
    assert [u.rsplit("/", 1)[-1].split("?")[0] for u in gleif.urls] == [
        "direct-parent", "ultimate-parent", "direct-children"]


def test_an_error_that_is_not_a_missing_relationship_still_raises(monkeypatch):
    """Catching every HTTPError would report a rate-limited or broken service
    as an entity with no parents, which is a wrong answer rather than a
    failure."""
    routes = dict(GLEIF_ROUTES)
    routes[f"{TOYOTA}/direct-parent"] = ("gleif_not_found.json", "application/vnd.api+json", 500)
    replay(monkeypatch, routes)
    with pytest.raises(requests.HTTPError):
        entities.ownership(TOYOTA)


def test_only_a_handful_of_aliases_are_returned(gleif, monkeypatch):
    """Some entities carry dozens across scripts, against a response format
    whose point is to be small. Synthetic, because no recorded record here has
    more than one."""
    record = {"id": "X", "attributes": {"entity": {
        "legalName": {"name": "Example AG"},
        "otherNames": [{"name": f"Alias {i}"} for i in range(6)],
        "transliteratedOtherNames": [{"name": "Beispiel"}],
        "legalAddress": {"country": "DE"}, "status": "ACTIVE"}}}
    assert entities._summary(record)["other_names"] == [f"Alias {i}" for i in range(4)]


# --- what the evals found ----------------------------------------------------

def hit(name: str, *aliases: str) -> dict:
    return {"name": name, "other_names": list(aliases)}


def test_an_exact_name_outranks_one_that_merely_contains_the_query():
    """An eval asked for "Banco Santander". GLEIF returned 41 hits led by
    EDUARDO R FERNANDEZ PEREZ SL, which matches because Santander is a Spanish
    city, and filtered to Spain the bank was the last of five."""
    hits = [hit("EDUARDO R FERNANDEZ PEREZ SL"),
            hit("FUNDACION BANCO SANTANDER"),
            hit("BANCO SANTANDER S.A.", "BANCO DE SANTANDER SA."),
            hit("MUTUALIDAD DE EMPLEADOS DEL BANCO SANTANDER")]
    ranked = sorted(hits, key=lambda h: entities._score("Banco Santander", h))
    assert [h["name"] for h in ranked] == [
        "BANCO SANTANDER S.A.",                       # starts with the query
        "FUNDACION BANCO SANTANDER",                  # contains it, shorter
        "MUTUALIDAD DE EMPLEADOS DEL BANCO SANTANDER",
        "EDUARDO R FERNANDEZ PEREZ SL"]               # no name match at all


def test_a_name_matching_only_through_an_alias_still_ranks():
    """Toyota's legal name is in Japanese, so the Latin name an agent types
    reaches the record through otherNames or not at all."""
    japanese = hit("トヨタ自動車株式会社", "Toyota Motor Corporation")
    assert entities._score("Toyota Motor Corporation", japanese)[0] == 0
    assert entities._score("Toyota Motor", japanese)[0] == 1


def test_ownership_says_how_many_children_there_are(gleif):
    """A list of 50 that is the first 50 of 200 reads as the whole tree. The
    provider's own count is in the response and was being dropped."""
    got = entities.ownership(TOYOTA)
    assert got["direct_children_total"] == 11
    assert len(got["direct_children"]) == 11
    assert "children_truncated" not in got


def test_a_company_with_no_children_reports_none_rather_than_nothing(gleif):
    got = entities.ownership(TOYOTA_CHILD)
    assert got["direct_children"] == [] and got["direct_children_total"] == 0


def test_an_accented_name_is_matched_by_its_unaccented_spelling():
    """Typed "Nestle", NESTLÉ S.A. scored nothing and the company ranked below
    its own subsidiaries. GLEIF matches either spelling; ranking has to too."""
    assert entities._score("Nestle", hit("NESTLÉ S.A."))[0] == 1
    assert entities._score("Nestlé", hit("NESTLE S.A."))[0] == 1


def test_the_operating_company_outranks_a_branch_of_the_same_name():
    """The Dutch and French branches of Banco Santander are both legally named
    "Banco Santander S.A.", exactly as the Spanish company is. Name matching
    cannot separate them, and the parent is what was asked for."""
    def entity(name, category):
        return {**hit(name), "category": category, "status": "ACTIVE"}

    ranked = sorted([entity("Banco Santander S.A.", "BRANCH"),
                     entity("BANCO SANTANDER S.A. ADRHEDGED", "FUND"),
                     entity("BANCO SANTANDER S.A.", "GENERAL")],
                    key=lambda h: entities._score("Banco Santander", h))
    assert [h["category"] for h in ranked] == ["GENERAL", "BRANCH", "FUND"]


def test_a_dissolved_entity_ranks_below_a_live_one_it_ties_with():
    """The docstring has always said to check status. Ordering on it means an
    agent taking the first hit is not handed a dead company."""
    def entity(status):
        return {**hit("BANCO X"), "category": "GENERAL", "status": status}
    assert entities._score("Banco X", entity("ACTIVE")) < \
           entities._score("Banco X", entity("INACTIVE"))
