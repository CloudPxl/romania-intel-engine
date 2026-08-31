"""Tests for scrapers/adapters/*.py — the polymorphic CMS adapter
framework for county/municipal portal coverage.

Fixtures below are hand-built to match each platform's real, documented
mechanics (ASP.NET WebForms `__VIEWSTATE`/postback pagination for Indeco
Soft; a JSON array of Romanian-keyed fields for Sobis) rather than
invented shapes — see each adapter module's docstring for what's
genuinely standardized about the platform vs. what varies per
deployment. Run with `pytest` from romania-intel-engine/.
"""

import json

import httpx
import pytest

from scrapers.adapters.generic_portal_adapter import GenericPortalAdapter
from scrapers.adapters.indeco_adapter import IndecoAdapter, _map_columns
from scrapers.adapters.sobis_adapter import SobisAdapter

INDECO_PAGE_1 = """
<html><body><form>
<input type="hidden" name="__VIEWSTATE" value="VS1" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="VG1" />
<input type="hidden" name="__EVENTVALIDATION" value="EV1" />
<table id="GridView1">
<tr><th>Nr.</th><th>Titlu</th><th>Data adoptarii</th></tr>
<tr><td>101</td><td>HCL privind modernizare drum comunal</td><td>15.01.2026</td></tr>
<tr><td>102</td><td>HCL privind aprobare buget local</td><td>16.01.2026</td></tr>
</table>
<a href="javascript:__doPostBack('GridView1','Page$2')">2</a>
</form></body></html>
"""

INDECO_PAGE_2 = """
<html><body><form>
<input type="hidden" name="__VIEWSTATE" value="VS2" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="VG2" />
<input type="hidden" name="__EVENTVALIDATION" value="EV2" />
<table id="GridView1">
<tr><th>Nr.</th><th>Titlu</th><th>Data adoptarii</th></tr>
<tr><td>103</td><td>HCL privind reabilitare pod peste rau</td><td>17.01.2026</td></tr>
</table>
</body></html>
"""

INDECO_NO_VIEWSTATE_HOMEPAGE = "<html><body><h1>Primaria Exemplu</h1></body></html>"


class TestIndecoAdapter:
    def test_map_columns_reads_folded_headers_regardless_of_order(self):
        columns = _map_columns(["Titlu", "Valoare estimata", "Nr.", "Data publicarii"])
        assert columns["title"] == 0
        assert columns["value"] == 1
        assert columns["number"] == 2
        assert columns["published_date"] == 3

    @pytest.mark.asyncio
    async def test_detect_true_when_viewstate_and_known_path_present(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            return httpx.Response(200, text=INDECO_PAGE_1, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = IndecoAdapter()
        adapter.rate_limit_delay = 0
        async with adapter._new_client() as client:
            assert await adapter.detect("https://primaria-exemplu-indeco.ro", client) is True

    @pytest.mark.asyncio
    async def test_detect_false_without_viewstate(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            return httpx.Response(200, text=INDECO_NO_VIEWSTATE_HOMEPAGE, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = IndecoAdapter()
        adapter.rate_limit_delay = 0
        async with adapter._new_client() as client:
            assert await adapter.detect("https://primaria-fara-indeco.ro", client) is False

    @pytest.mark.asyncio
    async def test_extract_hcl_decisions_paginates_via_postback_and_filters_by_keyword(self, monkeypatch):
        pages = {"get_calls": 0, "post_calls": 0}

        async def fake_get(self, url, *a, **kw):
            pages["get_calls"] += 1
            return httpx.Response(200, text=INDECO_PAGE_1, request=httpx.Request("GET", url))

        async def fake_post(self, url, *a, **kw):
            pages["post_calls"] += 1
            return httpx.Response(200, text=INDECO_PAGE_2, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        adapter = IndecoAdapter()
        adapter.rate_limit_delay = 0
        notices = await adapter.extract_hcl_decisions(
            "https://primaria-exemplu-indeco.ro", "Cluj", ["modernizare", "reabilitare"],
        )

        assert pages["get_calls"] == 1
        assert pages["post_calls"] == 1  # followed the Page$2 postback exactly once, then stopped (no link on page 2)
        titles = {n["project_title"] for n in notices}
        assert titles == {
            "HCL privind modernizare drum comunal",
            "HCL privind reabilitare pod peste rau",
        }
        modernizare_notice = next(n for n in notices if "modernizare" in n["project_title"])
        assert modernizare_notice["source_id"] == "IDC-HCL-CLUJ-101"
        assert modernizare_notice["published_date"] == "2026-01-15"
        assert modernizare_notice["source_type"] == "HCL_LOCAL"


SOBIS_ANUNT = {
    "id": 555,
    "titlu": "Achizitie servicii de proiectare drum judetean DJ107",
    "valoareEstimata": "1.250.000,00",
    "dataPublicarii": "2026-08-01",
    "dataLimita": "2026-09-15",
    "cpv": "71322000-1",
}

SOBIS_HTML_FALLBACK_PAGE = """
<html><body>
<table>
<tr><td><a href="/docs/anunt-2.pdf">Anunt achizitie reabilitare sediu CJ</a> - valoare estimata 340.500,00 lei, termen 12.10.2026</td></tr>
</table>
</body></html>
"""


class TestSobisAdapter:
    def test_item_to_notice_maps_romanian_field_names(self):
        adapter = SobisAdapter()
        notice = adapter._item_to_notice(SOBIS_ANUNT, "Timis", "PAAP_LOCAL", "SBS-PAAP", "https://cjtimis.ro/anunturi/", 0)
        assert notice["source_id"] == "SBS-PAAP-TIMIS-555"
        assert notice["financial_value_ron"] == pytest.approx(1250000.0)
        assert notice["published_date"] == "2026-08-01"
        assert notice["action_deadline"] == "2026-09-15"
        assert notice["cpv_code"] == "71322000-1"

    @pytest.mark.asyncio
    async def test_detect_true_via_json_api(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            return httpx.Response(200, text="[]", request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = SobisAdapter()
        adapter.rate_limit_delay = 0
        async with adapter._new_client() as client:
            assert await adapter.detect("https://cj-exemplu-sobis.ro", client) is True

    @pytest.mark.asyncio
    async def test_extract_procurement_notices_via_json_api(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            if "api/public/anunturi" in url:
                return httpx.Response(200, text=json.dumps([SOBIS_ANUNT]), request=httpx.Request("GET", url))
            return httpx.Response(404, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = SobisAdapter()
        adapter.rate_limit_delay = 0
        notices = await adapter.extract_procurement_notices("https://cj-exemplu-sobis.ro", "Timis", days_back=365)
        assert len(notices) == 1
        assert notices[0]["source_id"] == "SBS-PAAP-TIMIS-555"

    @pytest.mark.asyncio
    async def test_extract_procurement_notices_falls_back_to_html_when_api_not_json(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            if "api/public/anunturi" in url:
                return httpx.Response(200, text="<html>not json</html>", request=httpx.Request("GET", url))
            return httpx.Response(200, text=SOBIS_HTML_FALLBACK_PAGE, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = SobisAdapter()
        adapter.rate_limit_delay = 0
        notices = await adapter.extract_procurement_notices("https://cj-exemplu-sobis-html.ro", "Sibiu", days_back=365)
        assert len(notices) == 1
        assert notices[0]["financial_value_ron"] == pytest.approx(340500.0)
        assert notices[0]["document_url"] == "https://cj-exemplu-sobis-html.ro/docs/anunt-2.pdf"


WP_POST_ACHIZITII = {
    "id": 42,
    "title": {"rendered": "Anunt de participare - reabilitare drumuri judetene"},
    "content": {"rendered": "<p>Valoare estimata 500.000,00 lei. CPV 45233120-6.</p>"},
    "date": "2026-07-10T09:00:00",
    "link": "https://cj-exemplu-wp.ro/achizitii/anunt-42",
}


class TestGenericPortalAdapter:
    @pytest.mark.asyncio
    async def test_extract_procurement_notices_via_wp_json(self, monkeypatch):
        async def fake_get(self, url, *a, **kw):
            if "wp-json" in url:
                return httpx.Response(200, text=json.dumps([WP_POST_ACHIZITII]), request=httpx.Request("GET", url))
            return httpx.Response(404, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        adapter = GenericPortalAdapter()
        adapter.rate_limit_delay = 0
        notices = await adapter.extract_procurement_notices("https://cj-exemplu-wp.ro", "Bihor", days_back=90)
        assert len(notices) == 1
        assert notices[0]["source_id"] == "GEN-PAAP-BIHOR-42"
        assert notices[0]["cpv_code"] == "45233120-6"
        assert notices[0]["financial_value_ron"] == pytest.approx(500000.0)
