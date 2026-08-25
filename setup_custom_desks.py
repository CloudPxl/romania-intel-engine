import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, "romania-intel-engine")
FRONTEND = os.path.join(ROOT, "romania-intel-frontend")

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print("  [✓] Written: " + os.path.relpath(path, ROOT))

def run_cmd(cmd, cwd):
    print(f"\n[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"❌ Failed: {' '.join(cmd)}")
        sys.exit(1)

print("\n⚡ [1/4] Writing Dynamic Business Desk & Workspace Engine...")

# 1. AUTH CONTEXT WITH MULTI-DESK WORKSPACE MANAGEMENT
write_file(os.path.join(FRONTEND, "context/AuthContext.tsx"), """\"use client\";
import React, { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { syncBackendAuth, switchTenantWorkspace } from "@/lib/api";

export interface BusinessDivision {
  id: string;
  name: string;
  keywords: string[];
}

export interface BusinessDesk {
  id: string;
  name: string;
  cui: string;
  primary_domain: string;
  target_counties: string[];
  min_budget_ron: number;
  keywords: string[];
  divisions: BusinessDivision[];
}

export interface UserProfile {
  email: string;
  full_name: string;
  tenant_id: string;
  role: string;
  avatar_url?: string;
  is_subscribed?: boolean;
}

export interface UserPreferences {
  notification_email?: string;
  auto_alert_score: number;
  default_sort: "score_desc" | "budget_desc" | "date_desc" | "deadline_asc";
}

interface AuthContextType {
  user: UserProfile | null;
  loading: boolean;
  preferences: UserPreferences;
  updatePreferences: (newPrefs: Partial<UserPreferences>) => void;
  desks: BusinessDesk[];
  activeDesk: BusinessDesk;
  createDesk: (desk: Omit<BusinessDesk, "id">) => void;
  updateDesk: (id: string, desk: Partial<BusinessDesk>) => void;
  deleteDesk: (id: string) => void;
  switchDesk: (id: string) => void;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const DEFAULT_DESKS: BusinessDesk[] = [
  {
    id: "desk_main_infra",
    name: "SC Infra Construct Transilvania SRL",
    cui: "RO12345678",
    primary_domain: "infrastructura",
    target_counties: ["Cluj", "Iasi", "Bihor", "Timis", "Bucuresti", "Brasov", "Constanta"],
    min_budget_ron: 5000000,
    keywords: ["drum", "pod", "pasaj", "asfalt", "its", "scats", "semaforizare", "metrou  divisions: [
      { id: "div_heavy", name: "Infrastructura Grea & Drumuri", keywords: ["drum", "pod", "asfalt", "metrou"] },
      { id: "div_its", name: "Smart City & Sisteme ITS", keywords: ["its", "scats", "semaforizare", "anpr"] }
    ]
  },
  {
    id: "desk_medtech",
    name: "SC MedTech Pharma SRL",
    cui: "RO98765432",
    primary_domain: "sanatate",
    target_counties: ["Bucuresti", "Iasi", "Cluj", "Timis", "Brasov"],
    min_budget_ron: 3000000,
    keywords: ["rmn", "ct", "accelerator", "radioterapie", "spital", "oncologie", "pacs"],
    divisions: [
      { id: "div_imagistica", name: "Imagistica Medicala & RMN", keywords: ["rmn", "ct", "radioterapie"] },
      { id: "div_digital_health", name: "Digitalizare Spitale PACS", keywords: ["pacs", "soft medical"] }
    ]
  }
];

const DEFAULT_PREFERENCES: UserPreferences = {
  notification_email: "",
  auto_alert_score: 9.0,
  default_sort: "score_desc"
};

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  preferences: DEFAULT_PREFERENCES,
  updatePreferences: () => {},
  desks: DEFAULT_DESKS,
  activeDesk: DEFAULT_DESKS[0],
  createDesk: () => {},
  updateDesk: () => {},
  deleteDesk: () => {},
  switchDesk: () => {},
  signInWithGoogle: async () => {},
  signInWithEmail: async () => ({ error: null }),
  signOut: async () => {}
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [desks, setDesks] = useState<BusinessDesk[]>(DEFAULT_DESKS);
  const [activeDeskId, setActiveDeskId] = useState<string>(DEFAULT_DESKS[0].id);
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedDesks = localStorage.getItem("ro_intel_user_desks");
      const savedActiveId = localStorage.getItem("ro_intel_active_desk_id");
      const savedPrefs = localStorage.getItem("ro_intel_user_prefs");

      if (savedDesks) {
        try {
          const parsed = JSON.parse(savedDesks);
          if (parsed && parsed.length > 0) setDesks(parsed);
        } catch {}
      }
      if (savedActiveId) setActiveDeskId(savedActiveId);
      if (savedPrefs) {
        try { setPreferences(JSON.parse(savedPrefs)); } catch {}
      }
    }
  }, []);

  const saveDesksToStorage = (updatedDesks: BusinessDesk[]) => {
    setDesks(updatedDesks);
    if (typeof window !== "undefined") {
      localStorage.setItem("ro_intel_user_desks", JSON.stringify(updatedDesks));
    }
  };

  const createDesk = (deskData: Omit<BusinessDesk, "id">) => {
    const newDesk: BusinessDesk = {
      ...deskData,
      id: "desk_" + Date.now()
    };
    const updated = [...desks, newDesk];
    saveDesksToStorage(updated);
    switchDesk(newDesk.id);
  };

  const updateDesk = (id: string, deskData: Partial<BusinessDesk>) => {
    const updated = desks.map(d => (d.id === id ? { ...d, ...deskData } : d));
    saveDesksToStorage(updated);
  };

  const deleteDesk = (id: string) => {
    if (desks.length <= 1) {
      alert("Trebuie sa pastrati cel putin un Desk activ.");
      return;
    }
    const updated = desks.filter(d => d.id !== id);
    saveDesksToStorage(updated);
    if (activeDeskId === id) {
      switchDesk(updated[0].id);
    }
  };

  const switchDesk = (id: string) => {
    setActiveDeskId(id);
    if (typeof window !== "undefined") {
      localStorage.setItem("ro_intel_active_desk_id", id);
    }
    switchTenantWorkspace(id);
  };

  const updatePreferences = (newPrefs: Partial<UserPreferences>) => {
    setPreferences(prev => {
      const updated = { ...prev, ...newPrefs };
      if (typeof window !== "undefined") {
        localStorage.setItem("ro_intel_user_prefs", JSON.stringify(updated));
      }
      return updated;
    });
  };

  useEffect(() => {
    async function initAuth() {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (session?.user) {
          const authUser = session.user;
          const synced = await syncBackendAuth(
            authUser.email || "user@ro-intel.xyz",
            authUser.user_metadata?.full_name || authUser.user_metadata?.name || authUser.email?.split("@")[0],
            authUser.user_metadata?.avatar_url
          );
          if (synced?.user) {
            setUser({ ...synced.user, is_subscribed: true });
          }
        } else {
          setUser(null);
        }
      } catch (err) {
        console.warn("[AuthInit] Session verify note:", err);
        setUser(null);
      } finally {
        setLoading(false);
      }
    }

    initAuth();

    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (_event, session) => {
      if (session?.user) {
        const authUser = session.user;
        const synced = await syncBackendAuth(
          authUser.email || "user@ro-intel.xyz",
          authUser.user_metadata?.full_name || authUser.user_metadata?.name,
          authUser.user_metadata?.avatar_url
        );
        if (synced?.user) {
          setUser({ ...synced.user, is_subscribed: true });
        }
      } else {
        setUser(null);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = async () => {
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: typeof window !== "undefined" ? window.location.origin : ""
      }
    });
  };

  const signInWithEmail = async (email: string) => {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: typeof window !== "undefined" ? window.location.origin : ""
      }
    });
    return { error: error ? error.message : null };
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    setUser(null);
  };

  const activeDesk = desks.find(d => d.id === activeDeskId) || desks[0] || DEFAULT_DESKS[0];

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        preferences,
        updatePreferences,
        desks,
        activeDesk,
        createDesk,
        updateDesk,
        deleteDesk,
        switchDesk,
        signInWithGoogle,
        signInWithEmail,
        signOut
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
""")

# 2. ENTERPRISE MODALS WITH WORKSPACE & DESK MANAGER MODAL
write_file(os.path.join(FRONTEND, "components/EnterpriseModals.tsx"), """\"use client\";
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
import { useAuth, BusinessDesk } from "../context/AuthContext";

// 1. BILLING & PROFORMA MODAL
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
                    <li>- Alerte automate Email (Resend)</li>
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
                    <input type="text" value={companyName} onChange={e => setCompanyName(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">CUI / CIF</label>
                    <input type="text" value={cui} onChange={e => setCui(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Email Facturare</label>
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Adresa Sediu Social</label>
                    <input type="text" value={address} onChange={e => setAddress(e.target.value)} className="w-full rounded-lg bg-white border border-slate-300 p-2 text-slate-900" />
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

// 2. CAIET SCANNER MODAL
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
              {file ? "Fisier stat: " + file.name : "Incarcati fisierul PDF sau DOCX aici (sau click pentru a alege)"}
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

// 3. BUSINESS ELIGIBILITY MODAL
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

// 4. COPILOT AI CHAT MODAL
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
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
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

// 5. WIN ODDS MODAL
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
      <div className="relative w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl text-slate-900">   <div className="flex justify-between items-center mb-4 border-b border-slate-100 pb-3">
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

// 6. CLARIFICATION MODAL
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

// 7. PIPELINE TRACKER MODAL
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

// 8. ACCOUNT SETTINGS & PREFERENCES MODAL
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
                    onChange={e => setEmailInput(e.target.value)}
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
                onChange={e => setAlertEmail(e.target.value)}
                placeholder="ex: director@infraconstruct.ro"
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-2.5 text-slate-900"
              />
            </div>
            <div>
              <label className="block text-slate-600 mb-1">Prag Minim Scor Oportunitate pentru Alerta Automata</label>
              <select
                value={scoreThreshold}
                onChange={e => setScoreThreshold(Number(e.target.value))}
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

// 9. DYNAMIC WORKSPACE & BUSINESS DESK MANAGER MODAL
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
                onChange={e => setName(e.target.value)}
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
                  onChange={e => setCui(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Domeniu Strategic Principal</label>
                <select
                  value={domain}
                  onChange={e => setDomain(e.target.value)}
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
                onChange={e => setCounties(e.target.value)}
                className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
              />
            </div>

            <div>
              <label className="block text-slate-600 mb-1">Cuvinte-cheie Monitorizate (separate prin virgula)</label>
              <input
                type="text"
                placeholder="ex: pod, asfalt, consolidare, statie tratare"
                value={keywords}
                onChange={e => setKeywords(e.target.value)}
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
                  onChange={e => setDivisionName(e.target.value)}
                  className="w-full rounded-lg bg-slate-50 border border-slate-300 p-2 text-slate-900 focus:bg-white"
                />
              </div>
              <div>
                <label className="block text-slate-600 mb-1">Buget Minim Proiect (RON)</label>
                <input
                  type="number"
                  value={minBudget}
                  onChange={e => setMinBudget(Number(e.target.value))}
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
""")

# 3. MAIN PAGE WITH CLEAN LOGO (NO 2026, NO GREEN DOT) AND WORKING DESK SWITCHER
write_file(os.path.join(FRONTEND, "app/page.tsx"), """\"use client\";
import React, { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { fetchTenantFeed, fetchTenantProducts, fetch72hMarketReport, addLeadToPipeline, triggerEmailAlert } from "../lib/api";
import {
  PricingModal,
  CaietScannerModal,
  WinOddsModal,
  ClarificationModal,
  BusinessEligibilityModal,
  CopilotChatModal,
  PipelineTrackerModal,
  AccountSettingsModal,
  WorkspaceDeskModal
} from "../components/EnterpriseModals";

export default function DeskPage() {
  const { user, preferences, desks, activeDesk, switchDesk } = useAuth();
  const [selectedDivision, setSelectedDivision] = useState<string>("all");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [leads, setLeads] = useState<any[]>([]);
  const [selectedLead, setSelectedLead] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedCounty, setSelectedCounty] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<string>("score_desc");
  const [report72h, setReport72h] = useState<any>(null);
  const [profileDropdownOpen, setProfileDropdownOpen] = useState(false);
  const [workspaceDropdownOpen, setWorkspaceDropdownOpen] = useState(false);
  const [emailSending, setEmailSending] = useState(false);
  const [emailSentSuccess, setEmailSentSuccess] = useState(false);

  // Modals
  const [pricingOpen, setPricingOpen] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [winModalOpen, setWinModalOpen] = useState(false);
  const [clarificationOpen, setClarificationOpen] = useState(false);
  const [businessScannerOpen, setBusinessScannerOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deskManagerOpen, setDeskManagerOpen] = useState(false);

  const loadWorkspace = async (force = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);

    try {
      const feedData = await fetchTenantFeed(activeDesk?.id || "desk_default", undefined, activeCategory, force);
      setLeads(feedData?.leads || []);

      const macroData = await fetch72hMarketReport(activeDesk?.id || "desk_default");
      setReport72h(macroData);
    } catch (err) {
      console.warn("[Desk] Load note:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadWorkspace(false);
  }, [activeDesk?.id, activeCategory]);

  const handleSaveToPipeline = async (lead: any) => {
    try {
      await addLeadToPipeline(activeDesk?.id || "desk_default", lead);
      alert("Dosarul a fost salvat in Pipeline.");
    } catch {
      alert("Eroare la salvarea in pipeline.");
    }
  };

  const handleSendEmailAlert = async (lead: any) => {
    setEmailSending(true);
    setEmailSentSuccess(false);
    try {
      const recipient = preferences?.notification_email || user?.email || "director@infraconstruct.ro";
      await triggerEmailAlert(lead, recipient);
      setEmailSentSuccess(true);
      setTimeout(() => setEmailSentSuccess(false), 4000);
    } catch {
      alert("Eroare la transmiterea alertei pe email.");
    } finally {
      setEmailSending(false);
    }
  };

  // Filter and Score according to Active Desk's target counties & keywords
  const filteredLeads = leads.filter((l) => {
    const matchCounty = selectedCounty === "all" || l?.county?.toLowerCase() === selectedCounty.toLowerCase();
    const matchSearch =
      !searchQuery ||
      l?.project_title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.entity_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.locality?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.sub_category?.toLowerCase().includes(searchQuery.toLowerCase());

    let matchDivision = true;
    if (selectedDivision !== "all" && activeDesk?.divisions) {
      const activeDiv = activeDesk.divisions.find(d => d.id === selectedDivision);
      if (activeDiv && activeDiv.keywords?.length > 0) {
        const text = (l?.project_title + " " + l?.executive_summary + " " + l?.sub_category).toLowerCase();
        matchDivision = activeDiv.keywords.some(k => text.includes(k.toLowerCase()));
      }
    }

    return matchCounty && matchSearch && matchDivision;
  });

  filteredLeads.sort((a, b) => {
    if (sortBy === "budget_desc") return (b.financial_value_ron || 0) - (a.financial_value_ron || 0);
    if (sortBy === "budget_asc") return (a.financial_value_ron || 0) - (b.financial_value_ron || 0);
    if (sortBy === "date_desc") return (b.published_date || "").localeCompare(a.published_date || "");
    return (b.opportunity_score || 0) - (a.opportunity_score || 0);
  });

  const totalPipeline = filteredLeads.reduce((acc, curr) => acc + (curr?.financial_value_ron || 0), 0);
  const isSubscriber = Boolean(user?.is_subscribed);

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-900 flex flex-col font-sans">
      {/* 1. TOP BAR WITH CLEAN LOGO (NO 2026, NO GREEN DOT) & WORKING WORKSPACE SELECTOR */}
      <header className="h-16 border-b border-slate-200 bg-white px-6 flex items-center justify-between sticky top-0 z-30 shadow-sm">
        <div className="flex items-center gap-5">
          {/* Clean Logo */}
          <span className="font-bold text-base tracking-wider text-slate-900 uppercase">
            RO-INTEL
          </span>

          {/* Dynamic Desk / Workspace Selector */}
          <div className="relative">
            <button
              onClick={() => setWorkspaceDropdownOpen(!workspaceDropdownOpen)}
              className="flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-800 hover:border-slate-400 hover:bg-white transition shadow-sm"
            >
              <span className="h-2 w-2 rounded-full bg-sky-600"></span>
              <span className="truncate max-w-[200px]">{activeDesk?.name || "Selecteaza Desk"}</span>
              <span className="text-[10px] text-slate-500 font-normal">▼</span>
            </button>

            {workspaceDropdownOpen && (
              <div className="absolute left-0 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-xl z-50 text-xs space-y-1">
                <span className="text-[10px] uppercase font-bold text-slate-400 px-2 py-1 block">Companii & Desk-uri</span>
                {desks.map((d) => (
                  <button
                    key={d.id}
                    onClick={() => {
                      switchDesk(d.id);
                      setSelectedDivision("all");
                      setWorkspaceDropdownOpen(false);
                    }}
                    className={"w-full text-left rounded-lg px-2.5 py-2 transition flex items-center justify-between " + (activeDesk?.id === d.id ? "bg-sky-50 text-sky-800 font-bold border border-sky-200" : "text-slate-700 hover:bg-slate-100")}
                  >
                    <span className="truncate">{d.name}</span>
                    {activeDesk?.id === d.id && <span className="text-sky-700 text-xs font-bold">Activ</span>}
                  </button>
                ))}
                <div className="border-t border-slate-100 pt-1 mt-1">
                  <button
                    onClick={() => {
                      setWorkspaceDropdownOpen(false);
                      setDeskManagerOpen(true);
                    }}
                    className="w-full text-left rounded-lg px-2.5 py-1.5 font-bold text-sky-700 hover:bg-sky-50 transition"
                  >
                    + Administrare & Adaugare Companii
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPipelineOpen(true)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
          >
            Pipeline Oportunitati
          </button>

          <button
            onClick={() => setBusinessScannerOpen(true)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
          >
            Eligibilitate Finantari
          </button>

          <button
            onClick={() => setCopilotOpen(true)}
            className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100 transition shadow-sm"
          >
            Copilot AI & Radar 72h
          </button>

          <button
            onClick={() => setPricingOpen(true)}
            className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 transition shadow-sm"
          >
            Factura Proforma / OP
          </button>

          <div className="relative ml-2 pl-3 border-l border-slate-200">
            <button
              onClick={() => setProfileDropdownOpen(!profileDropdownOpen)}
              className="flex items-center gap-2 rounded-lg p-1 hover:bg-slate-100 transition"
            >
              <div className="h-7 w-7 rounded-full bg-slate-200 flex items-center justify-center font-bold text-xs text-slate-700 border border-slate-300">
                {user?.full_name ? user.full_name.charAt(0).toUpperCase() : "U"}
              </div>
              <div className="hidden lg:block text-left">
                <span className="block text-[11px] font-bold text-slate-800 leading-none">{user?.full_name || "Cont Nelogat"}</span>
                <span className="text-[10px] text-slate-500">{user?.role || "Vizitator Desk"}</span>
              </div>
            </button>

            {profileDropdownOpen && (
              <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl z-50 text-xs space-y-2">
                <div className="border-b border-slate-100 pb-2">
                  <p className="font-bold text-slate-900">{user?.full_name || "Utilizator Nelogat"}</p>
                  <p className="text-[11px] text-slate-500 truncate">{user?.email || "Acces limitat demo"}</p>
                  <span className="inline-block mt-1 rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                    {user?.role || "Neautentificat"}
                  </span>
                </div>

                <button
                  onClick={() => {
                    setProfileDropdownOpen(false);
                    setSettingsOpen(true);
                  }}
                  className="w-full rounded-lg bg-slate-100 py-2 text-center text-slate-700 hover:bg-slate-200 transition font-medium"
                >
                  Setari Cont & Alerte
                </button>

                <button
                  onClick={() => {
                    setProfileDropdownOpen(false);
                    setDeskManagerOpen(true);
                  }}
                  className="w-full rounded-lg bg-slate-100 py-2 text-center text-slate-700 hover:bg-slate-200 transition font-medium"
                >
                  Companii & Desk-uri
                </button>

                {!user ? (
                  <button
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      setSettingsOpen(true);
                    }}
                    className="w-full rounded-lg bg-sky-600 py-2 text-center text-white hover:bg-sky-700 transition font-bold"
                  >
                    Autentificare / Log in
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      setProfileDropdownOpen(false);
                      setSettingsOpen(true);
                    }}
                    className="w-full rounded-lg bg-rose-50 py-2 text-center text-rose-700 hover:bg-rose-100 transition font-medium border border-rose-200"
                  >
                    Deconectare
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* 2. BODY CONTENT */}
      <div className="flex-1 flex overflow-hidden">
        {/* SIDEBAR */}
        <aside className="w-72 border-r border-slate-200 bg-white p-5 flex flex-col justify-between hidden md:flex">
          <div>
            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-3">Domenii Strategice</span>
            <div className="space-y-1 mb-5 text-xs">
              {[
                { id: "all", label: "Toate Categoriile (Complet)" },
                { id: "infrastructura", label: "Infrastructura & Transporturi" },
                { id: "sanatate", label: "Sanatate & Echipamente Medicale" },
                { id: "energie", label: "Energie & Utilitati Verzi" },
                { id: "aparare", label: "Aparare & Securitate Speciala" },
                { id: "digitalizare", label: "Digitalizare, IT & Smart City" }
              ].map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveCategory(c.id)}
                  className={"w-full text-left rounded-lg px-3 py-2 font-medium transition " + (activeCategory === c.id ? "bg-sky-50 text-sky-800 border border-sky-200 font-bold" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}
                >
                  {c.label}
                </button>
              ))}
            </div>

            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Divizii & Linii {activeDesk?.name ? `(${activeDesk.name.split(" ")[0]})` : ""}</span>
            <div className="space-y-1 mb-5">
              <button
                onClick={() => setSelectedDivision("all")}
                className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedDivision === "all" ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
              >
                Toate Liniile Desk
              </button>
              {activeDesk?.divisions?.map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSelectedDivision(d.id)}
                  className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedDivision === d.id ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
                >
                  {d.name}
                </button>
              ))}
            </div>

            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Filtrare Judet</span>
            <select
              value={selectedCounty}
              onChange={(e) => setSelectedCounty(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-slate-50 p-2 text-xs text-slate-800 focus:bg-white focus:outline-none focus:border-sky-500"
            >
              <option value="all">Toate Judetele Monitorizate (8)</option>
              <option value="Iasi">Iasi</option>
              <option value="Cluj">Cluj</option>
              <option value="Timis">Timis</option>
              <option value="Bucuresti">Bucuresti</option>
              <option value="Brasov">Brasov</option>
              <option value="Constanta">Constanta</option>
              <option value="Bihor">Bihor</option>
            </select>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs text-slate-600 shadow-sm">
            <span className="block text-[10px] uppercase font-bold text-slate-500">Volum Total Identificat</span>
            <span className="text-xl font-extrabold text-slate-900 mt-0.5 block">{(totalPipeline / 1000000).toFixed(1)} Mil. RON</span>
            <span className="text-[11px] text-emerald-700 font-medium block mt-1">25 Motoare de Monitorizare Active</span>
          </div>
        </aside>

        {/* MAIN FEED */}
        <main className="flex-1 p-6 overflow-y-auto">
          {/* SEARCH & ISOLATED REFRESH BUTTON TOOLBAR */}
          <div className="flex flex-col lg:flex-row gap-3 justify-between items-center mb-6 bg-white p-3.5 rounded-xl border border-slate-200 shadow-sm">
            <div className="flex-1 w-full lg:w-auto flex items-center gap-2">
              <input
                type="text"
                placeholder="Cautare dupa proiect, autoritate, subcategorie sau cod..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full md:w-96 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs text-slate-900 placeholder-slate-400 focus:bg-white focus:border-sky-600 focus:outline-none"
              />
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="rounded-lg border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 focus:bg-white focus:outline-none"
              >
                <option value="score_desc">Sortare: Scor Oportunitate</option>
                <option value="budget_desc">Sortare: Buget Descrescator</option>
                <option value="budget_asc">Sortare: Buget Crescator</option>
                <option value="date_desc">Sortare: Cele mai recente</option>
              </select>
            </div>

            <div className="flex items-center gap-2.5 w-full lg:w-auto justify-end">
              <span className="text-xs text-slate-500 font-medium">{filteredLeads.length} semnale</span>
              
              {/* ISOLATED REFRESH BUTTON */}
              <button
                onClick={() => loadWorkspace(true)}
                disabled={refreshing}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition shadow-sm"
              >
                {refreshing ? "Se actualizeaza..." : "Actualizeaza date"}
              </button>

              <a
                href={"https://api.ro-intel.xyz/api/v1/tenants/" + (activeDesk?.id || "desk_default") + "/export/csv"}
                download
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition shadow-sm"
              >
                Export CSV
              </a>
            </div>
          </div>

          {loading ? (
            <div className="flex h-64 items-center justify-center text-xs text-slate-500 font-medium">Sincronizare registru pre-SEAP...</div>
          ) : filteredLeads.length === 0 ? (
            <div className="flex h-64 items-center justify-center text-xs text-slate-500">Nu exista semnale pentru criteriile selectate.</div>
          ) : (
            <div className="grid grid-cols-1 gap-3.5">
              {filteredLeads.map((l, index) => {
                const isGated = !isSubscriber && index >= 2;
                return (
                  <div
                    key={l.source_id}
                    onClick={() => {
                      if (isGated) setPricingOpen(true);
                      else setSelectedLead(l);
                    }}
                    className={"relative rounded-xl border bg-white p-5 cursor-pointer transition shadow-sm " + (isGated ? "border-slate-200 opacity-80" : "border-slate-200 hover:border-sky-500 hover:shadow-md")}
                  >
                    <div className="flex justify-between items-start mb-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-sky-50 px-2 py-0.5 text-[10px] font-bold text-sky-800 border border-sky-200 uppercase">
                          {l.category}
                        </span>
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                          {l.sub_category || "General"}
                        </span>
                        <span className="text-xs text-slate-500">
                          {l.locality}, {l.county}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-base font-extrabold text-slate-900">
                          {l.financial_value_ron ? (l.financial_value_ron / 1000000).toFixed(1) + " Mil. RON" : "Buget Neestimat"}
                        </span>
                        <span className="block text-[11px] font-bold text-emerald-700">Scor: {l.opportunity_score} / 10</span>
                      </div>
                    </div>

                    <h4 className={"text-sm font-bold text-slate-900 mb-1 " + (isGated ? "blur-[2px]" : "")}>{l.project_title}</h4>
                    <p className="text-xs text-slate-600 mb-2 font-medium">{l.entity_name} &bull; Sursa: <span className="text-slate-800 font-semibold">{l.source_type}</span></p>
                    
                    <p className={"text-xs text-slate-700 line-clamp-2 leading-relaxed bg-slate-50 p-3 rounded-lg border border-slate-100 " + (isGated ? "blur-[3px] select-none" : "")}>
                      {l.executive_summary}
                    </p>

                    <div className="mt-3 flex flex-wrap items-center justify-between text-[11px] text-slate-500 border-t border-slate-100 pt-2.5">
                      <div className="flex items-center gap-4">
                        <span>Publicat: <b className="text-slate-800">{l.published_date || "2026-08-25"}</b></span>
                        <span>Termen Reactie: <b className="text-amber-700">{l.action_deadline || "T4 2026"}</b></span>
                      </div>
                      {isGated ? (
                        <span className="text-sky-700 font-bold">Deblocheaza Dosarul &rarr;</span>
                      ) : (
                        <span className="text-sky-700 font-semibold hover:underline">Deschide Dosar Strategic &rarr;</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </main>
      </div>

      {/* 3. SLIDE-OVER DOSSIER */}
      {selectedLead && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-xl bg-white border-l border-slate-200 shadow-2xl p-6 overflow-y-auto flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-start mb-4 border-b border-slate-200 pb-3">
              <div>
                <span className="text-[11px] font-bold text-sky-700 uppercase tracking-wide">Dosar Tehnic Pre-SEAP &bull; {selectedLead.source_id}</span>
                <h3 className="text-lg font-bold text-slate-900 mt-0.5">{selectedLead.project_title}</h3>
                <p className="text-xs text-slate-600">{selectedLead.entity_name} ({selectedLead.county})</p>
              </div>
              <button onClick={() => setSelectedLead(null)} className="text-slate-400 hover:text-slate-700 p-1 font-bold text-sm">✕</button>
            </div>

            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200">
                  <span className="text-[10px] text-slate-500 block uppercase font-semibold">Buget Estimat</span>
                  <span className="text-base font-extrabold text-slate-900">{(selectedLead.financial_value_ron / 1000000).toFixed(2)} Mil. RON</span>
                </div>
                <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200">
                  <span className="text-[10px] text-slate-500 block uppercase font-semibold">Sursa Finantare</span>
                  <span className="text-sm font-bold text-sky-800">{selectedLead.funding_source}</span>
                </div>
              </div>

              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-2">
                <div className="flex justify-between">
                  <span className="text-slate-500">Data Publicarii:</span>
                  <span className="font-semibold text-slate-800">{selectedLead.published_date}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Termen Limita Dialog Tehnic:</span>
                  <span className="font-semibold text-amber-700">{selectedLead.action_deadline || "Nespecificat"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Registru Sursa:</span>
                  <span className="font-semibold text-slate-800">{selectedLead.source_type}</span>
                </div>
              </div>

              <div className="rounded-xl bg-sky-50 border border-sky-200 p-4">
                <span className="font-bold text-sky-900 block mb-1">Pozitionare Tehnica & Factori de Evaluare</span>
                <p className="teeading-relaxed">{selectedLead.sales_pitch_angle}</p>
              </div>

              <div className="pt-2 space-y-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Actiuni Dosar</span>
                
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => handleSaveToPipeline(selectedLead)}
                    className="rounded-lg bg-slate-900 p-2.5 text-center text-xs font-semibold text-white hover:bg-slate-800 transition shadow-sm"
                  >
                    Salveaza in Pipeline
                  </button>

                  <button
                    onClick={() => handleSendEmailAlert(selectedLead)}
                    disabled={emailSending}
                    className="rounded-lg border border-slate-300 bg-white p-2.5 text-center text-xs font-semibold text-slate-700 hover:bg-slate-50 transition shadow-sm"
                  >
                    {emailSending ? "Se expediaza..." : emailSentSuccess ? "Alerta Trimisa" : "Trimite Alerta Email"}
                  </button>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-1">
                  <button onClick={() => setScannerOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Scanner Caiet
                  </button>
                  <button onClick={() => setWinModalOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Simulator Sanse
                  </button>
                  <button onClick={() => setClarificationOpen(true)} className="rounded-lg bg-slate-100 border border-slate-200 p-2 text-center text-[11px] font-semibold text-slate-800 hover:bg-slate-200">
                    Adresa Legea 544
                  </button>
                </div>
              </div>
            </div>
          </div>

          <a
            href={selectedLead.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-6 w-full rounded-xl bg-slate-900 py-2.5 text-center font-semibold text-xs text-white hover:bg-slate-800 transition block shadow-sm"
          >
            Acceseaza Documentul Oficial Sursa &rarr;
          </a>
        </div>
      )}

      {/* 4. MODALS */}
      <PricingModal isOpen={pricingOpen} onClose={() => setPricingOpen(false)} tenantId={activeDesk?.id || "desk_default"} />
      <BusinessEligibilityModal isOpen={businessScannerOpen} onClose={() => setBusinessScannerOpen(false)} />
      <CopilotChatModal isOpen={copilotOpen} onClose={() => setCopilotOpen(false)} tenantId={activeDesk?.id || "desk_default"} report72h={report72h} />
      <CaietScannerModal isOpen={scannerOpen} onClose={() => setScannerOpen(false)} defaultTitle={selectedLead?.project_title || ""} />
      <WinOddsModal isOpen={winModalOpen} onClose={() => setWinModalOpen(false)} defaultBudget={selectedLead?.financial_value_ron || 10000000} />
      <ClarificationModal isOpen={clarificationOpen} onClose={() => setClarificationOpen(false)} opp={selectedLead || {}} />
      <PipelineTrackerModal isOpen={pipelineOpen} onClose={() => setPipelineOpen(false)} tenantId={activeDesk?.id || "desk_default"} />
      <AccountSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <WorkspaceDeskModal isOpen={deskManagerOpen} onClose={() => setDeskManagerOpen(false)} />
    </div>
  );
}
""")

print("\n⚡ [2/4] Verifying Backend Python Compilation...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator; print('  [OK] Backend Python: 0 errors')"], cwd=ENGINE)
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [3/4] Running Next.js Frontend Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=FRONTEND)
if res_next.returncode != 0:
    print("❌ Frontend build failed.")
    sys.exit(1)

print("\n⚡ [4/4] Executing Direct Git Pushes to Trigger Vercel & Render...")

# Git push frontend (triggers Vercel)
run_cmd(["git", "add", "-A"], cwd=FRONTEND)
subprocess.run(["git", "commit", "-m", "feat: custom desk manager, clean logo without 2026/green dot, light theme"], cwd=FRONTEND)
run_cmd(["git", "push", "origin", "main"], cwd=FRONTEND)

# Git push backend (triggers Render)
run_cmd(["git", "add", "-A"], cwd=ENGINE)
subprocess.run(["git", "commit", "-m", "feat: dynamic desk routing and resend email engine"], cwd=ENGINE)
run_cmd(["git", "push", "origin", "main"], cwd=ENGINE)

# Git push parent repo
run_cmd(["git", "add", "-A"], cwd=ROOT)
subprocess.run(["git", "commit", "-m", "deploy: release custom business desk manager and clean UI"], cwd=ROOT)
run_cmd(["git", "push", "origin", "main"], cwd=ROOT)

print("\n🎉 [SUCCESS] Deployment completed! Vercel and Render builds triggered successfully.")
