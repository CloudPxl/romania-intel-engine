"""Tests for scrapers/matrix/municipal_batch1.py — Brașov, Craiova,
Ploiești and Galați.

Fixtures are trimmed copies of markup and JSON captured live from each
portal on 2026-09-08 (see the scraper module's docstring for the
reconnaissance behind each endpoint), not invented shapes: the Brașov
block is one real `.accordion-item`, the Craiova rows are three real
`li.clearfix` entries including a genuinely status-prefixed one, the
Galați row is a real `div.item.front_post`, and the Ploiești payload is a
real `hotarari` post. Real values are kept as published — that is the
point of the money/CPV/CUI assertions below.

No network and no DATABASE_URL: every test drives `_parse`/`_build_signal`
directly, which is also what lets them assert on parsing without being
coupled to whatever the portals publish today.
"""

import json

import pytest
from bs4 import BeautifulSoup

from scrapers.matrix.municipal_batch1 import (
    BrasovMunicipalScraper,
    CraiovaMunicipalScraper,
    GalatiMunicipalScraper,
    PloiestiMunicipalScraper,
)

# One real notice from www.brasovcity.ro/primaria/achizitii/, trimmed to
# the labelled block the parser reads. Values are exactly as published.
BRASOV_HTML = """
<div class="accordion">
  <div class="accordion-item mb-2" role="listitem">
    <h2 class="accordion-header"><button>17-08-2026 ora 11:28 - termen expirat</button></h2>
    <div class="accordion-collapse collapse show">
      <div class="accordion-body">
        <a class="btn" href="/primaria/anunt-achizitie-procedura-proprie/31333539">Vezi în pagină separată</a>
        <p>Nr anunt: ADV1543667</p>
        <p>Tip anunt: Cumparari directe</p>
        <p>Data creare: 13.08.2026 11:31</p>
        <p>Data publicare: 13.08.2026 11:31</p>
        <p>Denumire oficiala: MUNICIPIUL BRASOV   CIF: 4384206</p>
        <p>Denumire contract: Servicii privind elaborarea Strategiei pentru Tineret a Municipiului Bra&#537;ov</p>
        <p>Data limita depunere oferta: 17.08.2026 11:28</p>
        <p>Tip contract: Servicii</p>
        <p>Cod si denumire CPV: 73000000-2 - Servicii de cercetare si de dezvoltare (Rev.2)</p>
        <p>Valoare estimata: 137.000,00  RON</p>
        <p>Descriere contract: Obiectivul general al contractului il reprezinta elaborarea Strategiei pentru Tineret.</p>
        <p>Criterii de atribuire: Atribuirea contractului se va face pe baza criteriului pretul cel mai scazut.</p>
      </div>
    </div>
  </div>
</div>
"""

# Three real rows from primariacraiova.ro/ro/c/54/... — the first carries
# the portal's own "Anulata - " status prefix.
CRAIOVA_HTML = """
<div class="section_content_text_ca"><ul>
  <li class="clearfix">
    <a href="/ro/a/3998/anulata---reabilitare-si-conservare-cladire">
      <i class="fa fa-newspaper-o"></i><b> Anulata - Reabilitare si conservare cladire-str. Romain Rolland nr. 8</b>
    </a>
    <span class="datet">21/08/2026, 11:48</span>
  </li>
  <li class="clearfix">
    <a href="/ro/a/4006/achizitie-tonere">
      <i class="fa fa-newspaper-o"></i><b> Achizitie tonere</b>
    </a>
    <span class="datet">31/08/2026, 16:06</span>
  </li>
  <li class="clearfix">
    <a href="/ro/a/4005/servicii-de-mentenanta-pe-baza-de-abonament-lunar">
      <i class="fa fa-newspaper-o"></i><b> Servicii de mentenanta, pe baza de abonament lunar, pentru remedierea defectiunilor</b>
    </a>
    <span class="datet">31/08/2026, 13:38</span>
  </li>
</ul></div>
"""

# One real row from primariagalati.ro's Domino announcements document.
GALATI_HTML = """
<div class="item front_post tranz p-border post type-post status-publish hentry">
  <h3 class="news-title"><a href="/portal/galati/portal.nsf/AllByUNID/Anunt+public-000A9FA6?OpenDocument">Anunț public</a></h3>
  <p class="meta">Data: <span class="post-date">07.09.2026</span></p>
  <p class="teaser">Privind vanzarea prin licitatie publica a unor imobile proprietatea privata a Municipiului Galati, in valoare de 1.250.000,00 lei.</p>
</div>
"""

# A real ploiesti.ro /wp-json/wp/v2/hotarari post.
PLOIESTI_HCL_POST = {
    "id": 51823,
    "date": "2026-09-02T15:19:42",
    "link": "https://ploiesti.ro/hotarari/hcl-364-2026/",
    "title": {"rendered": "HCL 364/2026"},
    "content": {
        "rendered": (
            "<p>Consiliul Local al Municipiului Ploie&#537;ti: V&#259;z&acirc;nd Referatul de aprobare "
            "nr. 412/31.08.2026 al Primarului Municipiului Ploie&#537;ti referitor la actualizarea "
            "Devizului General pentru Proiectul de reabilitare a strazii Gheorghe Doja; valoarea "
            "totala este de 2.532.544,93 lei.</p>"
        )
    },
}


def _brasov_signals():
    return BrasovMunicipalScraper()._parse(BeautifulSoup(BRASOV_HTML, "html.parser"))


class TestBrasovMunicipalScraper:
    def test_parses_the_notice(self):
        (signal,) = _brasov_signals()
        assert signal.project_title.startswith("Servicii privind elaborarea Strategiei")
        assert signal.entity_name == "Primăria Municipiului Brașov"
        assert signal.county == "Brasov"
        assert signal.published_date == "2026-08-13"
        assert signal.action_deadline == "2026-08-17"
        assert signal.source_url.endswith("/primaria/anunt-achizitie-procedura-proprie/31333539")

    def test_romanian_value_is_parsed_through_money_py(self):
        """'137.000,00' is dot-thousands / comma-decimal. Reading it the
        other way round yields 137.0 — a six-figure contract that sinks
        below every min-value filter while looking entirely legitimate."""
        (signal,) = _brasov_signals()
        assert signal.estimated_value_ron == 137000.0

    def test_authority_cif_is_captured_for_the_promoted_column(self):
        # Feeds opportunities.authority_cui via ai_refinery's promotion.
        (signal,) = _brasov_signals()
        assert signal.metadata["contracting_authority_cui"] == "4384206"

    def test_cpv_code_is_extracted_and_drives_nothing_it_should_not(self):
        (signal,) = _brasov_signals()
        assert signal.cpv_code == "73000000-2"

    def test_award_criterion_is_captured(self):
        (signal,) = _brasov_signals()
        assert "pretul cel mai scazut" in signal.metadata["award_criterion"].lower()

    def test_notice_number_is_captured(self):
        (signal,) = _brasov_signals()
        assert signal.metadata["notice_no"] == "ADV1543667"

    def test_value_is_read_from_its_own_label_not_the_whole_block(self):
        """A figure mentioned in the description (a penalty, a previous
        contract) must not be picked up as the budget."""
        html = BRASOV_HTML.replace(
            "Obiectivul general al contractului il reprezinta elaborarea Strategiei pentru Tineret.",
            "Penalitati de 9.999.999,00 RON se aplica la intarziere.",
        )
        (signal,) = BrasovMunicipalScraper()._parse(BeautifulSoup(html, "html.parser"))
        assert signal.estimated_value_ron == 137000.0

    def test_item_without_a_contract_name_is_skipped_not_faked(self):
        html = BRASOV_HTML.replace("Denumire contract:", "Alt camp:")
        assert BrasovMunicipalScraper()._parse(BeautifulSoup(html, "html.parser")) == []


class TestCraiovaMunicipalScraper:
    def _signals(self):
        return CraiovaMunicipalScraper()._parse(BeautifulSoup(CRAIOVA_HTML, "html.parser"))

    def test_parses_all_rows(self):
        assert len(self._signals()) == 3

    def test_status_prefix_becomes_a_stage_and_leaves_the_title(self):
        """The portal prefixes outcomes onto the title. Left in place, the
        same contract reads as two different projects once it's awarded;
        left unmapped, a cancelled procedure scores like a live one."""
        cancelled = self._signals()[0]
        assert cancelled.metadata["procurement_stage"] == "cancelled"
        assert cancelled.project_title.startswith("Reabilitare si conservare cladire")
        assert "Anulata" not in cancelled.project_title

    def test_unprefixed_row_is_treated_as_open(self):
        assert self._signals()[1].metadata["procurement_stage"] == "tender_open"

    def test_a_hyphen_inside_a_title_is_not_mistaken_for_a_status_prefix(self):
        row = self._signals()[2]
        assert row.metadata["procurement_stage"] == "tender_open"
        assert row.project_title.startswith("Servicii de mentenanta")

    def test_slashed_date_is_converted_to_iso(self):
        assert self._signals()[1].published_date == "2026-08-31"

    def test_value_is_honestly_unpublished_not_guessed(self):
        """The budget lives one click deeper and this scraper does not
        follow the link — so it reports no value rather than inventing
        one from the title."""
        assert all(s.estimated_value_ron == 0.0 for s in self._signals())

    def test_missing_container_yields_nothing_rather_than_raising(self):
        assert CraiovaMunicipalScraper()._parse(BeautifulSoup("<div></div>", "html.parser")) == []


class TestGalatiMunicipalScraper:
    def _signals(self):
        return GalatiMunicipalScraper()._parse(BeautifulSoup(GALATI_HTML, "html.parser"))

    def test_title_is_the_subject_not_the_repeated_category_label(self):
        """The text before "Data:" is a label the portal repeats across
        hundreds of rows ("Anunț public"). Using it as the title gave every
        row the same name and left keyword matching nothing to work with."""
        (signal,) = self._signals()
        assert signal.project_title.startswith("Privind vanzarea prin licitatie publica")
        assert signal.sub_category == "Anunț public"

    def test_dotted_date_is_converted_to_iso(self):
        (signal,) = self._signals()
        assert signal.published_date == "2026-09-07"

    def test_value_in_prose_is_parsed_through_money_py(self):
        (signal,) = self._signals()
        assert signal.estimated_value_ron == 1250000.0

    def test_row_without_a_subject_is_skipped(self):
        html = GALATI_HTML.replace(
            "Privind vanzarea prin licitatie publica a unor imobile proprietatea privata a Municipiului Galati, in valoare de 1.250.000,00 lei.",
            "",
        )
        assert GalatiMunicipalScraper()._parse(BeautifulSoup(html, "html.parser")) == []

    def test_archive_is_capped(self):
        """The portal serves its whole back-catalogue (4,915 rows at
        verification) in one document; emitting all of it every tick would
        swamp the feed and the tick deadline with one municipality."""
        many = GALATI_HTML * (GalatiMunicipalScraper.MAX_ROWS + 20)
        signals = GalatiMunicipalScraper()._parse(BeautifulSoup(many, "html.parser"))
        assert len(signals) <= GalatiMunicipalScraper.MAX_ROWS


class TestPloiestiMunicipalScraper:
    def _signal(self):
        return PloiestiMunicipalScraper()._build_signal(
            PLOIESTI_HCL_POST, "hotarari", "Hotărâre de Consiliu Local",
            "pre_tender_approved_indicators",
        )

    def test_hcl_title_is_enriched_with_its_real_subject(self):
        """An HCL's own title is just its number, which tells a bidder
        nothing and gives keyword matching nothing to match."""
        signal = self._signal()
        assert signal.project_title.startswith("HCL 364/2026 — ")
        assert "actualizarea Devizului General" in signal.project_title

    def test_value_in_the_decision_body_is_parsed(self):
        assert self._signal().estimated_value_ron == 2532544.93

    def test_stage_marks_it_as_a_pre_tender_signal(self):
        # A council decision approving indicators is the earliest public
        # signal an investment is coming — it must not rank as an open
        # procedure.
        assert self._signal().metadata["procurement_stage"] == "pre_tender_approved_indicators"

    def test_post_without_a_title_or_id_is_skipped(self):
        assert PloiestiMunicipalScraper()._build_signal(
            {"id": 1, "title": {"rendered": ""}, "content": {"rendered": "x"}},
            "hotarari", "H", "notice") is None
        assert PloiestiMunicipalScraper()._build_signal(
            {"title": {"rendered": "HCL 1/2026"}, "content": {"rendered": "x"}},
            "hotarari", "H", "notice") is None

    def test_hcl_without_a_recognisable_subject_keeps_its_number(self):
        post = {**PLOIESTI_HCL_POST, "content": {"rendered": "<p>Text fara formula standard.</p>"}}
        signal = PloiestiMunicipalScraper()._build_signal(
            post, "hotarari", "Hotărâre de Consiliu Local", "notice")
        assert signal.project_title == "HCL 364/2026"

    def test_announcements_are_not_title_enriched(self):
        # The enrichment is HCL-specific; an anunț already has a real title.
        signal = PloiestiMunicipalScraper()._build_signal(
            {**PLOIESTI_HCL_POST, "title": {"rendered": "Anunt privind ceva"}},
            "anunturi", "Anunț Public", "notice")
        assert signal.project_title == "Anunt privind ceva"


class TestZeroFabricationContract:
    """Every scraper in this batch must degrade to an empty list — never
    raise, never invent — when its portal is unreachable or redesigned."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [
        BrasovMunicipalScraper, CraiovaMunicipalScraper, GalatiMunicipalScraper,
    ])
    async def test_unreachable_portal_yields_no_signals(self, cls, monkeypatch):
        async def _no_body(self, url, timeout=15.0):
            return None

        monkeypatch.setattr(cls, "fetch_url", _no_body)
        assert await cls().fetch_market_consultations() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [
        BrasovMunicipalScraper, CraiovaMunicipalScraper, GalatiMunicipalScraper,
    ])
    async def test_unparseable_markup_yields_no_signals(self, cls, monkeypatch):
        async def _junk(self, url, timeout=15.0):
            return "<html><body>complet alt layout</body></html>"

        monkeypatch.setattr(cls, "fetch_url", _junk)
        assert await cls().fetch_market_consultations() == []

    @pytest.mark.asyncio
    async def test_ploiesti_non_json_yields_no_signals(self, monkeypatch):
        async def _html(self, url, timeout=30.0):
            return "<html>error page</html>"

        monkeypatch.setattr(PloiestiMunicipalScraper, "fetch_url", _html)
        assert await PloiestiMunicipalScraper().fetch_market_consultations() == []

    @pytest.mark.asyncio
    async def test_ploiesti_one_failing_post_type_does_not_cost_the_other(self, monkeypatch):
        async def _one_ok(self, url, timeout=30.0):
            if "hotarari" in url:
                raise RuntimeError("upstream 502")
            return json.dumps([{**PLOIESTI_HCL_POST, "title": {"rendered": "Anunt real"}}])

        monkeypatch.setattr(PloiestiMunicipalScraper, "fetch_url", _one_ok)
        signals = await PloiestiMunicipalScraper().fetch_market_consultations()
        assert len(signals) == 1
        assert signals[0].project_title == "Anunt real"

    @pytest.mark.asyncio
    async def test_a_parse_error_does_not_escape_and_take_down_the_tick(self, monkeypatch):
        async def _ok(self, url, timeout=15.0):
            return CRAIOVA_HTML

        def _boom(self, soup):
            raise ValueError("simulated parser regression")

        monkeypatch.setattr(CraiovaMunicipalScraper, "fetch_url", _ok)
        monkeypatch.setattr(CraiovaMunicipalScraper, "_parse", _boom)
        assert await CraiovaMunicipalScraper().fetch_market_consultations() == []


class TestOrchestratorRegistration:
    def test_all_four_are_registered(self):
        from scrapers.orchestrator import OpportunityOrchestrator

        names = {s.name for s in OpportunityOrchestrator().scrapers}
        for expected in ("BrasovMunicipal", "CraiovaMunicipal", "PloiestiMunicipal", "GalatiMunicipal"):
            assert expected in names

    def test_poll_intervals_are_municipal_scale(self):
        """A municipal HCL page changes a few times a week. Polling it at
        the cadence of a SEAP feed would spend the tick budget on pages
        that have not changed."""
        for cls in (BrasovMunicipalScraper, CraiovaMunicipalScraper,
                    PloiestiMunicipalScraper, GalatiMunicipalScraper):
            assert 720 <= cls().poll_interval_minutes <= 1440
