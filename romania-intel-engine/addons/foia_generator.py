import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger("FOIAGenerator")

class LegalClarificationGenerator:
    @staticmethod
    def generate_clarification_letter(
        authority_name: str,
        project_title: str,
        source_id: str,
        company_name: str,
        cui_fiscal: str,
        clarification_points: str
    ) -> Dict[str, Any]:
        today_str = datetime.now().strftime("%d.%m.%Y")

        letter_text = f"""
Către: {authority_name}
În atenția: Serviciului Achiziții Publice / Direcției Tehnice

Ref: Procedura de consultare de piață / semnal pre-SEAP {source_id}
Obiect: "{project_title}"

Data: {today_str}

Stimate domnule / Stimată doamnă Director,

Subscrisa, {company_name}, înregistrată la Registrul Comerțului, CUI {cui_fiscal}, în calitate de operator economic de profil interesat de participarea la procedura menționată în referință,

Având în vedere principiile nediscriminării, tratamentului egal și proporționalității consacrate de Art. 2 alin. (2) din Legea nr. 98/2016 privind achizițiile publice, precum și prevederile Legii nr. 544/2001 privind liberul acces la informațiile de interes public,

Vă înaintăm prezenta SOLICITARE DE CLARIFICĂRI / PUNCT DE VEDERE TEHNIC cu privire la cerințele preliminare ale procedurii:

{clarification_points}

Vă rugăm să aveți în vedere ajustarea cerințelor tehnice astfel încât să asigurați un mediu concurențial real și accesul liber al soluțiilor tehnice inovatoare și eficiente din punct de vedere energetic.

În speranța unui dialog tehnico-instituțional constructiv, vă stăm la dispoziție pentru orice demonstrații tehnice preliminare.

Cu stimă,
Departamentul Bidding & Afaceri Publice
{company_name}
"""
        return {
            "document_type": "Adresă Oficială Solicitare Clarificări Legea 98/2016",
            "recipient": authority_name,
            "reference_id": source_id,
            "generated_letter": letter_text.strip()
        }
