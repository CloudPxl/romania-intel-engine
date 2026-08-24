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
Catre: {authority_name}
In atentia: Serviciului Achizitii Publice / Directiei Tehnice

Ref: Procedura de consultare de piata / semnal pre-SEAP {source_id}
Obiect: "{project_title}"

Data: {today_str}

Stimate domnule / Stimata doamna Director,

Subscrisa, {company_name}, inregistrata la Registrul Comertului, CUI {cui_fiscal}, in calitate de operator economic de profil interesat de participarea la procedura mentionata in referinta,

Avand in vedere principiile nediscriminarii, tratamentului egal si proportionalitatii consacrate de Art. 2 alin. (2) din Legea nr. 98/2016 privind achizitiile publice, precum si prevederile Legii nr. 544/2001 privind liberul acces la informatiile de interes public,

Va inaintam prezenta SOLICITARE DE CLARIFICARI / PUNCT DE VEDERE TEHNIC cu privire la cerintele preliminare ale procedurii:

{clarification_points}

Va rugam sa aveti in vedere ajustarea cerintelor tehnice astfel incat sa asigurati un mediu concurential real si accesul liber al solutiilor tehnice performante.

Cu stima,
Departamentul Bidding & Strategie Achizitii
{company_name}
"""
        return {
            "document_type": "Adresa Oficiala Solicitare Clarificari Legea 98/2016",
            "recipient": authority_name,
            "reference_id": source_id,
            "generated_letter": letter_text.strip()
        }
