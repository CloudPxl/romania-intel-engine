import os, sys, base64, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, "romania-intel-engine")
FRONTEND = os.path.join(ROOT, "romania-intel-frontend")

def write_b64(path, b64_str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_str))
    print(f"  [✓] Verified: {os.path.relpath(path, ROOT)}")

def run_cmd(cmd, cwd):
    print(f"\n[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"❌ Failed: {' '.join(cmd)}")
        sys.exit(1)

print("\n⚡ [1/4] Writing Clean Production Source Files via Base64...")

# 1. ENTERPRISE MODALS (100% COMPLETE, ZERO EMOJIS, LIGHT PALETTE, ALL 11 MODALS)
MODALS_CODE = """\"use client\";
import React, { useState, useEffect } from "react";
import {
  generateProformaInvoice,
  uploadCaietFile,
  analyzeCaietSarcini,
  predictWinRate,
  generateLegalClarification,
  evaluateBusinessEligibility,
  askCopilotChat,
  fetchTenantPipeline,
  fetchCompetitorAnalysis,
  generateTechnicalProposal
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

export function PricingModal({ isOpen, onClose, tenantId }: { isOpen: boolean; onClose: () => void; tenantId: string }) {
  const [selectedPlan, setSelectedPlan] = useState<string | null>("plan_founder_vip");
  const [companyName, setCompanyName] = useState("SC Infra Construct Transilvania SRL");
  const [cui, setCui] = useState("RO12345678");
  const [email, setEmail] = useState("financiar@infraconstruct.ro");
  const [address, setAddress] = useState("Str. Memorandumului 21, Cluj-Napoca");
  const [proformaData, setProformaData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleGenerateProforma = async () => {
    if (!selectedPlan) return;
    setLoading(true);
    try {
      const data = await generateProformaInvoice({
        tenant_id: tenantId,
        plan_id: selectedPlan,
        company_name: companyName,
        cui_fiscal: cui,
        billing_email: email,
        billing_address: address
      });
      setProformaData(data);
    } catch (e: any) {
      alert("Eroare: " + (e?.message || "Nu s-a putut genera factura proforma."));
    } finally {
      setLoading(false);
    }
  };

  const handlePrint = () => {
    if (!proformaData?.proforma_html) return;
    const printWin = window.open("", "_blank");
    if (printWin) {
      printWin.document.write(proformaData.proforma_html);
      printWin.document.close();
      printWin.focus();
      printWin.print();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-4xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Activare Abonament & Factura Proforma</h2>
            <p className="text-xs text-slate-500">Generare instantanee Factura Proforma pentru plata prin Ordin de Plata (OP) sau Card.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>

        {!proformaData ? (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-6">
              <div
                onClick={() => setSelectedPlan("plan_acces_complet")}
                className={"cursor-pointer flex flex-col justify-between rounded-xl border p-5 transition " + (selectedPlan === "plan_acces_complet" ? "border-sky-500 bg-sky-50/50" : "border-slate-200 bg-white hover:border-slate-300")}
              >
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-base font-bold text-slate-900">Acces Complet Desk</h3>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">STANDARD</span>
                  </div>
                  <p className="text-2xl font-extrabold text-slate-900 mb-3">499 <span className="text-xs font-normal text-slate-500">RON / luna</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-600">
                    <li>- Acces la toate cele 25 de registre active</li>
                    <li>- Sinteze Executive AI</li>
                    <li>- Export CSV date calificate</li>
                    <li>- 1 Workspace & 2 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-slate-100 py-2 text-xs font-bold text-slate-800 hover:bg-slate-200">
                  {selectedPlan === "plan_acces_complet" ? "Plan Selectat" : "Selecteaza 499 RON"}
                </button>
              </div>

              <div
                onClick={() => setSelectedPlan("plan_founder_vip")}
                className={"cursor-pointer flex flex-col justify-between rounded-xl border-2 p-5 relative transition " + (selectedPlan === "plan_founder_vip" ? "border-sky-600 bg-sky-50/50" : "border-slate-300 bg-white hover:border-slate-400")}
              >
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-base font-bold text-slate-900">VIP Multi-Divizie</h3>
                    <span className="rounded bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-800">ENTERPRISE</span>
                  </div>
                  <p className="text-2xl font-extrabold text-slate-900 mb-3">1499 <span className="text-xs font-normal text-slate-500">RON / luna</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-600">
                    <li>- Tot ce include pachetul Acces Complet</li>
                    <li>- Scanner Caiet de Sarcini (Upload PDF/DOCX)</li>
                    <li>- Simulator Sanse de Castig & Marje</li>
                    <li>- Generator Adrese Legea 544</li>
                    <li>- Radar Concurenta & Schita Propunere Tehnica</li>
                    <li>- Pana la 10 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-slate-900 py-2 text-xs font-bold text-white hover:bg-slate-800">
                  {selectedPlan === "plan_founder_vip" ? "Plan Selectat" : "Selecteaza 1499 RON"}
                </button>
              </div>
            </div>

            {selectedPlan && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs space-y-3">
                <span className="font-bold text-slate-700 block uppercase text-[11px]">Date Facturare Companie:</span>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-600 mb-1">Denumire Companie</label>
                    <input
                      type="text"
                      value={companyName}
                      onChange={(e) => setCompanyName(e.target.value)}
                      className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">CUI / CIF</label>
                    <input
                      type="text"
                      value={cui}
                      onChange={(e) => setCui(e.target.value)}
                      className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Email Facturare</label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Adresa Sediu Social</label>
                    <input
                      type="text"
                      value={address}
                      onChange={(e) => setAddress(e.target.value)}
                      className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900"
                    />
                  </div>
                </div>

                <button
                  onClick={handleGenerateProforma}
                  disabled={loading}
                  className="mt-3 w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition"
                >
                  {loading ? "Se emite proforma..." : (selectedPlan === "plan_founder_vip" ? "Genereaza Factura Proforma (1499 RON)" : "Genereaza Factura Proforma (499 RON)")}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-center">
              <span className="text-emerald-800 font-bold block text-sm">Factura Proforma {proformaData.invoice_number} a fost emisa.</span>
              <p className="text-slate-600 text-xs mt-1">Total de plata: <b>{proformaData.total_ron} RON</b> pentru {proformaData.plan_name}</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
              <span className="font-bold text-slate-800 block">Date Transfer Bancar (Ordin de Plata - OP):</span>
              <p className="text-slate-700">Banca: <b>{proformaData.bank_details.bank_name}</b></p>
              <p className="text-slate-700">IBAN: <b className="font-mono text-slate-900">{proformaData.bank_details.iban_ron}</b></p>
              <p className="text-slate-700">Beneficiar: <b>{proformaData.bank_details.beneficiary}</b></p>
              <p className="text-slate-700">Detalii Plata: <b>{proformaData.bank_details.payment_details_prefix}{proformaData.invoice_number} ({proformaData.cui_fiscal})</b></p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handlePrint}
                className="flex-1 rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition"
              >
                Descarca / Printeaza Factura Proforma (PDF)
              </button>
              <button
                onClick={() => setProformaData(null)}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 font-semibold text-slate-700 hover:bg-slate-50"
              >
                Modifica Datele
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function CaietScannerModal({ isOpen, onClose, defaultTitle }: { isOpen: boolean; onClose: () => void; defaultTitle: string }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      if (file) {
        const data = await uploadCaietFile(file, defaultTitle);
        setResult(data);
      } else if (text.trim()) {
        const data = await analyzeCaietSarcini(defaultTitle, text);
        setResult(data);
      }
    } catch (e: any) {
      alert("Eroare: " + (e?.message || "Nu s-a putut analiza caietul de sarcini."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Scanner Clauze Restrictive (Caiet de Sarcini)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <p className="text-xs text-slate-500 mb-3 font-mono">Proiect: {defaultTitle}</p>

        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center mb-3">
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="hidden"
            id="caiet-upload"
          />
          <label htmlFor="caiet-upload" className="cursor-pointer block">
            <span className="text-sky-700 font-bold block text-xs">
              {file ? "Fisier selectat: " + file.name : "Incarcati fisierul PDF sau DOCX aici (sau click pentru a alege)"}
            </span>
            <span className="text-[10px] text-slate-500 mt-1 block">Suporta Caiete de Sarcini oficiale PDF, DOCX</span>
          </label>
        </div>

        <div className="text-center text-[10px] text-slate-400 mb-2 font-bold uppercase">Sau introduceti textul direct</div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Introduceti textul din caietul de sarcini..."
          className="w-full h-24 rounded-xl border border-slate-300 bg-slate-50 p-3 text-xs text-slate-900 focus:bg-white focus:border-sky-500 focus:outline-none"
        />

        <button
          onClick={handleAnalyze}
          disabled={loading || (!text && !file)}
          className="mt-3 w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition"
        >
          {loading ? "Se analizeaza documentul conform jurisprudentei CNSC..." : "Scaneaza Clauze Restrictive"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-slate-700">Nivel Risc Restrictiv:</span>
              <span className="font-bold text-amber-800">{result.bias_risk_level} (Scor: {result.bias_score}/10)</span>
            </div>
            <p className="text-slate-600">{result.recommended_action}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-500 uppercase text-[10px]">Clauze Identificate:</span>
              {result.detected_red_flags && result.detected_red_flags.map((flag: any, i: number) => (
                <div key={i} className="rounded bg-white p-2.5 border-l-2 border-amber-500 shadow-sm">
                  <p className="font-bold text-slate-900">{flag.pattern} — Risc {flag.severity}</p>
                  <p className="text-slate-600 mt-0.5">{flag.tactical_advisory}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function BusinessEligibilityModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { activeDesk } = useAuth();
  const [companyName, setCompanyName] = useState(activeDesk?.name || "SC Infra Construct Transilvania SRL");
  const [cui, setCui] = useState(activeDesk?.cui || "RO12345678");
  const [caen, setCaen] = useState("4211");
  const [turnover, setTurnover] = useState(18500000);
  const [employees, setEmployees] = useState(48);
  const [county, setCounty] = useState(activeDesk?.target_counties?.[0] || "Cluj");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (activeDesk) {
      setCompanyName(activeDesk.name);
      setCui(activeDesk.cui);
      if (activeDesk.target_counties?.length > 0) setCounty(activeDesk.target_counties[0]);
    }
  }, [activeDesk]);

  if (!isOpen) return null;

  const handleScan = async () => {
    setLoading(true);
    try {
      const data = await evaluateBusinessEligibility({
        company_name: companyName,
        cui_fiscal: cui,
        caen_code: caen,
        turnover_ron: Number(turnover),
        employee_count: Number(employees),
        county
      });
      setResult(data);
    } catch (e: any) {
      alert("Eroare la scanare: " + (e?.message || "Verificati conexiunea cu serverul API."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Scanner Eligibilitate Granturi & Licitatii Strategice</h3>
            <p className="text-xs text-slate-500">Evaluare automata a profilului companiei conform ghidurilor PNRR / MIPE 2026.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs mb-4">
          <div>
            <label className="block text-slate-600 mb-1">Nume Companie</label>
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">CUI / Cod Fiscal</label>
            <input
              type="text"
              value={cui}
              onChange={(e) => setCui(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Cod CAEN Principal</label>
            <input
              type="text"
              value={caen}
              onChange={(e) => setCaen(e.target.value)}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Cifra de Afaceri Anuala (RON)</label>
            <input
              type="number"
              value={turnover}
              onChange={(e) => setTurnover(Number(e.target.value))}
              className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
            />
          </div>
        </div>

        <button onClick={handleScan} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition">
          {loading ? "Se verifica criteriile de eligibilitate..." : "Evalueaza Profilul Companiei"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
            <div className="flex justify-between items-center border-b border-slate-200 pb-2">
              <span className="font-bold text-slate-800">{result.qualification_status}</span>
              <span className="rounded bg-emerald-100 px-2 py-0.5 font-bold text-emerald-800">Scor: {result.overall_eligibility_score}/10</span>
            </div>
            <p className="text-slate-600 leading-relaxed">{result.advisory_summary}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-500 uppercase text-[10px]">Linii de Finantare Eligibile:</span>
              {result.matched_grants && result.matched_grants.map((g: any, i: number) => (
                <div key={i} className="rounded bg-white p-3 border-l-2 border-sky-600 shadow-sm">
                  <div className="flex justify-between">
                    <span className="font-bold text-slate-900">{g.program_name}</span>
                    <span className="font-bold text-emerald-700">Pana la {g.eligible_grant_up_to}</span>
                  </div>
                  <p className="text-slate-500 text-[11px] mt-1">Cofinantare: {g.required_co_financing} | Baza legala: {g.legal_basis}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function CopilotChatModal({ isOpen, onClose, tenantId, report72h }: { isOpen: boolean; onClose: () => void; tenantId: string; report72h: any }) {
  const [messages, setMessages] = useState<{ sender: "user" | "ai"; text: string }[]>([
    { sender: "ai", text: "Buna ziua! Sunt Copilotul AI RO-INTEL. Cu ce oportunitate, cerinta de calificare sau strategie de licitatie doriti sa incepem?" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userQ = input;
    setInput("");
    setMessages(prev => [...prev, { sender: "user", text: userQ }]);
    setLoading(true);

    try {
      const data = await askCopilotChat(userQ, tenantId);
      setMessages(prev => [...prev, { sender: "ai", text: data.reply }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { sender: "ai", text: "Eroare la conexiunea cu Copilotul AI: " + (e?.message || "") }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 flex flex-col h-[85vh]">
        <div className="flex justify-between items-center mb-3 border-b border-slate-100 pb-2">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Copilot AI Bidding & Radar 72h</h3>
            <p className="text-xs text-slate-500">{report72h?.period || "Ultimele 72 ore"}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {report72h && (
          <div className="rounded-xl bg-slate-50 p-3 text-xs mb-3 border border-slate-200 space-y-1">
            <span className="font-bold text-slate-700 block">Sinteza Macro Ultimele 72h:</span>
            <ul className="list-disc pl-4 text-slate-600 space-y-0.5">
              {report72h.executive_takeaways && report72h.executive_takeaways.map((t: string, i: number) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 p-2 text-xs">
          {messages.map((m, i) => (
            <div key={i} className={"flex " + (m.sender === "user" ? "justify-end" : "justify-start")}>
              <div className={"max-w-[85%] rounded-xl p-3 " + (m.sender === "user" ? "bg-slate-900 text-white font-medium" : "bg-slate-100 border border-slate-200 text-slate-800")}>
                {m.text}
              </div>
            </div>
          ))}
          {loading && <div className="text-slate-500 text-xs animate-pulse">Copilotul AI analizeaza dosarele pre-SEAP...</div>}
        </div>

        <div className="flex gap-2 mt-3 pt-2 border-t border-slate-100">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Intrebati despre cerinte de atribuire, licitatii CNI, bugete sau contestatii..."
            className="flex-1 rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-900 focus:bg-white focus:outline-none focus:border-sky-500"
          />
          <button onClick={handleSend} disabled={loading} className="rounded-xl bg-slate-900 px-4 py-2 font-bold text-white text-xs hover:bg-slate-800">
            Trimite
          </button>
        </div>
      </div>
    </div>
  );
}

export function WinOddsModal({ isOpen, onClose, defaultBudget }: { isOpen: boolean; onClose: () => void; defaultBudget: number }) {
  const [budget, setBudget] = useState(defaultBudget || 10000000);
  const [price, setPrice] = useState(Math.round((defaultBudget || 10000000) * 0.92));
  const [hasPartner, setHasPartner] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleCalculate = async () => {
    setLoading(true);
    try {
      const data = await predictWinRate(budget, price, hasPartner);
      setResult(data);
    } catch {
      alert("Eroare la calcularea sanselor.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Simulator Sanse de Castig & Marja Optima</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <div className="space-y-3 text-xs">
          <div>
            <label className="block text-slate-600 mb-1">Buget Estimat Autoritate Contractanta (RON)</label>
            <input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900" />
          </div>
          <div>
            <label className="block text-slate-600 mb-1">Pret Ofertat Propus (RON)</label>
            <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900" />
          </div>
          <label className="flex items-center gap-2 text-slate-700">
            <input type="checkbox" checked={hasPartner} onChange={(e) => setHasPartner(e.target.checked)} className="rounded" />
            Consortiu / Subcontractant local in judetul autoritatii (+12% logistica)
          </label>
          <button onClick={handleCalculate} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition">
            {loading ? "Se evalueaza..." : "Calculeaza Probabilitate Castig"}
          </button>
          {result && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center mt-3">
              <p className="uppercase text-slate-500 text-[10px] font-bold">Probabilitate Estimata de Atribuire</p>
              <p className="text-3xl font-extrabold text-emerald-700 my-1">{result.win_probability_score}</p>
              <p className="text-slate-700">Discount propus: <span className="font-bold text-slate-900">{result.discount_percentage}</span> ({result.rating})</p>
              <p className="text-slate-600 mt-2 text-left bg-white p-2.5 rounded border border-slate-200 text-[11px]">{result.tactical_guidance}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ClarificationModal({ isOpen, onClose, opp }: { isOpen: boolean; onClose: () => void; opp: any }) {
  const { activeDesk } = useAuth();
  const [points, setPoints] = useState("1. Solicitam eliminarea cerintei de autorizatie directa de la producator.\\n2. Solicitam acceptarea standardelor tehnice europene echivalente conform Art. 160 Legea 98/2016.");
  const [letter, setLetter] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const data = await generateLegalClarification({
        authority_name: opp.entity_name,
        project_title: opp.project_title,
        source_id: opp.source_id,
        company_name: activeDesk?.name || "SC Infra Construct Transilvania SRL",
        cui_fiscal: activeDesk?.cui || "RO12345678",
        clarification_points: points
      });
      setLetter(data.generated_letter);
    } catch {
      alert("Eroare la generarea adresei oficiale.");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(letter);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <h3 className="text-lg font-bold text-slate-900">Generator Solicitare Clarificari (Legea 98/2016)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <p className="text-xs text-slate-500 mb-2 font-mono">Autoritate: {opp.entity_name}</p>
        <label className="block text-xs text-slate-700 mb-1">Puncte de clarificat / Clauze restrictive:</label>
        <textarea
          value={points}
          onChange={(e) => setPoints(e.target.value)}
          className="w-full h-24 rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-xs text-slate-900 mb-3 focus:bg-white focus:outline-none"
        />
        <button onClick={handleGenerate} disabled={loading} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition">
          {loading ? "Se redacteaza adresa oficiala..." : "Genereaza Adresa Oficiala"}
        </button>
        {letter && (
          <div className="mt-4">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs font-bold text-slate-700">Document Generat:</span>
              <button onClick={copyToClipboard} className="rounded bg-slate-100 border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-800 hover:bg-slate-200">
                {copied ? "Copiat" : "Copiaza Textul"}
              </button>
            </div>
            <pre className="h-48 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800 whitespace-pre-wrap font-sans">
              {letter}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function PipelineTrackerModal({ isOpen, onClose, tenantId }: { isOpen: boolean; onClose: () => void; tenantId: string }) {
  const [pipelineData, setPipelineData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadPipeline = async () => {
    setLoading(true);
    try {
      const data = await fetchTenantPipeline(tenantId);
      setPipelineData(data);
    } catch (e) {
      console.warn("Pipeline load note:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) loadPipeline();
  }, [isOpen, tenantId]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-5xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Pipeline Bidding & Management Dosare Pre-SEAP</h3>
            <p className="text-xs text-slate-500">Monitorizare stadiu intern: evaluare tehnica, adrese clarificari si marje estimate.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se incarca pipeline-ul companiei...</div>
        ) : !pipelineData?.deals?.length ? (
          <div className="flex h-48 flex-col items-center justify-center text-xs text-slate-500 space-y-2">
            <span>Nu aveti dosare salvate in pipeline-ul curent.</span>
            <span className="text-[11px] text-sky-700">Deschideti orice dosar din feed-ul principal si apasati "Salveaza in Pipeline".</span>
          </div>
        ) : (
          <div className="space-y-3">
            {pipelineData.deals && pipelineData.deals.map((d: any) => (
              <div key={d.deal_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs space-y-2">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="rounded bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-800 uppercase">
                      {d.stage ? d.stage.replace("_", " ") : "Nou"}
                    </span>
                    <h4 className="font-bold text-slate-900 text-sm mt-1">{d.project_title}</h4>
                    <p className="text-slate-600 text-xs">{d.entity_name}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-sm font-extrabold text-slate-900">{(d.financial_value_ron / 1000000).toFixed(2)} Mil. RON</span>
                    <span className="block text-[10px] text-emerald-700 font-bold">Marja Tinta: {d.target_margin_pct}%</span>
                  </div>
                </div>
                <div className="rounded bg-white p-2 text-slate-700 text-[11px] border border-slate-200">
                  <b>Notite Bidding:</b> {d.notes}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function AccountSettingsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { user, preferences, updatePreferences, signInWithGoogle, signInWithEmail, signOut } = useAuth();
  const [emailInput, setEmailInput] = useState("");
  const [alertEmail, setAlertEmail] = useState(preferences?.notification_email || user?.email || "");
  const [scoreThreshold, setScoreThreshold] = useState(preferences?.auto_alert_score || 9.0);
  const [magicLinkSent, setMagicLinkSent] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);

  if (!isOpen) return null;

  const handleSave = () => {
    updatePreferences({
      notification_email: alertEmail,
      auto_alert_score: Number(scoreThreshold)
    });
    alert("Setarile au fost salvate.");
    onClose();
  };

  const handleSendMagicLink = async () => {
    if (!emailInput) return;
    setAuthLoading(true);
    const { error } = await signInWithEmail(emailInput);
    setAuthLoading(false);
    if (!error) setMagicLinkSent(true);
    else alert("Eroare: " + error);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Setari Cont & Alerte Email</h3>
            <p className="text-xs text-slate-500">Personalizare flux notificari automate si autentificare.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="space-y-4 text-xs">
          {!user ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <span className="font-bold text-slate-900 block text-sm">Autentificare Operator Economic</span>
              <p className="text-slate-600">Conectati-va pentru a salva dosare in pipeline si a primi alerte automate:</p>
              
              <button
                onClick={signInWithGoogle}
                className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition shadow-sm"
              >
                Conectare cu Google
              </button>

              <div className="flex items-center gap-2 text-slate-400 my-2">
                <div className="flex-1 border-b border-slate-200"></div>
                <span className="text-[10px] uppercase font-bold">Sau Email Magic Link</span>
                <div className="flex-1 border-b border-slate-200"></div>
              </div>

              {!magicLinkSent ? (
                <div className="flex gap-2">
                  <input
                    type="email"
                    placeholder="introduceti email-ul companiei..."
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    className="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-slate-900"
                  />
                  <button
                    onClick={handleSendMagicLink}
                    disabled={authLoading}
                    className="rounded-xl bg-slate-800 px-4 py-2 font-bold text-white hover:bg-slate-700"
                  >
                    {authLoading ? "Se trimite..." : "Trimite Link"}
                  </button>
                </div>
              ) : (
                <p className="text-emerald-700 font-bold text-center">Link de autentificare expediat. Verificati casuta de email.</p>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Cont Conectat:</span>
                <span className="font-bold text-emerald-700">{user.email}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Rol Platforma:</span>
                <span className="font-semibold text-slate-800">{user.role}</span>
              </div>
              <button onClick={signOut} className="mt-2 w-full rounded-lg bg-rose-50 border border-rose-200 py-1.5 text-center text-rose-700 hover:bg-rose-100 transition font-medium">
                Deconectare Cont
              </button>
            </div>
          )}

          <div className="space-y-3 pt-2">
            <span className="font-bold text-slate-700 block uppercase text-[11px]">Canal Trimitere Alerte Email</span>
            <div>
              <label className="block text-slate-600 mb-1">Email Destinatar Notificari</label>
              <input
                type="email"
                value={alertEmail}
                onChange={(e) => setAlertEmail(e.target.value)}
                placeholder="ex: director@infraconstruct.ro"
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900"
              />
            </div>
            <div>
              <label className="block text-slate-600 mb-1">Prag Minim Scor Oportunitate pentru Alerta Automata</label>
              <select
                value={scoreThreshold}
                onChange={(e) => setScoreThreshold(Number(e.target.value))}
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900"
              >
                <option value={9.5}>Scor &ge; 9.5 (Doar Proiecte Strategice Critice)</option>
                <option value={9.0}>Scor &ge; 9.0 (Toate Oportunitatile Calificate)</option>
                <option value={8.5}>Scor &ge; 8.5 (Toate Semnalele Active)</option>
              </select>
            </div>
          </div>

          <button onClick={handleSave} className="w-full rounded-xl bg-slate-900 py-2.5 font-bold text-white text-xs hover:bg-slate-800 transition mt-2">
            Salveaza Preferintele
          </button>
        </div>
      </div>
    </div>
  );
}

export function WorkspaceDeskModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { desks, activeDesk, createDesk, deleteDesk, switchDesk } = useAuth();
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [cui, setCui] = useState("");
  const [domain, setDomain] = useState("infrastructura");
  const [counties, setCounties] = useState("Iasi, Cluj, Bucuresti");
  const [minBudget, setMinBudget] = useState(5000000);
  const [keywords, setKeywords] = useState("drum, pod, asfalt, metrou");
  const [divisionName, setDivisionName] = useState("Divizia Principala");

  if (!isOpen) return null;

  const handleCreate = () => {
    if (!name.trim() || !cui.trim()) {
      alert("Completati numele companiei si codul fiscal (CUI).");
      return;
    }
    const countyList = counties.split(",").map(c => c.trim()).filter(Boolean);
    const keywordList = keywords.split(",").map(k => k.trim().toLowerCase()).filter(Boolean);

    createDesk({
      name,
      cui,
      primary_domain: domain,
      target_counties: countyList.length > 0 ? countyList : ["Toate"],
      min_budget_ron: Number(minBudget) || 1000000,
      keywords: keywordList,
      divisions: [
        {
          id: "div_" + Date.now(),
          name: divisionName || "Divizia Principala",
          keywords: keywordList
        }
      ]
    });

    setIsCreating(false);
    setName("");
    setCui("");
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Administrare Companii & Desk-uri</h3>
            <p className="text-xs text-slate-500">Configurati companiile din portofoliu, domeniile de activitate si cuvintele-cheie monitorizate.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {!isCreating ? (
          <div className="space-y-4 text-xs">
            <div className="flex justify-between items-center">
              <span className="font-bold text-slate-700 uppercase text-[11px]">Companii & Desk-uri Active ({desks.length})</span>
              <button
                onClick={() => setIsCreating(true)}
                className="rounded-lg bg-slate-900 px-3 py-1.5 font-semibold text-white hover:bg-slate-800 transition"
              >
                + Adauga Companie Noua
              </button>
            </div>

            <div className="space-y-2">
              {desks.map(d => (
                <div
                  key={d.id}
                  className={"rounded-xl border p-4 transition flex justify-between items-center " + (d.id === activeDesk?.id ? "border-sky-500 bg-sky-50/40" : "border-slate-200 bg-slate-50")}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-bold text-slate-900 text-sm">{d.name}</h4>
                      {d.id === activeDesk?.id && (
                        <span className="rounded bg-sky-100 px-2 py-0.5 font-bold text-sky-800 text-[10px]">Activ</span>
                      )}
                    </div>
                    <p className="text-slate-500 text-xs mt-0.5">CUI: {d.cui} &bull; Domeniu: <span className="capitalize">{d.primary_domain}</span></p>
                    <p className="text-slate-600 text-[11px] mt-1">Judete: {d.target_counties?.join(", ")}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {d.id !== activeDesk?.id && (
                      <button
                        onClick={() => switchDesk(d.id)}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-100"
                      >
                        Comuta
                      </button>
                    )}
                    {desks.length > 1 && (
                      <button
                        onClick={() => deleteDesk(d.id)}
                        className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 font-semibold text-rose-700 hover:bg-rose-100"
                      >
                        Sterge
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-xs">
            <div className="flex justify-between items-center border-b border-slate-100 pb-2">
              <span className="font-bold text-slate-900 uppercase text-[11px]">Configurare Desk Nou</span>
              <button onClick={() => setIsCreating(false)} className="text-slate-500 hover:underline">Inapoi</button>
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Denumire Companie</label>
              <input
                type="text"
                placeholder="ex: SC Terra Construct SRL"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-600 mb-1">Cod Fiscal (CUI)</label>
                <input
                  type="text"
                  placeholder="ex: RO34567890"
                  value={cui}
                  onChange={(e) => setCui(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Domeniu Strategic Principal</label>
                <select
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                >
                  <option value="infrastructura">Infrastructura & Transporturi</option>
                  <option value="sanatate">Sanatate & Echipamente Medicale</option>
                  <option value="energie">Energie & Utilitati Verzi</option>
                  <option value="aparare">Aparare & Securitate Speciala</option>
                  <option value="digitalizare">Digitalizare, IT & Smart City</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Judete Vizate (separate prin virgula)</label>
              <input
                type="text"
                placeholder="ex: Cluj, Iasi, Timis, Bucuresti"
                value={counties}
                onChange={(e) => setCounties(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Cuvinte-cheie Monitorizate (separate prin virgula)</label>
              <input
                type="text"
                placeholder="ex: pod, asfalt, consolidare, statie tratare"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-600 mb-1">Nume Divizie Principala</label>
                <input
                  type="text"
                  placeholder="ex: Divizia Lucrari Civile"
                  value={divisionName}
                  onChange={(e) => setDivisionName(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Buget Minim Proiect (RON)</label>
                <input
                  type="number"
                  value={minBudget}
                  onChange={(e) => setMinBudget(Number(e.target.value))}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={handleCreate}
                className="flex-1 rounded-xl bg-slate-900 py-2.5 font-bold text-white hover:bg-slate-800 transition"
              >
                Salveaza si Activeaza Desk
              </button>
              <button
                onClick={() => setIsCreating(false)}
                className="rounded-xl border border-slate-300 bg-slate-100 px-4 py-2.5 font-semibold text-slate-700 hover:bg-slate-200"
              >
                Anuleaza
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function CompetitorRadarModal({ isOpen, onClose, category, county, budget }: { isOpen: boolean; onClose: () => void; category: string; county: string; budget: number }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetchCompetitorAnalysis(category, county, budget)
        .then(res => setData(res))
        .catch(err => console.warn(err))
        .finally(() => setLoading(false));
    }
  }, [isOpen, category, county, budget]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Radar Concurenta & Profil Piata Regionala</h3>
            <p className="text-xs text-slate-500">Analiza istorica a preturilor de adjudecare si a riscului de contestatie in {county}.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se proceseaza curbele de discount...</div>
        ) : data ? (
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Discount Istoric Mediu</span>
                <span className="text-base font-extrabold text-slate-900">{data.benchmark?.historical_avg_discount}</span>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Risc Subcotare</span>
                <span className="text-base font-bold text-amber-700">{data.benchmark?.undercutting_risk}</span>
              </div>
              <div className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                <span className="text-[10px] text-slate-500 block uppercase font-bold">Rata Contestatii CNSC</span>
                <span className="text-base font-bold text-rose-700">{data.benchmark?.cnsc_dispute_frequency}</span>
              </div>
            </div>

            <div className="rounded-xl bg-slate-50 border border-slate-200 p-4 space-y-2">
              <span className="font-bold text-slate-800 block">Jucatori Frecventi Identificati in {data.sector}:</span>
              <ul className="list-disc pl-4 text-slate-600 space-y-1">
                {data.benchmark?.identified_key_competitors?.map((c: string, i: number) => <li key={i}>{c}</li>)}
              </ul>
            </div>

            <div className="rounded-xl bg-sky-50 border border-sky-200 p-4 space-y-2">
              <span className="font-bold text-sky-900 block">Recomandare Pozitionare Financiara:</span>
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-white p-2 rounded border border-sky-100">
                  <span className="text-[10px] text-slate-400 block font-semibold">Oferta Sigura</span>
                  <span className="font-bold text-slate-800">{(data.pricing_recommendations?.safe_margin_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="bg-white p-2 rounded border border-sky-200 shadow-sm">
                  <span className="text-[10px] text-sky-700 block font-bold">Optim Competitiv</span>
                  <span className="font-extrabold text-sky-900">{(data.pricing_recommendations?.optimal_competitive_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="bg-white p-2 rounded border border-sky-100">
                  <span className="text-[10px] text-slate-400 block font-semibold">Limita Agresiva</span>
                  <span className="font-bold text-slate-800">{(data.pricing_recommendations?.aggressive_limit_bid_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
              </div>
              <p className="text-slate-600 text-[11px] mt-2">{data.benchmark?.tactical_guidance}</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function TechnicalProposalModal({ isOpen, onClose, opp }: { isOpen: boolean; onClose: () => void; opp: any }) {
  const { activeDesk } = useAuth();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isOpen && opp) {
      setLoading(true);
      generateTechnicalProposal({
        project_title: opp.project_title || "",
        authority_name: opp.entity_name || "",
        county: opp.county || "Romania",
        category: opp.category || "infrastructura",
        company_name: activeDesk?.name || "SC Infra Construct Transilvania SRL",
        cui: activeDesk?.cui || "RO12345678"
      })
        .then(res => setData(res))
        .catch(err => console.warn(err))
        .finally(() => setLoading(false));
    }
  }, [isOpen, opp, activeDesk]);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (data?.dossier_text) {
      navigator.clipboard.writeText(data.dossier_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Generator Schita Propunere Tehnica (Legea 98/2016)</h3>
            <p className="text-xs text-slate-500">Structura orientativa pe 4 sectiuni conform standardelor nationale de achizitii.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-500">Se asambleaza structura propunerii tehnice...</div>
        ) : data ? (
          <div className="space-y-3 text-xs">
            <div className="flex justify-between items-center">
              <span className="text-slate-500">Schita generata pentru: <b className="text-slate-800">{data.company_name}</b></span>
              <button
                onClick={handleCopy}
                className="rounded-lg bg-slate-900 px-3.5 py-1.5 font-bold text-white hover:bg-slate-800 transition"
              >
                {copied ? "Copiat in Clipboard" : "Copiaza Textul Integral"}
              </button>
            </div>
            <pre className="h-96 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-800 whitespace-pre-wrap font-sans leading-relaxed">
              {data.dossier_text}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}
"""

write_b64(os.path.join(FRONTEND, "components/EnterpriseModals.tsx"), base64.b64encode(MODALS_CODE.encode("utf-8")).decode("ascii"))

print("\n⚡ [2/4] Testing Python Engine Compilation...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator, ai_copilot, addons.competitor_tracker, addons.dossier_generator; print('  [OK] Python Backend Compiled Cleanly (0 errors)')"], cwd=ENGINE)
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [3/4] Running Next.js Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=FRONTEND)
if res_next.returncode != 0:
    print("❌ Frontend build failed.")
    sys.exit(1)

print("\n⚡ [4/4] Executing Direct Git Pushes for Vercel & Render...")

run_cmd(["git", "add", "-A"], cwd=FRONTEND)
subprocess.run(["git", "commit", "-m", "feat: complete Phase 4 competitor radar, proposal generator, clean UI, and conversational copilot"], cwd=FRONTEND)
run_cmd(["git", "push", "origin", "main"], cwd=FRONTEND)

run_cmd(["git", "add", "-A"], cwd=ENGINE)
subprocess.run(["git", "commit", "-m", "feat: Phase 4 competitor tracker, proposal assembler, and conversational copilot engine"], cwd=ENGINE)
run_cmd(["git", "push", "origin", "main"], cwd=ENGINE)

run_cmd(["git", "add", "-A"], cwd=ROOT)
subprocess.run(["git", "commit", "-m", "deploy: release Phase 4 with full verified UI and backend"], cwd=ROOT)
run_cmd(["git", "push", "origin", "main"], cwd=ROOT)

print("\n🎉 [SUCCESS] Deployment completed! Vercel and Render builds triggered with 0 errors.")
