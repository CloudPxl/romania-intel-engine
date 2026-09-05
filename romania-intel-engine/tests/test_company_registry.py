"""Offline guards for the ANAF company-verification client.

The live accuracy check lives in scripts/verify_company_lookup.py and hits
the real registers (9 real companies, 5 consecutive 100% runs required).
These are the complement: fully mocked, so the parsing, normalisation and
— most importantly — the honest-failure behaviour stay pinned even when
ANAF is unreachable, which is exactly when a client is most tempted to
start guessing.
"""
import httpx
import pytest

from addons import company_registry
from addons.company_registry import (
    _company_name_matches,
    _parse_anaf_company,
    cui_checksum_valid,
    normalize_cui,
    verify_company,
)

# A real ANAF v9 response, trimmed to the fields this product reads.
ANAF_FOUND = {
    "found": [
        {
            "date_generale": {
                "cui": 1590082,
                "denumire": "OMV PETROM SA",
                "adresa": "MUNICIPIUL BUCUREŞTI, SECTOR 1, STR. CORALILOR, NR.22",
                "nrRegCom": "J1997008302407",
                "cod_CAEN": 610,
                "forma_juridica": "SOCIETATE COMERCIALĂ PE ACŢIUNI",
                "data_inregistrare": "1992-12-09",
                "stare_inregistrare": "INREGISTRAT din data 23.10.1997",
                "statusRO_e_Factura": False,
            },
            "inregistrare_scop_Tva": {"scpTVA": True},
            "stare_inactiv": {"statusInactivi": False, "dataInactivare": "", "dataRadiere": ""},
            "adresa_sediu_social": {
                "sdenumire_Judet": "MUNICIPIUL BUCUREŞTI",
                "sdenumire_Localitate": "Sector 1 Mun. Bucureşti",
            },
        }
    ]
}


class TestCuiNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("RO1590082", 1590082),
            ("ro 1590082", 1590082),
            (" 1590082 ", 1590082),
            ("RO-1590082", 1590082),
            (1590082, 1590082),
            ("abc", None),
            ("", None),
            (None, None),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_cui(raw) == expected

    def test_checksum_accepts_real_cuis(self):
        # Every one of these was confirmed against ANAF's own register.
        for cui in (1590082, 14399840, 14056826, 13267221, 5888716, 199001):
            assert cui_checksum_valid(cui), cui

    def test_checksum_rejects_a_transposed_digit(self):
        assert not cui_checksum_valid(1590083)


class TestParsing:
    def test_caen_leading_zero_is_restored(self):
        # ANAF returns CAEN as an int (610), dropping the leading zero.
        # business_eligibility.py's programme tables list 4-character
        # strings, so a raw 610 would never match "0610".
        parsed = _parse_anaf_company(ANAF_FOUND["found"][0])
        assert parsed["caen_code"] == "0610"

    def test_flattens_the_nested_objects(self):
        parsed = _parse_anaf_company(ANAF_FOUND["found"][0])
        assert parsed["company_name"] == "OMV PETROM SA"
        assert parsed["trade_registry_number"] == "J1997008302407"
        assert parsed["county"] == "MUNICIPIUL BUCUREŞTI"
        assert parsed["vat_registered"] is True
        assert parsed["is_inactive_taxpayer"] is False


class TestNameMatching:
    def test_legal_form_suffixes_do_not_break_a_match(self):
        result = _company_name_matches("Dedeman SRL", "DEDEMAN S.R.L.")
        assert result["matches"] is True

    def test_a_different_company_is_flagged(self):
        result = _company_name_matches("Firma Inexistenta Test", "OMV PETROM SA")
        assert result["matches"] is False

    def test_partial_official_name_still_matches(self):
        result = _company_name_matches("Romgaz", 'SOCIETATEA NATIONALA DE GAZE NATURALE "ROMGAZ" SA')
        assert result["matches"] is True

    def test_nothing_to_compare_is_not_a_mismatch(self):
        result = _company_name_matches("", "OMV PETROM SA")
        assert result["compared"] is False
        assert result["matches"] is None


def _mock_transport(handler):
    """Swaps httpx's network layer for a callable, so nothing here can
    accidentally reach the real ANAF during a test run."""
    return httpx.MockTransport(handler)


class TestHonestFailure:
    @pytest.mark.asyncio
    async def test_unreachable_anaf_never_invents_a_company(self, monkeypatch):
        def handler(request):
            raise httpx.ConnectError("network down")

        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(company_registry.httpx, "AsyncClient", patched)
        result = await verify_company(1590082)
        assert result["verified"] is False
        assert result["found"] is False
        assert "company" not in result
        assert result.get("error")

    @pytest.mark.asyncio
    async def test_unknown_cui_is_reported_not_fabricated(self, monkeypatch):
        def handler(request):
            return httpx.Response(404)

        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(company_registry.httpx, "AsyncClient", patched)
        result = await verify_company(1590082)
        assert result["verified"] is False
        assert "ANAF" in (result.get("error") or "")

    @pytest.mark.asyncio
    async def test_verified_company_carries_the_registry_facts(self, monkeypatch):
        def handler(request):
            if "bilant" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "an": 2024,
                        "cui": 1590082,
                        "deni": "OMV PETROM SA",
                        "caen": 610,
                        "den_caen": "Extractia petrolului brut",
                        "i": [
                            {"indicator": "I13", "val_indicator": 29692697896, "val_den_indicator": "Cifra de afaceri neta"},
                            {"indicator": "I20", "val_indicator": 7207, "val_den_indicator": "Numar mediu de salariati"},
                        ],
                    },
                )
            return httpx.Response(200, json=ANAF_FOUND)

        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(company_registry.httpx, "AsyncClient", patched)
        result = await verify_company("RO1590082", declared_name="OMV Petrom SA")

        assert result["verified"] is True
        assert result["company"]["caen_code"] == "0610"
        assert result["financials"]["turnover_ron"] == 29692697896.0
        assert result["financials"]["employee_count"] == 7207
        assert result["name_match"]["matches"] is True
        assert result["registry_warnings"] == []

    @pytest.mark.asyncio
    async def test_inactive_taxpayer_raises_an_exclusion_warning(self, monkeypatch):
        payload = {"found": [dict(ANAF_FOUND["found"][0])]}
        payload["found"][0]["stare_inactiv"] = {
            "statusInactivi": True,
            "dataInactivare": "2024-03-01",
            "dataRadiere": "",
        }

        def handler(request):
            if "bilant" in str(request.url):
                return httpx.Response(200, json={"an": 2024, "cui": 1590082, "i": []})
            return httpx.Response(200, json=payload)

        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(company_registry.httpx, "AsyncClient", patched)
        result = await verify_company(1590082)

        assert result["verified"] is True
        assert result["company"]["is_inactive_taxpayer"] is True
        # Art. 165 Legea 98/2016 — this is a procurement exclusion ground,
        # so it has to reach the caller as a warning, not just a boolean
        # buried in the payload.
        assert any("INACTIV" in w for w in result["registry_warnings"])
