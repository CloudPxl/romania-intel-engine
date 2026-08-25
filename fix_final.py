import os, subprocess

frontend_dir = os.path.join(os.path.dirname(__file__), "romania-intel-frontend")
modals_path = os.path.join(frontend_dir, "components", "EnterpriseModals.tsx")

code = """\"use client\";
import React, { useState, useEffect } from "react";
import {
  generateProformaInvoice,
  uploadCaietFile,
  analyzeCaietSarcini,
  predictWinRate,
  generateLegalClarification,
  evaluateBusinessEligibility,
  askCopilotChat,
  fetchTenantPipeline
} from "../lib/api";

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
      alert("Eroare: " + (e?.message || "Nu s-a putut genera factura proformă."));
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-4xl rounded-2xl border border-cyan-800/60 bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-6 border-b border-[#1e293b] pb-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-cyan-400">Activare Abonament & Factură Proformă</h2>
            <p className="text-xs text-slate-400">Generare instantanee Factură Proformă pentru plată prin Ordin de Plată (OP) sau Card.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-[#1e293b] hover:text-white">✕</button>
        </div>

        {!proformaData ? (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
              <div
                onClick={() => setSelectedPlan("plan_acces_complet")}
                className={`cursor-pointer flex flex-col justify-between rounded-xl border p-5 transition ${
                  selectedPlan === "plan_acces_complet" ? "border-cyan-400 bg-cyan-950/20" : "border-slate-700 bg-[#131d2e] hover:border-slate-500"
                }`}
              >
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-lg font-bold">Acces Complet Desk</h3>
                    <span className="rounded bg-cyan-950 px-2 py-0.5 text-[10px] font-semibold text-cyan-400">STANDARD</span>
                  </div>
                  <p className="text-2xl font-extrabold text-white mb-3">499 <span className="text-xs font-normal text-slate-400">RON / lună</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-300">
                    <li>✓ Acces la toate cele 25 de registre active</li>
                    <li>✓ Sinteze Executive Grok AI</li>
                    <li>✓ Export CSV date calificate</li>
                    <li>✓ 1 Workspace & 2 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-slate-800 py-2 text-xs font-bold text-white">
                  {selectedPlan === "plan_acces_complet" ? "Plan Selectat ✓" : "Selectează 499 RON"}
                </button>
              </div>

              <div
                onClick={() => setSelectedPlan("plan_founder_vip")}
                className={`cursor-pointer flex flex-col justify-between rounded-xl border-2 p-5 relative transition ${
                  selectedPlan === "plan_founder_vip" ? "border-cyan-400 bg-cyan-950/30" : "border-cyan-600/60 bg-[#131d2e] hover:border-cyan-400"
                }`}
              >
                <span className="absolute -top-3 right-4 rounded-full bg-cyan-500 px-2.5 py-0.5 text-[9px] font-bold text-black uppercase">Recomandat</span>
                <div>
                  <div className="flex justify-between items-baseline mb-2">
                    <h3 className="text-lg font-bold text-cyan-400">VIP Founder & Multi-Divizie</h3>
                    <span className="rounded bg-cyan-900/60 px-2 py-0.5 text-[10px] font-semibold text-cyan-300">ENTERPRISE</span>
                  </div>
                  <p className="text-2xl font-extrabold text-white mb-3">1499 <span className="text-xs font-normal text-slate-400">RON / lună</span></p>
                  <ul className="space-y-1.5 text-xs text-slate-300">
                    <li className="text-cyan-200">✓ Tot ce include pachetul Acces Complet</li>
                    <li>✓ Scanner Caiet de Sarcini (Upload PDF/DOCX)</li>
                    <li>✓ Simulator Șanse de Câștig & Marje</li>
                    <li>✓ Generator Adrese Legea 544</li>
                    <li>✓ Alerte automate Email & Telegram</li>
                    <li>✓ Până la 10 Utilizatori</li>
                  </ul>
                </div>
                <button className="mt-4 w-full rounded-lg bg-cyan-500 py-2 text-xs font-bold text-black">
                  {selectedPlan === "plan_founder_vip" ? "Plan Selectat ✓" : "Selectează 1499 RON"}
                </button>
              </div>
            </div>

            {selectedPlan && (
              <div className="rounded-xl border border-[#1e293b] bg-[#131d2e] p-4 text-xs space-y-3">
                <span className="font-bold text-cyan-300 block uppercase text-[11px]">Date Facturare Companie (Pentru Factura Proformă):</span>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-400 mb-1">Denumire Companie</label>
                    <input type="text" value={companyName} onChange={e => setCompanyName(e.target.value)} className="w-full rounded-lg bg-[#0b111e] border border-slate-700 p-2 text-white" />
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">CUI / CIF</label>
                    <input type="text" value={cui} onChange={e => setCui(e.target.value)} className="w-full rounded-lg bg-[#0b111e] border border-slate-700 p-2 text-white" />
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Email Facturare</label>
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)} className="w-full rounded-lg bg-[#0b111e] border border-slate-700 p-2 text-white" />
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Adresă Sediu Social</label>
                    <input type="text" value={address} onChange={e => setAddress(e.target.value)} className="w-full rounded-lg bg-[#0b111e] border border-slate-700 p-2 text-white" />
                  </div>
                </div>

                <button
                  onClick={handleGenerateProforma}
                  disabled={loading}
                  className="mt-3 w-full rounded-xl bg-cyan-500 py-2.5 font-bold text-black text-xs hover:bg-cyan-400 transition"
                >
                  {loading ? "Se emite proforma..." : `Generează Factura Proformă (${selectedPlan === "plan_founder_vip" ? "1499" : "499"} RON)`}
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="rounded-xl border border-emerald-500/40 bg-emerald-950/20 p-4 text-center">
              <span className="text-emerald-400 font-bold block text-sm">✓ Factura Proformă {proformaData.invoice_number} a fost emisă cu succes!</span>
              <p className="text-slate-300 text-xs mt-1">Total de plată: <b>{proformaData.total_ron} RON</b> pentru {proformaData.plan_name}</p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-[#131d2e] p-4 space-y-2">
              <span className="font-bold text-cyan-400 block">Date Transfer Bancar (Ordin de Plată - OP):</span>
              <p className="text-slate-300">Banca: <b>{proformaData.bank_details.bank_name}</b></p>
              <p className="text-slate-300">IBAN: <b className="font-mono text-cyan-300">{proformaData.bank_details.iban_ron}</b></p>
              <p className="text-slate-300">Beneficiar: <b>{proformaData.bank_details.beneficiary}</b></p>
              <p className="text-slate-300">Detalii Plată: <b>{proformaData.bank_details.payment_details_prefix}{proformaData.invoice_number} ({proformaData.cui_fiscal})</b></p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handlePrint}
                className="flex-1 rounded-xl bg-cyan-500 py-2.5 font-bold text-black hover:bg-cyan-400 transition"
              >
                Descarcă / Printează Factura Proformă (PDF)
              </button>
              <button
                onClick={() => setProformaData(null)}
                className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2.5 font-semibold text-slate-300 hover:text-white"
              >
                Modifică Datele
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-2xl border border-[#1e293b] bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <h3 className="text-xl font-bold text-amber-400">Scanner Clauze Restrictive (Caiet de Sarcini)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>
        <p className="text-xs text-slate-400 mb-3 font-mono">Proiect: {defaultTitle}</p>

        <div className="rounded-xl border-2 border-dashed border-slate-700 bg-[#131d2e] p-4 text-center mb-3">
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="hidden"
            id="caiet-upload"
          />
          <label htmlFor="caiet-upload" className="cursor-pointer block">
            <span className="text-cyan-400 font-bold block text-xs">
              {file ? `Fișier selectat: ${file.name}` : "📂 Trageți fișierul PDF sau DOCX aici (sau click pentru a alege)"}
            </span>
            <span className="text-[10px] text-slate-500 mt-1 block">Suportă Caiete de Sarcini oficiale PDF, DOCX</span>
          </label>
        </div>

        <div className="text-center text-[10px] text-slate-500 mb-2">SAU LIPIȚI TEXTUL DIRECT</div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Lipiți aici textul din caietul de sarcini..."
          className="w-full h-24 rounded-xl border border-slate-700 bg-[#131d2e] p-3 text-xs text-slate-200 focus:border-amber-400 focus:outline-none"
        />

        <button
          onClick={handleAnalyze}
          disabled={loading || (!text && !file)}
          className="mt-3 w-full rounded-xl bg-amber-500 py-2.5 font-bold text-black text-xs hover:bg-amber-400 transition"
        >
          {loading ? "Se analizează documentul conform jurisprudenței CNSC..." : "Scanează Clauze Restrictive"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-800 bg-[#131d2e] p-4 text-xs">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-slate-300">Nivel Risc Restrictiv:</span>
              <span className="font-bold text-amber-400">{result.bias_risk_level} (Scor: {result.bias_score}/10)</span>
            </div>
            <p className="text-slate-400">{result.recommended_action}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-400 uppercase text-[10px]">Clauze Identificate:</span>
              {result.detected_red_flags && result.detected_red_flags.map((flag: any, i: number) => (
                <div key={i} className="rounded bg-black/40 p-2.5 border-l-2 border-amber-500">
                  <p className="font-bold text-amber-300">{flag.pattern} — Risc {flag.severity}</p>
                  <p className="text-slate-300 mt-0.5">{flag.tactical_advisory}</p>
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
  const [companyName, setCompanyName] = useState("SC Infra Construct Transilvania SRL");
  const [cui, setCui] = useState("RO12345678");
  const [caen, setCaen] = useState("4211");
  const [turnover, setTurnover] = useState(18500000);
  const [employees, setEmployees] = useState(48);
  const [county, setCounty] = useState("Cluj");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

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
      alert("Eroare la scanare: " + (e?.message || "Verificați conexiunea cu serverul API."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-3xl rounded-2xl border border-cyan-800/60 bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <div>
            <h3 className="text-xl font-bold text-cyan-400">Scanner Eligibilitate Granturi & Licitații Strategice</h3>
            <p className="text-xs text-slate-400">Evaluare automată a profilului companiei conform ghidurilor PNRR / MIPE 2026.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs mb-4">
          <div>
            <label className="block text-slate-400 mb-1">Nume Companie</label>
            <input type="text" value={companyName} onChange={e => setCompanyName(e.target.value)} className="w-full rounded-lg bg-[#131d2e] border border-slate-700 p-2 text-white" />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">CUI / Cod Fiscal</label>
            <input type="text" value={cui} onChange={e => setCui(e.target.value)} className="w-full rounded-lg bg-[#131d2e] border border-slate-700 p-2 text-white" />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">Cod CAEN Principal</label>
            <input type="text" value={caen} onChange={e => setCaen(e.target.value)} className="w-full rounded-lg bg-[#131d2e] border border-slate-700 p-2 text-white" />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">Cifră de Afaceri Anuală (RON)</label>
            <input type="number" value={turnover} onChange={e => setTurnover(Number(e.target.value))} className="w-full rounded-lg bg-[#131d2e] border border-slate-700 p-2 text-white" />
          </div>
        </div>

        <button onClick={handleScan} disabled={loading} className="w-full rounded-xl bg-cyan-500 py-2.5 font-bold text-black text-xs hover:bg-cyan-400 transition">
          {loading ? "Se verifică criteriile de eligibilitate..." : "Evaluează Profilul Companiei"}
        </button>

        {result && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-800 bg-[#131d2e] p-4 text-xs">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2">
              <span className="font-bold text-slate-200">{result.qualification_status}</span>
              <span className="rounded bg-emerald-950 px-2 py-0.5 font-bold text-emerald-400">Scor: {result.overall_eligibility_score}/10</span>
            </div>
            <p className="text-slate-300 leading-relaxed">{result.advisory_summary}</p>
            <div className="space-y-2 mt-2">
              <span className="font-bold text-slate-400 uppercase text-[10px]">Linii de Finanțare Eligibile:</span>
              {result.matched_grants && result.matched_grants.map((g: any, i: number) => (
                <div key={i} className="rounded bg-black/40 p-3 border-l-2 border-cyan-500">
                  <div className="flex justify-between">
                    <span className="font-bold text-cyan-300">{g.program_name}</span>
                    <span className="font-bold text-emerald-400">Până la {g.eligible_grant_up_to}</span>
                  </div>
                  <p className="text-slate-400 text-[11px] mt-1">Cofinanțare: {g.required_co_financing} | Bază legală: {g.legal_basis}</p>
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
    { sender: "ai", text: "Bună ziua! Sunt Copilotul AI RO-INTEL. Cum vă pot ajuta cu strategiile de ofertare, cerințele tehnice sau dosarele din ultimele 72 de ore?" }
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-3xl rounded-2xl border border-cyan-800/60 bg-[#0b111e] p-6 shadow-2xl text-white flex flex-col h-[85vh]">
        <div className="flex justify-between items-center mb-3 border-b border-[#1e293b] pb-2">
          <div>
            <h3 className="text-lg font-bold text-cyan-400">Copilot AI Bidding & Radar 72h</h3>
            <p className="text-xs text-slate-400">{report72h?.period || "Ultimele 72 ore"}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>

        {report72h && (
          <div className="rounded-xl bg-[#131d2e] p-3 text-xs mb-3 border border-slate-800 space-y-1">
            <span className="font-bold text-slate-300 block">Sinteză Macro Ultimele 72h:</span>
            <ul className="list-disc pl-4 text-slate-400 space-y-0.5">
              {report72h.executive_takeaways && report72h.executive_takeaways.map((t: string, i: number) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 p-2 text-xs">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.sender === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-xl p-3 ${m.sender === "user" ? "bg-cyan-600 text-black font-semibold" : "bg-[#131d2e] border border-slate-800 text-slate-200"}`}>
                {m.text}
              </div>
            </div>
          ))}
          {loading && <div className="text-slate-400 text-xs animate-pulse">Copilotul AI analizează dosarele pre-SEAP...</div>}
        </div>

        <div className="flex gap-2 mt-3 pt-2 border-t border-[#1e293b]">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
            placeholder="Întrebați despre cerințe de atribuire, licitații CNI, bugete sau contestații..."
            className="flex-1 rounded-xl border border-slate-700 bg-[#131d2e] px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500"
          />
          <button onClick={handleSend} disabled={loading} className="rounded-xl bg-cyan-500 px-4 py-2 font-bold text-black text-xs hover:bg-cyan-400">
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
      alert("Eroare la calcularea șanselor.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-xl rounded-2xl border border-[#1e293b] bg-[#0b111e] p-6 shadow-2xl text-white">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <h3 className="text-xl font-bold text-emerald-400">Simulator Șanse de Câștig & Marjă Optimă</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>
        <div className="space-y-3 text-xs">
          <div>
            <label className="block text-slate-400 mb-1">Buget Estimat Autoritate Contractantă (RON)</label>
            <input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="w-full rounded-xl border border-slate-700 bg-[#131d2e] p-2.5 text-white" />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">Preț Ofertat Propus (RON)</label>
            <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} className="w-full rounded-xl border border-slate-700 bg-[#131d2e] p-2.5 text-white" />
          </div>
          <label className="flex items-center gap-2 text-slate-300">
            <input type="checkbox" checked={hasPartner} onChange={(e) => setHasPartner(e.target.checked)} className="rounded" />
            Consorțiu / Subcontractant local în județul autorității (+12% logistică)
          </label>
          <button onClick={handleCalculate} disabled={loading} className="w-full rounded-xl bg-emerald-500 py-2.5 font-bold text-black text-xs hover:bg-emerald-400 transition">
            {loading ? "Se evaluează..." : "Calculează Probabilitate Câștig"}
          </button>
          {result && (
            <div className="rounded-xl border border-slate-800 bg-[#131d2e] p-4 text-center mt-3">
              <p className="uppercase text-slate-400 text-[10px]">Probabilitate Estimată de Atribuire</p>
              <p className="text-3xl font-extrabold text-emerald-400 my-1">{result.win_probability_score}</p>
              <p className="text-slate-300">Discount propus: <span className="font-bold text-white">{result.discount_percentage}</span> ({result.rating})</p>
              <p className="text-slate-400 mt-2 text-left bg-black/30 p-2.5 rounded border border-slate-800 text-[11px]">{result.tactical_guidance}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ClarificationModal({ isOpen, onClose, opp }: { isOpen: boolean; onClose: () => void; opp: any }) {
  const [points, setPoints] = useState("1. Solicităm eliminarea cerinței de autorizație directă de la producător.\\n2. Solicităm acceptarea standardelor tehnice europene echivalente conform Art. 160 Legea 98/2016.");
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
        company_name: "SC Infra Construct Transilvania SRL",
        cui_fiscal: "RO12345678",
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-2xl rounded-2xl border border-[#1e293b] bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <h3 className="text-xl font-bold text-cyan-400">Generator Solicitare Clarificări (Legea 98/2016)</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>
        <p className="text-xs text-slate-400 mb-2 font-mono">Autoritate: {opp.entity_name}</p>
        <label className="block text-xs text-slate-300 mb-1">Puncte de clarificat / Clauze restrictive:</label>
        <textarea
          value={points}
          onChange={(e) => setPoints(e.target.value)}
          className="w-full h-24 rounded-xl border border-slate-700 bg-[#131d2e] p-2.5 text-xs text-slate-200 mb-3 focus:outline-none"
        />
        <button onClick={handleGenerate} disabled={loading} className="w-full rounded-xl bg-cyan-500 py-2.5 font-bold text-black text-xs hover:bg-cyan-400 transition">
          {loading ? "Se redactează adresa oficială..." : "Generează Adresă Oficială"}
        </button>
        {letter && (
          <div className="mt-4">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs font-bold text-slate-300">Document Generat (Gata de semnare):</span>
              <button onClick={copyToClipboard} className="rounded bg-slate-800 px-3 py-1 text-xs font-semibold text-cyan-400 hover:bg-slate-700">
                {copied ? "Copiat!" : "Copiază Textul"}
              </button>
            </div>
            <pre className="h-48 overflow-y-auto rounded-xl border border-slate-800 bg-[#060b13] p-3 text-xs text-slate-300 whitespace-pre-wrap font-sans">
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-5xl rounded-2xl border border-cyan-800/60 bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <div>
            <h3 className="text-xl font-bold text-cyan-400">Pipeline Bidding & Management Dosare Pre-SEAP</h3>
            <p className="text-xs text-slate-400">Monitorizare stadiu intern: evaluare tehnică, adrese clarificări și marje estimate.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-xs text-slate-400">Se încarcă pipeline-ul companiei...</div>
        ) : !pipelineData?.deals?.length ? (
          <div className="flex h-48 flex-col items-center justify-center text-xs text-slate-500 space-y-2">
            <span>Nu aveți dosare salvate în pipeline-ul curent.</span>
            <span className="text-[11px] text-cyan-400">Deschideți orice dosar din feed-ul principal și apăsați "Salvează în Pipeline".</span>
          </div>
        ) : (
          <div className="space-y-3">
            {pipelineData.deals && pipelineData.deals.map((d: any) => (
              <div key={d.deal_id} className="rounded-xl border border-[#1e293b] bg-[#131d2e] p-4 text-xs space-y-2">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="rounded bg-cyan-950 px-2 py-0.5 text-[10px] font-bold text-cyan-400 border border-cyan-800/40 uppercase">
                      {d.stage ? d.stage.replace("_", " ") : "Nou"}
                    </span>
                    <h4 className="font-bold text-slate-100 text-sm mt-1">{d.project_title}</h4>
                    <p className="text-slate-400 text-xs">{d.entity_name}</p>
                  </div>
                  <div className="text-right">
                    <span className="text-sm font-extrabold text-white">{(d.financial_value_ron / 1000000).toFixed(2)} Mil. RON</span>
                    <span className="block text-[10px] text-emerald-400 font-bold">Marjă Țintă: {d.target_margin_pct}%</span>
                  </div>
                </div>
                <div className="rounded bg-black/40 p-2 text-slate-300 text-[11px]">
                  <b>Notițe Bidding:</b> {d.notes}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
"""

with open(modals_path, "w", encoding="utf-8") as f:
    f.write(code)

print("  [✓] EnterpriseModals.tsx written cleanly.")

print("  [>] Running npm run build...")
res = subprocess.run(["npm", "run", "build"], cwd=os.path.join(ROOT, "romania-intel-frontend"))
if res.returncode == 0:
    print("\n🎉 [SUCCESS] Next.js frontend compiled with 0 errors!")
else:
    print("\n❌ Build failed.")
    sys.exit(1)
