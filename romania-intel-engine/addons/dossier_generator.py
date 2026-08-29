import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger("DossierGenerator")

# Domain-specific technical content. The previous template emitted the same
# four sections for every procedure regardless of domain, so a medical
# imaging bid and a motorway bid received byte-identical text — including
# "utilaje grele" for a software contract.
DOMAIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "infrastructura": {
        "label": "lucrări de construcții și infrastructură",
        "key_personnel": [
            "Manager de Proiect (certificare PMP/PRINCE2)",
            "Responsabil Tehnic cu Execuția (RTE) atestat MLPDA pe domeniul aferent",
            "Responsabil cu Controlul Calității (CQ) atestat",
            "Coordonator SSM (Securitate și Sănătate în Muncă)",
        ],
        "standards": [
            "SR EN ISO 9001:2015 — management al calității",
            "SR EN ISO 14001:2015 — management de mediu",
            "SR ISO 45001:2018 — sănătate și securitate ocupațională",
            "Legea nr. 10/1995 privind calitatea în construcții, republicată",
            "HG nr. 766/1997 — regulamente privind calitatea în construcții",
        ],
        "technical_focus": [
            "Organizarea de șantier, căi de acces provizorii și managementul traficului pe durata execuției",
            "Planul de mobilizare a utilajelor grele și a stațiilor de producție (betoane/mixturi asfaltice)",
            "Programul de control al calității pe faze determinante (PCCVI), cu puncte de staționare obligatorii",
            "Managementul deșeurilor din construcții și demolări conform Legii nr. 211/2011",
        ],
        "warranty": "Perioada de garanție a lucrărilor: minimum 36 de luni de la recepția la terminarea lucrărilor, conform HG nr. 273/1994.",
    },
    "sanatate": {
        "label": "furnizare de echipamente și servicii medicale",
        "key_personnel": [
            "Manager de Proiect cu experiență în implementări medicale",
            "Inginer service autorizat de producător pentru echipamentele ofertate",
            "Specialist aplicații clinice (training utilizatori)",
            "Responsabil reglementare dispozitive medicale",
        ],
        "standards": [
            "Regulamentul (UE) 2017/745 privind dispozitivele medicale (MDR)",
            "SR EN ISO 13485 — sisteme de management al calității pentru dispozitive medicale",
            "Marcaj CE și declarație de conformitate UE pentru fiecare echipament",
            "Legea nr. 95/2006 privind reforma în domeniul sănătății, republicată",
            "Aviz de funcționare emis de ANMDMR pentru activitatea de distribuție/service",
        ],
        "technical_focus": [
            "Matricea de conformitate punct-cu-punct cu specificațiile tehnice minime din caietul de sarcini",
            "Planul de instalare, punere în funcțiune și testare de acceptanță (FAT/SAT)",
            "Interoperabilitate DICOM 3.0 / HL7 cu sistemele RIS-PACS existente ale unității sanitare",
            "Planul de instruire a personalului medical și tehnic, cu certificare de participare",
        ],
        "warranty": "Garanție minimum 36 de luni, cu timp de intervenție sub 4 ore și disponibilitate anuală garantată de minimum 95%.",
    },
    "energie": {
        "label": "soluții energetice și eficiență energetică",
        "key_personnel": [
            "Manager de Proiect",
            "Inginer electroenergetician autorizat ANRE (gradul corespunzător puterii instalate)",
            "Auditor energetic atestat MDLPA",
            "Responsabil punere în funcțiune și probe",
        ],
        "standards": [
            "Norme tehnice ANRE privind racordarea la rețelele de interes public",
            "SR EN 62446 — sisteme fotovoltaice: cerințe de testare și documentare",
            "SR EN ISO 50001 — sisteme de management al energiei",
            "Legea nr. 121/2014 privind eficiența energetică",
        ],
        "technical_focus": [
            "Calculul producției estimate de energie și al indicatorilor de performanță (PR, randament specific)",
            "Soluția de racordare, protecții și conformitatea cu avizul tehnic de racordare (ATR)",
            "Sistemul de monitorizare SCADA și mentenanța predictivă",
            "Analiza cost-beneficiu și termenul de amortizare a investiției",
        ],
        "warranty": "Garanție de produs și de performanță conform standardului producătorului, cu monitorizare a degradării anuale.",
    },
    "aparare": {
        "label": "echipamente și servicii cu destinație de apărare/securitate",
        "key_personnel": [
            "Manager de Proiect cu autorizație de acces la informații clasificate",
            "Responsabil de securitate (structura de securitate proprie)",
            "Inginer de sistem",
        ],
        "standards": [
            "Standarde NATO STANAG aplicabile categoriei de produs",
            "Legea nr. 182/2002 privind protecția informațiilor clasificate",
            "Autorizație/aviz de securitate industrială emis de ORNISS/DSN",
            "OUG nr. 114/2011 privind achizițiile în domeniile apărării și securității",
        ],
        "technical_focus": [
            "Conformitatea cu cerințele de securitate industrială și manipularea informațiilor clasificate",
            "Trasabilitatea lanțului de aprovizionare și certificarea originii componentelor",
            "Testele de mediu și rezistență conform specificațiilor militare aplicabile",
        ],
        "warranty": "Garanție și suport logistic integrat pe durata ciclului de viață, conform cerințelor din caietul de sarcini.",
    },
    "digitalizare": {
        "label": "servicii IT și transformare digitală",
        "key_personnel": [
            "Manager de Proiect (PMP/PRINCE2)",
            "Arhitect de soluție",
            "Responsabil securitate cibernetică",
            "Responsabil protecția datelor (DPO) sau expert GDPR",
        ],
        "standards": [
            "SR EN ISO/IEC 27001 — managementul securității informației",
            "Regulamentul (UE) 2016/679 (GDPR) și Legea nr. 190/2018",
            "Legea nr. 362/2018 privind securitatea rețelelor și sistemelor informatice (NIS)",
            "Cerințele de interoperabilitate din Legea nr. 242/2022 (schimbul de date între instituții)",
        ],
        "technical_focus": [
            "Arhitectura soluției, componentele și diagrama de integrare cu sistemele existente",
            "Planul de migrare a datelor și strategia de rollback",
            "Măsurile tehnice și organizatorice de protecție a datelor cu caracter personal",
            "Nivelurile de serviciu (SLA), disponibilitate și proceduri de escaladare",
        ],
        "warranty": "Garanție și mentenanță post-implementare minimum 36 de luni, cu SLA de disponibilitate de minimum 99,5%.",
    },
}

DEFAULT_PROFILE_KEY = "digitalizare"


class TechnicalDossierGenerator:
    @staticmethod
    def generate_draft(
        project_title: str,
        authority_name: str,
        county: str,
        category: str,
        company_name: str,
        cui: str,
        estimated_value_ron: Optional[float] = None,
        cpv_code: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile = DOMAIN_PROFILES.get((category or "").strip().lower(), DOMAIN_PROFILES[DEFAULT_PROFILE_KEY])
        today = date.today().strftime("%d.%m.%Y")

        # Procedure thresholds — Legea 98/2016 Art. 7 (values in RON, as
        # updated by the periodic ANAP threshold orders). Which procedure
        # applies changes what the bidder must actually file, so the draft
        # states it instead of assuming an open tender.
        procedure_note = TechnicalDossierGenerator._procedure_note(estimated_value_ron)

        header_lines = [
            "PROPUNERE TEHNICĂ — DOSAR DE CALIFICARE",
            f"Procedura: {project_title}",
            f"Autoritate contractantă: {authority_name}" + (f" ({county})" if county else ""),
            f"Ofertant: {company_name} (CUI: {cui})",
            f"Data întocmirii: {today}",
        ]
        if source_id:
            header_lines.append(f"Referință semnal: {source_id}")
        if cpv_code:
            header_lines.append(f"Cod CPV: {cpv_code}")
        if estimated_value_ron:
            header_lines.append(f"Valoare estimată publicată: {estimated_value_ron:,.2f} RON")
        header_lines.append("Temei legal: Legea nr. 98/2016 privind achizițiile publice; HG nr. 395/2016 (norme de aplicare)")

        sections: List[str] = []

        sections.append(
            "SECȚIUNEA 1: OBIECTUL OFERTEI ȘI ÎNCADRAREA PROCEDURALĂ\n"
            f"1.1 Prezenta propunere tehnică vizează {profile['label']}, în cadrul procedurii "
            f"„{project_title}” organizate de {authority_name}.\n"
            f"1.2 {procedure_note}\n"
            "1.3 Ofertantul declară că a analizat integral documentația de atribuire și că oferta respectă "
            "cerințele minime obligatorii din caietul de sarcini."
        )

        focus_lines = "\n".join(f"2.{i} {item}" for i, item in enumerate(profile["technical_focus"], start=1))
        sections.append("SECȚIUNEA 2: METODOLOGIE DE EXECUȚIE ȘI ABORDARE TEHNICĂ\n" + focus_lines)

        personnel_lines = "\n".join(f"3.{i} {item}" for i, item in enumerate(profile["key_personnel"], start=1))
        sections.append(
            "SECȚIUNEA 3: RESURSE UMANE ȘI PERSONAL-CHEIE\n" + personnel_lines +
            "\n3.x Pentru fiecare expert se anexează CV în format european, diplomele/atestatele relevante "
            "și angajamentul de disponibilitate pe durata contractului."
        )

        standards_lines = "\n".join(f"4.{i} {item}" for i, item in enumerate(profile["standards"], start=1))
        sections.append(
            "SECȚIUNEA 4: CONFORMITATE NORMATIVĂ, CALITATE ȘI MEDIU\n" + standards_lines
        )

        sections.append(
            "SECȚIUNEA 5: MATRICEA DE CONFORMITATE\n"
            "5.1 Se anexează matricea de conformitate punct-cu-punct cu specificațiile tehnice solicitate, "
            "cu trimitere la pagina din fișa tehnică a producătorului pentru fiecare cerință.\n"
            "5.2 Orice echivalență propusă este însoțită de documente justificative, conform "
            "art. 156 din Legea nr. 98/2016 (propuneri echivalente).\n"
            f"5.3 {profile['warranty']}"
        )

        sections.append(
            "SECȚIUNEA 6: DOCUMENTE DE CALIFICARE ANEXATE\n"
            "6.1 DUAE completat (Documentul Unic de Achiziții European), conform art. 193 din Legea nr. 98/2016.\n"
            "6.2 Declarații privind neîncadrarea în motivele de excludere prevăzute la art. 164, 165 și 167 "
            "din Legea nr. 98/2016.\n"
            "6.3 Certificate de atestare fiscală (buget de stat și buget local), în termen de valabilitate.\n"
            "6.4 Certificat constatator ONRC din care să reiasă obiectul de activitate corespunzător.\n"
            "6.5 Dovada constituirii garanției de participare, dacă este solicitată prin fișa de date."
        )

        disclaimer = (
            "NOTĂ: Document generat automat ca schiță de lucru de motorul RO-INTEL. Conținutul trebuie "
            "verificat și completat de un specialist în achiziții publice prin raportare la documentația "
            "de atribuire specifică procedurii. Referințele legale sunt orientative și trebuie confirmate "
            "în forma în vigoare la data depunerii ofertei."
        )

        doc = "\n".join(header_lines) + "\n\n" + ("\n" + "-" * 80 + "\n").join(sections) + "\n\n" + "-" * 80 + "\n" + disclaimer

        return {
            "project_title": project_title,
            "authority_name": authority_name,
            "company_name": company_name,
            "category_profile": category or DEFAULT_PROFILE_KEY,
            "procedure_note": procedure_note,
            "dossier_text": doc.strip(),
            "sections_count": len(sections),
            "status": "ready",
            "disclaimer": disclaimer,
        }

    @staticmethod
    def _procedure_note(estimated_value_ron: Optional[float]) -> str:
        if not estimated_value_ron:
            return (
                "Valoarea estimată nu este publicată de autoritate; tipul procedurii și cerințele de "
                "calificare se confirmă din fișa de date a achiziției."
            )
        # Thresholds per Legea 98/2016 art. 7 alin. (1) and (5), as revised
        # by the ANAP threshold orders; stated as guidance because the exact
        # figures are periodically updated by order.
        if estimated_value_ron < 900_000:
            return (
                f"La o valoare estimată de {estimated_value_ron:,.0f} RON, achiziția se poate încadra ca achiziție "
                "directă (art. 7 alin. (5) din Legea nr. 98/2016) — se confirmă pragul în vigoare la data publicării."
            )
        if estimated_value_ron < 27_000_000:
            return (
                f"La o valoare estimată de {estimated_value_ron:,.0f} RON, procedura aplicabilă este, de regulă, "
                "procedura simplificată (art. 7 alin. (2) din Legea nr. 98/2016)."
            )
        return (
            f"La o valoare estimată de {estimated_value_ron:,.0f} RON, valoarea depășește pragurile europene, "
            "fiind aplicabilă licitația deschisă cu publicare în JOUE (art. 7 alin. (1) din Legea nr. 98/2016)."
        )
