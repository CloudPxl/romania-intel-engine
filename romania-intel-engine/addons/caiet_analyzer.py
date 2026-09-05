import io
import logging
import re
from typing import Dict, Any, List, Optional
from pypdf import PdfReader
import docx

import legal_kb

logger = logging.getLogger("CaietAnalyzer")

# ISO/SR EN standard numbers as they actually appear in Romanian caiete de
# sarcini — "ISO 9001", "SR EN ISO 14001", "ISO/IEC 27001" — captured by
# family so "ISO 9001:2015" and "ISO 9001" both fold to the same entry.
_ISO_PATTERN = re.compile(
    r"(?:SR\s+EN\s+)?ISO(?:/IEC)?\s*(\d{4,5})(?::\d{4})?",
    re.IGNORECASE,
)

# Turnover ("cifra de afaceri") clauses: the number and its unit almost
# always sit within a short window of the trigger phrase, e.g. "cifra de
# afaceri medie anuala ... de minim 5.000.000 lei" — so the pattern
# captures the phrase and a following amount+unit rather than requiring
# an exact fixed template.
_TURNOVER_PATTERN = re.compile(
    r"cifr\w*\s+de\s+afaceri[^.\n]{0,120}?"
    r"([\d.,]{3,})\s*(lei|ron|euro|eur)",
    re.IGNORECASE,
)

# Roles that count as "key personnel" when a caiet lists mandatory experts.
# Matched as whole phrases so "manager" alone (too generic, fires on
# unrelated text) never counts without its qualifying noun.
_KEY_PERSONNEL_PATTERNS = [
    "manager de proiect", "responsabil tehnic cu executia", "responsabil tehnic",
    "sef de santier", "coordonator ssm", "responsabil ssm",
    "responsabil cu controlul calitatii", "auditor energetic",
    "inginer electroenergetician", "inginer de sistem", "arhitect de solutie",
    "responsabil securitate cibernetica", "responsabil protectia datelor",
    "expert cheie", "expert tehnic", "diriginte de santier",
    "responsabil de mediu", "medic coordonator",
]

# Mandatory-equipment phrasing: "dotare cu", "utilaje precum", "echipamente
# minime" etc. followed by the actual equipment noun phrase up to the next
# sentence boundary.
_EQUIPMENT_TRIGGER_PATTERN = re.compile(
    r"(?:dotare(?:a)?\s+cu|utilaje?(?:le)?\s+(?:minime?\s+)?(?:necesare|solicitate|precum)?|"
    r"echipamente?(?:le)?\s+minime?(?:\s+necesare)?)"
    r"\s*[:\-]?\s*([^.\n]{5,200})",
    re.IGNORECASE,
)

# Matching runs through text_utils, which folds diacritics and matches whole
# words. This matters more here than anywhere else in the codebase: a real
# caiet de sarcini is written in correct Romanian ("experiență similară"),
# while these patterns are written unaccented, so the previous
# `keyword in text.lower()` test silently found nothing in exactly the
# documents this analyser exists to check. Whole-word matching also stops
# "marca" from firing inside "marcare" or "remarcă".
RESTRICTIVE_PATTERNS = [
    {
        "keyword": "experienta similara",
        "legal_topic": "qualification_criteria",
        # Romanian is inflected and legal drafting uses the genitive freely
        # ("dovada experienței similare"), so the declined forms are listed
        # explicitly. Whole-word matching will not reach them from the
        # nominative, and loosening to prefix matching would start firing
        # on unrelated words.
        "variants": [
            "experienta similara", "experientei similare", "experiente similare",
            "experienta anterioara similara", "experienta similara indeplinita",
        ],
        "risk": "Mediu",
        "warning": "Verificați dacă cerința de experiență similară este proporțională cu obiectul și valoarea contractului; cerințele disproporționate încalcă principiul proporționalității (art. 2 alin. (2) din Legea nr. 98/2016).",
    },
    {
        "keyword": "termen de livrare scurt",
        "legal_topic": "principles",
        "variants": ["termen de livrare sub", "livrare in maxim", "termen de executie sub"],
        "risk": "Ridicat",
        "warning": "Termen de livrare neobișnuit de scurt, care poate favoriza un operator cu stoc pre-constituit.",
    },
    {
        "keyword": "standard proprietar",
        "legal_topic": "technical_specifications",
        "variants": ["certificare specifica", "certificat specific", "standard propriu"],
        "risk": "Ridicat",
        "warning": "Cerință de standard tehnic proprietar fără mențiunea „sau echivalent”.",
    },
    {
        "keyword": "autorizatie de producator",
        "legal_topic": "qualification_criteria",
        "variants": ["autorizatie producator", "autorizatie de producator", "scrisoare de autorizare", "certificat de autorizare producator"],
        "risk": "Critic",
        "warning": "Obligativitatea prezentării autorizației directe de producător la depunerea ofertei este frecvent calificată drept clauză restrictivă în practica CNSC.",
    },
    {
        "keyword": "marca sau producator indicat",
        "legal_topic": "technical_specifications",
        "variants": ["marca", "marci", "producator anume", "model anume"],
        "risk": "Critic",
        "warning": "Indicarea unei mărci, a unui producător sau a unui model fără sintagma „sau echivalent” restrânge concurența (art. 156 din Legea nr. 98/2016 privind specificațiile tehnice).",
    },
]

class TextExtractionError(Exception):
    """The document could not be parsed at all (corrupt, encrypted, or not
    actually the format its extension claims).

    This exists because the alternative — what this module used to do —
    is actively dangerous here. On a parse failure it fell back to
    `file_bytes.decode("utf-8", errors="ignore")` on the raw binary, which
    yields near-garbage that still *looks* like text. analyze_specification_text
    then found none of its patterns in that garbage and returned
    "Scazut (Specificatii Deschise)" with no red flags — presenting a
    document that was never actually read as if it had been verified clean,
    to a user deciding whether to bid. Failing loudly is the only honest
    option: the same "report nothing rather than fabricate something"
    convention the scrapers follow.
    """


class CaietDeSarciniAnalyzer:
    @staticmethod
    def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
        """Returns the document's text, or raises TextExtractionError if the
        file cannot be parsed.

        An empty return is meaningful and distinct from an error: it means the
        file parsed correctly but carries no text layer (a scanned PDF), which
        the caller should route to the async OCR pipeline rather than treat as
        a failure.
        """
        filename_lower = filename.lower()

        if filename_lower.endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                pages = reader.pages
            except Exception as e:
                logger.error(f"[CaietAnalyzer] Unreadable PDF '{filename}': {e}")
                raise TextExtractionError(
                    "Fișierul PDF nu a putut fi citit (posibil corupt, criptat sau protejat cu parolă)."
                ) from e

            # Per-page, so one malformed page in an otherwise readable
            # document costs that page rather than the whole analysis.
            chunks: List[str] = []
            failed_pages = 0
            for index, page in enumerate(pages):
                try:
                    text = page.extract_text()
                except Exception as e:
                    failed_pages += 1
                    logger.warning(f"[CaietAnalyzer] Page {index + 1} of '{filename}' failed to extract: {e}")
                    continue
                if text:
                    chunks.append(text)

            if failed_pages and not chunks:
                raise TextExtractionError(
                    "Nicio pagină din documentul PDF nu a putut fi procesată."
                )
            return "\n".join(chunks).strip()

        if filename_lower.endswith(".docx"):
            try:
                doc = docx.Document(io.BytesIO(file_bytes))
                return "\n".join(para.text for para in doc.paragraphs).strip()
            except Exception as e:
                logger.error(f"[CaietAnalyzer] Unreadable DOCX '{filename}': {e}")
                raise TextExtractionError(
                    "Fișierul DOCX nu a putut fi citit (posibil corupt sau într-un format neacceptat)."
                ) from e

        # Any other extension is treated as plain text. Decoding with
        # errors="ignore" is legitimate here (unlike the old PDF/DOCX
        # fallback): the bytes are genuinely expected to be text, and a few
        # undecodable characters shouldn't fail an otherwise readable file.
        return file_bytes.decode("utf-8", errors="ignore").strip()

    @staticmethod
    async def load_extracted_text(doc_id: Optional[str] = None, notice_id: Optional[str] = None) -> Optional[str]:
        """Additive path alongside extract_text_from_file(): pulls text
        already produced by workers/document_tasks.py's async ingestion
        pipeline (workers/pdf_preprocessor.py + workers/ocr_engine.py) out of
        the document_extractions table, instead of asking the caller to
        re-upload and re-parse the same bytes inline. This is what lets a
        100+ page scanned HCL/CNAIR PDF — too slow to parse inline, which is
        exactly why that async pipeline exists — reach this analyzer's
        keyword/risk scan at all.

        Returns None when the row doesn't exist, hasn't finished processing
        yet (status != "done"), or no database is configured — callers
        should treat that as "not ready", not as "no text". The existing
        inline-upload code path (extract_text_from_file, called directly
        from api.py's synchronous /upload-caiet route) is completely
        unaffected by this method's existence.
        """
        import document_extractions

        row = None
        if doc_id:
            row = await document_extractions.get_extraction(doc_id)
        elif notice_id:
            row = await document_extractions.get_latest_extraction_for_notice(notice_id)
        else:
            return None
        if not row or row.get("status") != "done":
            return None
        return row.get("raw_text") or None

    @staticmethod
    def extract_qualification_criteria(text: str) -> Dict[str, Any]:
        """Pulls the structured qualification requirements out of a caiet
        de sarcini — turnover floor, required ISO/SR EN certifications, key
        personnel roles, and mandatory equipment — as distinct from the
        restrictive-clause scan above, which flags *anti-competitive*
        wording rather than *what a bidder must show* to qualify at all.
        Both readings matter to a bidder deciding whether to pursue a
        tender: one says "can I compete", the other says "am I eligible".
        """
        from text_utils import matching_terms

        turnover_hits = []
        for match in _TURNOVER_PATTERN.finditer(text):
            amount, unit = match.group(1), match.group(2)
            turnover_hits.append(f"{amount} {unit.upper()}")

        iso_hits = sorted({f"ISO {m.group(1)}" for m in _ISO_PATTERN.finditer(text)})

        personnel_hits = matching_terms(text, _KEY_PERSONNEL_PATTERNS)

        equipment_hits: List[str] = []
        for match in _EQUIPMENT_TRIGGER_PATTERN.finditer(text):
            snippet = match.group(1).strip(" :-")
            if snippet and snippet not in equipment_hits:
                equipment_hits.append(snippet)

        return {
            "turnover_requirements": turnover_hits[:5] or ["Nespecificat explicit în textul analizat"],
            "required_certifications": iso_hits or ["Nicio certificare ISO/SR EN identificată explicit"],
            "key_personnel_roles": personnel_hits or ["Niciun rol de personal-cheie identificat explicit"],
            "mandatory_equipment": equipment_hits[:5] or ["Niciun echipament obligatoriu identificat explicit"],
            "extraction_note": (
                "Extragere automată bazată pe tipare de text uzuale în caietele de sarcini din România. "
                "O cerință absentă din această listă poate fi totuși prezentă în document sub o formulare "
                "neacoperită de tipare — verificați manual secțiunea de capacitate tehnică și economică."
            ),
        }

    @staticmethod
    def analyze_specification_text(text: str, project_title: str) -> Dict[str, Any]:
        from text_utils import matching_terms

        qualification_criteria = CaietDeSarciniAnalyzer.extract_qualification_criteria(text)

        flagged_risks = []
        overall_risk_score = 1.0

        for item in RESTRICTIVE_PATTERNS:
            hits = matching_terms(text, item["variants"])
            if hits:
                flagged_risks.append({
                    "pattern": item["keyword"],
                    # Quoting the exact wording that fired lets the user
                    # verify the finding against the document instead of
                    # trusting an unexplained flag.
                    "matched_terms": hits,
                    "severity": item["risk"],
                    "tactical_advisory": item["warning"],
                    # The provision this clause offends, quoted from the
                    # consolidated text rather than paraphrased. A finding
                    # that reproduces the statutory sentence is one the
                    # bidder can put straight into a clarification request;
                    # a bare severity label is not. Empty when the
                    # knowledge base has not been built.
                    "legal_basis": legal_kb.topic(item["legal_topic"])["articles"],
                })
                if item["risk"] == "Critic":
                    overall_risk_score += 3.5
                elif item["risk"] == "Ridicat":
                    overall_risk_score += 2.0
                else:
                    overall_risk_score += 1.0

        risk_level = "Scazut (Specificatii Deschise)"
        if overall_risk_score >= 7.0:
            risk_level = "Critic (Risc major de dedicatie / Clauze restrictive)"
        elif overall_risk_score >= 4.0:
            risk_level = "Moderat (Necesita solicitare de clarificari)"

        return {
            "project_title": project_title,
            "bias_risk_level": risk_level,
            "bias_score": min(10.0, round(overall_risk_score, 1)),
            "extracted_character_count": len(text),
            "qualification_criteria": qualification_criteria,
            "detected_red_flags": flagged_risks if flagged_risks else [
                {"pattern": "Niciunul", "severity": "OK",
                 "tactical_advisory": "Nu au fost identificate tipare restrictive dintre cele verificate."}
            ],
            "recommended_action": (
                "Transmiteți o solicitare oficială de clarificări în baza art. 160-161 din Legea nr. 98/2016."
                if flagged_risks else
                "Nu au fost detectate clauze restrictive dintre tiparele verificate. Continuați cu pregătirea dosarului tehnic."
            ),
            # An empty result means "none of the patterns we test for were
            # found", not "the specification is clean". Stating that keeps
            # the user from reading a keyword scan as a legal review.
            "coverage_note": (
                f"Analiză automată pe {len(RESTRICTIVE_PATTERNS)} tipare uzuale de clauze restrictive. "
                "Nu substituie verificarea juridică a documentației; absența unui semnal nu garantează "
                "conformitatea caietului de sarcini."
            ),
        }
