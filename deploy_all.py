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
    print(f"\n[EXEC] {' '.join(cmd)} in {os.path.relpath(cwd, ROOT) or '.'}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}")
        sys.exit(1)

print("\n⚡ [1/4] Writing Clean Frontend Files (Light Theme, No Emojis, No Auto-Login, Toolbar Refresh)...")

# 1. AUTH CONTEXT (NO AUTO-LOGIN, VISITORS ARE NULL/LOGGED OUT)
write_file(os.path.join(FRONTEND, "context/AuthContext.tsx"), """\"use client\";
import React, { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { syncBackendAuth, switchTenantWorkspace } from "@/lib/api";

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
  view_mode: "cards" | "compact";
}

interface AuthContextType {
  user: UserProfile | null;
  loading: boolean;
  preferences: UserPreferences;
  updatePreferences: (newPrefs: Partial<UserPreferences>) => void;
  activeTenant: string;
  setActiveTenant: (tenantId: string) => void;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
}

const DEFAULT_PREFERENCES: UserPreferences = {
  notification_email: "",
  auto_alert_score: 9.0,
  default_sort: "score_desc",
  view_mode: "cards"
};

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  preferences: DEFAULT_PREFERENCES,
  updatePreferences: () => {},
  activeTenant: "t1_infra_transilvania",
  setActiveTenant: () => {},
  signInWithGoogle: async () => {},
  signInWithEmail: async () => ({ error: null }),
  signOut: async () => {}
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTenant, setActiveTenantState] = useState("t1_infra_transilvania");
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedPrefs = localStorage.getItem("ro_intel_user_prefs");
      if (savedPrefs) {
        try { setPreferences(JSON.parse(savedPrefs)); } catch {}
      }
    }
  }, []);

  const updatePreferences = (newPrefs: Partial<UserPreferences>) => {
    setPreferences(prev => {
      const updated = { ...prev, ...newPrefs };
      if (typeof window !== "undefined") {
        localStorage.setItem("ro_intel_user_prefs", JSON.stringify(updated));
      }
      return updated;
    });
  };

  const setActiveTenant = (tenantId: string) => {
    setActiveTenantState(tenantId);
    switchTenantWorkspace(tenantId);
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
            setActiveTenantState(synced.user.tenant_id || "t1_infra_transilvania");
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
          setActiveTenantState(synced.user.tenant_id || "t1_infra_transilvania");
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
        redirectTo: `${typeof window !== "undefined" ? window.location.origin : ""}`
      }
    });
  };

  const signInWithEmail = async (email: string) => {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${typeof window !== "undefined" ? window.location.origin : ""}`
      }
    });
    return { error: error ? error.message : null };
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, preferences, updatePreferences, activeTenant, setActiveTenant, signInWithGoogle, signInWithEmail, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
""")

# 2. MAIN APP PAGE (LIGHT ENTERPRISE THEME, NO EMOJIS, TOOLBAR REFRESH BUTTON, FREEMIUM GATING)
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
  AccountSettingsModal
} from "../components/EnterpriseModals";

export default function DeskPage() {
  const { user, preferences } = useAuth();
  const [tenantId, setTenantId] = useState("t1_infra_transilvania");
  const [products, setProducts] = useState<any[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>("all");
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

  const tenantNames: Record<string, string> = {
    "t1_infra_transilvania": "SC Infra Construct Transilvania SRL",
    "t2_medtech_bucuresti": "SC MedTech Pharma SRL",
    "t3_vest_consulting_grants": "SC Vest Project Consulting"
  };

  const loadWorkspace = async (force = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);

    try {
      const prodData = await fetchTenantProducts(tenantId);
      setProducts(prodData?.products || []);

      const feedData = await fetchTenantFeed(tenantId, selectedProduct !== "all" ? selectedProduct : undefined, activeCategory, force);
      setLeads(feedData?.leads || []);

      const macroData = await fetch72hMarketReport(tenantId);
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
  }, [tenantId, activeCategory, selectedProduct]);

  const handleSaveToPipeline = async (lead: any) => {
    try {
      await addLeadToPipeline(tenantId, lead);
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

  const filteredLeads = leads.filter((l) => {
    const matchCounty = selectedCounty === "all" || l?.county?.toLowerCase() === selectedCounty.toLowerCase();
    const matchSearch =
      !searchQuery ||
      l?.project_title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.entity_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.locality?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      l?.sub_category?.toLowerCase().includes(searchQuery.toLowerCase());
    return matchCounty && matchSearch;
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
      {/* 1. TOP EXECUTIVE BAR */}
      <header className="h-16 border-b border-slate-200 bg-white px-6 flex items-center justify-between sticky top-0 z-30 shadow-sm">
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-600"></span>
            <span className="font-bold text-base tracking-wider text-slate-900 uppercase">
              RO-INTEL <span className="text-sky-700 text-[11px] font-semibold px-2 py-0.5 rounded bg-sky-50 border border-sky-200">2026</span>
            </span>
          </div>

          <div className="relative">
            <button
              onClick={() => setWorkspaceDropdownOpen(!workspaceDropdownOpen)}
              className="flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-800 hover:border-slate-400 hover:bg-white transition shadow-sm"
            >
              <span className="h-2 w-2 rounded-full bg-sky-600"></span>
              <span>{tenantNames[tenantId] || "Selecteaza Companie"}</span>
              <span className="text-[10px] text-slate-500 font-normal">▼</span>
            </button>

            {workspaceDropdownOpen && (
              <div className="absolute left-0 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-xl z-50 text-xs space-y-1">
                <span className="text-[10px] uppercase font-bold text-slate-400 px-2 py-1 block">Companie Activa</span>
                {Object.entries(tenantNames).map(([id, name]) => (
                  <button
                    key={id}
                    onClick={() => {
                      setTenantId(id);
                      setSelectedProduct("all");
                      setWorkspaceDropdownOpen(false);
                    }}
                    className={"w-full text-left rounded-lg px-2.5 py-2 transition flex items-center justify-between " + (tenantId === id ? "bg-sky-50 text-sky-800 font-bold border border-sky-200" : "text-slate-700 hover:bg-slate-100")}
                  >
                    <span className="truncate">{name}</span>
                    {tenantId === id && <span className="text-sky-700 text-xs font-bold">Activ</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

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

      {/* 2. MAIN BODY */}
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

            <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-2">Divizii Produs</span>
            <div className="space-y-1 mb-5">
              <button
                onClick={() => setSelectedProduct("all")}
                className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedProduct === "all" ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
              >
                Toate Liniile
              </button>
              {products.map((p) => (
                <button
                  key={p.product_id}
                  onClick={() => setSelectedProduct(p.product_id)}
                  className={"w-full text-left rounded-lg px-3 py-1.5 text-xs transition " + (selectedProduct === p.product_id ? "text-sky-700 font-bold" : "text-slate-600 hover:bg-slate-50")}
                >
                  {p.name}
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
          {/* SEARCH & REPOSITIONED REFRESH BUTTON TOOLBAR */}
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
                href={"https://api.ro-intel.xyz/api/v1/tenants/" + tenantId + "/export/csv"}
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
                <p className="text-slate-700 leading-relaxed">{selectedLead.sales_pitch_angle}</p>
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
      <PricingModal isOpen={pricingOpen} onClose={() => setPricingOpen(false)} tenantId={tenantId} />
      <BusinessEligibilityModal isOpen={businessScannerOpen} onClose={() => setBusinessScannerOpen(false)} />
      <CopilotChatModal isOpen={copilotOpen} onClose={() => setCopilotOpen(false)} tenantId={tenantId} report72h={report72h} />
      <CaietScannerModal isOpen={scannerOpen} onClose={() => setScannerOpen(false)} defaultTitle={selectedLead?.project_title || ""} />
      <WinOddsModal isOpen={winModalOpen} onClose={() => setWinModalOpen(false)} defaultBudget={selectedLead?.financial_value_ron || 10000000} />
      <ClarificationModal isOpen={clarificationOpen} onClose={() => setClarificationOpen(false)} opp={selectedLead || {}} />
      <PipelineTrackerModal isOpen={pipelineOpen} onClose={() => setPipelineOpen(false)} tenantId={tenantId} />
      <AccountSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
""")

print("\n⚡ [2/4] Verifying Python Backend Imports...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator; print('  [OK] Python Backend: 0 errors')"], cwd=ENGINE)
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [3/4] Running Next.js Frontend Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=FRONTEND)
if res_next.returncode != 0:
    print("❌ Frontend build failed.")
    sys.exit(1)

print("\n⚡ [4/4] Executing Direct Git Pushes for Vercel and Render...")

# Git push frontend (triggers Vercel)
run_cmd(["git", "add", "-A"], cwd=FRONTEND)
subprocess.run(["git", "commit", "-m", "feat: light enterprise palette, zero emojis, isolated toolbar refresh, and freemium gatekeeper"], cwd=FRONTEND)
run_cmd(["git", "push", "origin", "main"], cwd=FRONTEND)

# Git push backend (triggers Render)
run_cmd(["git", "add", "-A"], cwd=ENGINE)
subprocess.run(["git", "commit", "-m", "feat: resend api email dispatcher and 25-scraper matrix with live verified URLs"], cwd=ENGINE)
run_cmd(["git", "push", "origin", "main"], cwd=ENGINE)

# Git push parent repo
run_cmd(["git", "add", "-A"], cwd=ROOT)
subprocess.run(["git", "commit", "-m", "deploy: sync all submodules for production release"], cwd=ROOT)
run_cmd(["git", "push", "origin", "main"], cwd=ROOT)

print("\n🎉 [SUCCESS] All submodules built with 0 errors and pushed to Vercel & Render!")
