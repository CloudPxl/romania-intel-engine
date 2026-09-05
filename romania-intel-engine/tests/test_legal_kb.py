"""Guards on the ingested legislation.

The knowledge base exists so drafted documents quote real provisions
instead of remembered ones. These pin the two failure modes that would
quietly defeat that: a repealed article being served as if it were in
force, and the extractor harvesting the wrong text for an article number.

Both are real regressions caught during the build, not hypotheticals —
Art. 6 of Legea 101/2016 is repealed and still widely cited, and the first
extraction pass served an amending ordinance's Article 2 as if it were
Legea 98/2016's.
"""
import pytest

import legal_kb


@pytest.mark.skipif(not legal_kb.is_available(), reason="run scripts/build_legal_kb.py first")
class TestIngestedCorpus:
    def test_all_four_laws_present(self):
        keys = {law["key"] for law in legal_kb.stats()["laws"]}
        assert {"L98/2016", "L99/2016", "L100/2016", "L101/2016"} <= keys

    def test_corpus_is_substantial(self):
        assert legal_kb.stats()["article_count"] > 500

    @pytest.mark.parametrize(
        "key,must_contain",
        [
            # Each expectation is a distinctive phrase from the article's
            # own operative text, so a mis-extraction that silently swaps
            # in another article's body fails here rather than surfacing as
            # a wrong quotation in a customer's document.
            ("L98/2016:2", "scopul prezentei legi"),
            ("L98/2016:156", "specificațiile tehnice"),
            ("L98/2016:165", "obligațiile privind plata impozitelor"),
            ("L98/2016:193", "duae"),
            ("L98/2016:210", "neobișnuit de scăzut"),
            ("L101/2016:8", "consiliul"),
        ],
    )
    def test_articles_carry_their_own_text(self, key, must_contain):
        text = (legal_kb.quote(key) or "").lower()
        assert must_contain in text, f"{key} does not contain {must_contain!r}: {text[:160]}"

    def test_article_2_is_the_law_not_an_amending_ordinance(self):
        # The first extractor took the longest body per article number,
        # which picked an amending OUG's Article 2 — its text even said
        # "prezentei ordonanțe de urgență". The law's own article always
        # comes first in the consolidated page.
        text = (legal_kb.quote("L98/2016:2") or "").lower()
        assert "prezentei ordonanțe de urgență" not in text

    def test_repealed_article_is_detected(self):
        # Art. 6 of Legea 101/2016 (notificarea prealabilă) was repealed by
        # OUG 45/2018 and is still cited in guidance and by LLMs.
        assert legal_kb.is_repealed("L101/2016:6") is True

    def test_repealed_articles_are_excluded_from_topics(self):
        for article in legal_kb.topic("remedies")["articles"]:
            assert article["repealed"] is False

    def test_repealed_articles_are_excluded_from_search(self):
        for hit in legal_kb.search("contestație", law_keys=["L101/2016"], limit=25):
            assert not legal_kb.is_repealed(hit["key"])

    def test_amendment_history_is_stripped_from_quotations(self):
        # The portal interleaves "(la 22-12-2017, ... a fost modificat de
        # ...)" into the body. That is provenance, not obligation, and it
        # reads as noise inside a formal letter.
        text = legal_kb.quote("L98/2016:210", max_chars=2000) or ""
        assert "a fost modificat de" not in text
        assert "MONITORUL OFICIAL" not in text

    def test_abnormally_low_price_topic_has_no_invented_threshold(self):
        # The widely-repeated "under 80% of the estimated value triggers
        # Art. 210" is not in the article. The only 80% in Legea 98/2016 is
        # Art. 31, on in-house awards. If a future edit reintroduces the
        # claim by pointing this topic at the wrong article, this fails.
        text = " ".join(a["text"] for a in legal_kb.topic("abnormally_low_price")["articles"])
        assert "80%" not in text

    def test_every_topic_resolves_to_real_articles(self):
        for name in legal_kb.TOPICS:
            resolved = legal_kb.topic(name)
            assert resolved["articles"], f"topic {name} resolved to nothing"
            for article in resolved["articles"]:
                assert article["text"].strip()
                assert article["citation"].startswith("art. ")


class TestDegradesWithoutKb:
    def test_missing_kb_returns_empty_rather_than_raising(self, monkeypatch, tmp_path):
        # A generator must still produce a complete document when the
        # knowledge base has not been built — citations are additive.
        monkeypatch.setattr(legal_kb, "_kb", None)
        monkeypatch.setattr(legal_kb, "KB_PATH", tmp_path / "absent.json")
        try:
            assert legal_kb.is_available() is False
            assert legal_kb.get_article("L98/2016:210") is None
            assert legal_kb.topic("remedies")["articles"] == []
            assert legal_kb.search("orice") == []
        finally:
            monkeypatch.setattr(legal_kb, "_kb", None)
