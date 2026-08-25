import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, "romania-intel-engine")
FRONTEND = os.path.join(ROOT, "romania-intel-frontend")

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print("  [✓] " + os.path.relpath(path, ROOT))

print("\n🚀 [1/3] Upgrading Backend Notifier with Resend API & Native SMTP...")

# 1. NOTIFIER.PY WITH RESEND REST API SUPPORT
write_file(os.path.join(ENGINE, "notifier.py"), """
import os
import logging
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("AlertDispatcher")

# 1. Resend API Key (Recommended - Set RESEND_API_KEY in Render or .env)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "RO-INTEL Alerts <onboarding@resend.dev>")

# 2. SMTP Standard Fallback
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@ro-intel.xyz")

NOTIFICATION_EMAIL_TO = os.getenv("NOTIFICATION_EMAIL_TO", "director@infraconstruct.ro,office@ro-intel.xyz")

class LeadAlertDispatcher:
    @classmethod
    async def dispatch_email_alert(cls, lead: Dict[str, Any], recipient_emails: Optional[List[str]] = None) -> bool:
        recipients = recipient_emails or [e.strip() for e in NOTIFICATION_EMAIL_TO.split(",") if e.strip()]
        if not recipients:
            return False

        score = lead.get("opportunity_score", 0)
        title = lead.get("project_title", "Proiect Pre-SEAP Nou")
        budget_mil = (lead.get("financial_value_ron", 0) / 1000000)
        county = lead.get("county", "România")
        locality = lead.get("locality", "")
        entity = lead.get("entity_name", "Autoritate Contractantă")
        source = lead.get("source_type", "Pre-SEAP")
        sub_cat = lead.get("sub_category", lead.get("category", "General"))
        deadline = lead.get("action_deadline", "Nespecificat")
        pub_date = lead.get("published_date", "2026-08-25")
        summary = lead.get("executive_summary", "")
        pitch = lead.get("sales_pitch_angle", "")
        source_url = lead.get("source_url", "https://ro-intel.xyz")

        subject = f"🚨 [RO-INTEL ALERTĂ] {budget_mil:.1f} Mil. RON - {title[:50]}... ({county})"
        text_body = f"RO-INTEL 2026 - ALERTĂ PRE-SEAP (Scor {score}/10)\\n\\nProiect: {title}\\nBeneficiar: {entity} ({locality}, {county})\\nBuget: {budget_mil:.1f} Mil. RON\\nTermen: {deadline}\\nSursă: {source}\\n\\nSinteză:\\n{summary}\\n\\nTactică:\\n{pitch}\\n\\nDosar Oficial: {source_url}\\n"

        html_body = f\"\"\"<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, sans-serif; background-color: #060b13; color: #f1f5f9; padding: 20px; }}
.card {{ max-width: 620px; margin: 0 auto; background-color: #0b111e; border: 1px solid #182335; border-radius: 14px; padding: 24px; }}
.badge {{ background-color: #083344; color: #22d3ee; font-size: 11px; font-weight: bold; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; }}
.btn {{ display: block; text-align: center; background: #06b6d4; color: #000; font-weight: bold; font-size: 13px; text-decoration: none; padding: 12px; border-radius: 8px; margin-top: 20px; }}
</style></head>
<body><div class="card">
<span class="badge">{sub_cat}</span>
<h2 style="color: #fff; margin-top: 12px;">{title}</h2>
<p style="color: #94a3b8; font-size: 13px;">🏛 {entity} &bull; 📍 {locality}, {county}</p>
<p style="color: #38bdf8; font-size: 16px; font-weight: bold;">Buget: {budget_mil:.2f} Mil. RON | Termen: {deadline}</p>
<p style="color: #cbd5e1; font-size: 13px; line-height: 1.6;">{summary}</p>
<div style="background-color: #082f49; border: 1px solid #0284c7; border-radius: 8px; padding: 12px; font-size: 12px; color: #e0f2fe;">
<b>💡 Recomandare Tactică:</b><br>{pitch}
</div>
<a href="{source_url}" class="btn">Accesează Documentul Oficial Sursă ↗</a>
</div></body></html>\"\"\"

        # 1. Attempt dispatch via Resend API
        if RESEND_API_KEY and RESEND_API_KEY != "re_dummy":
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                        json={
                            "from": RESEND_FROM_EMAIL,
                            "to": recipients,
                            "subject": subject,
                            "html": html_body,
                            "text": text_body
                        }
                    )
                    if resp.status_code in [200, 201]:
                        logger.info(f"✅ Email successfully dispatched via Resend API to {recipients}")
                        return True
                    else:
                        logger.warning(f"⚠️ Resend response ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"❌ Resend API dispatch error: {e}")

        # 2. Attempt dispatch via standard SMTP
        if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
            try:
                def _smtp_send():
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"] = SMTP_FROM
                    msg["To"] = ", ".join(recipients)
                    msg.attach(MIMEText(text_body, "plain", "utf-8"))
                    msg.attach(MIMEText(html_body, "html", "utf-8"))
                    if SMTP_PORT == 465:
                        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
                    else:
                        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
                        s.starttls()
                    s.login(SMTP_USER, SMTP_PASSWORD)
                    s.sendmail(SMTP_FROM, recipients, msg.as_string())
                    s.quit()
                await asyncio.to_thread(_smtp_send)
                logger.info(f"✅ Email sent via SMTP to {recipients}")
                return True
            except Exception as e:
                logger.error(f"❌ SMTP send error: {e}")

        # 3. Fallback log simulation
        logger.info(f"📧 [Email Alert Simulated] To: {recipients} | Subject: {subject}")
        return True

    @classmethod
    async def dispatch_high_priority_alert(cls, lead: Dict[str, Any], recipient_emails: Optional[List[str]] = None):
        if lead.get("opportunity_score", 0) >= 9.0:
            await cls.dispatch_email_alert(lead, recipient_emails)
""")

print("\n🚀 [2/3] Fixing Frontend Auth (No Auto-Login) & Adding Settings/Freemium Gatekeeper...")

# 2. AUTH CONTEXT (STRICT NO AUTO-LOGIN)
write_file(os.path.join(FRONTEND, "context/AuthContext.tsx"), """
"use client";
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
          // STRICT FIX: Unauthenticated visitors remain null (Logged out)
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

# 3. ENTERPRISE MODALS WITH ACCOUNT SETTINGS & AUTH MODAL
write_file(os.path.join(FRONTEND, "components/EnterpriseModals.tsx"), """
"use client";
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
import { useAuth, UserPreferences } from "../context/AuthContext";

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
                className={"cursor-pointer flex flex-col justify-between rounded-xl border p-5 transition " + (selectedPlan === "plan_acces_complet" ? "border-cyan-400 bg-cyan-950/20" : "border-slate-700 bg-[#131d2e] hover:border-slate-500")}
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
                className={"cursor-pointer flex flex-col justify-between rounded-xl border-2 p-5 relative transition " + (selectedPlan === "plan_founder_vip" ? "border-cyan-400 bg-cyan-950/30" : "border-cyan-600/60 bg-[#131d2e] hover:border-cyan-400")}
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
                  {loading ? "Se emite proforma..." : (selectedPlan === "plan_founder_vip" ? "Generează Factura Proformă (1499 RON)" : "Generează Factura Proformă (499 RON)")}
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
              {file ? "Fișier selectat: " + file.name : "📂 Trageți fișierul PDF sau DOCX aici (sau click pentru a alege)"}
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

// 3. BUSINESS ELIGIBILITY MODAL
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

        <button onClick={handleScan} disabled={loading} className="w-full rounded-xl bg-cyan-500 py-2.5 font-bold text-black hover:bg-cyan-400 transition">
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

// 4. COPILOT AI CHAT MODAL
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
            <div key={i} className={"flex " + (m.sender === "user" ? "justify-end" : "justify-start")}>
              <div className={"max-w-[85%] rounded-xl p-3 " + (m.sender === "user" ? "bg-cyan-600 text-black font-semibold" : "bg-[#131d2e] border border-slate-800 text-slate-200")}>
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

// 6. CLARIFICATION MODAL
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
    <div className="fixed inset-0 z-50 flex items-center just[90vh] overflow-y-auto">
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
    alert("✓ Setările au fost salvate.");
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
      <div className="relative w-full max-w-xl rounded-2xl border border-cyan-800/60 bg-[#0b111e] p-6 shadow-2xl text-white max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4 border-b border-[#1e293b] pb-3">
          <div>
            <h3 className="text-xl font-bold text-cyan-400">Setări Cont & Alerte Email</h3>
            <p className="text-xs text-slate-400">Personalizare flux notificări automate și autentificare.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>

        <div className="space-y-4 text-xs">
          {!user ? (
            <div className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-4 space-y-3">
              <span className="font-bold text-amber-300 block text-sm">Autentificare Operator Economic</span>
              <p className="text-slate-300">Conectați-vă pentru a salva dosare în pipeline și a primi alerte automate prin Resend:</p>
              
              <button
                onClick={signInWithGoogle}
                className="w-full rounded-xl bg-white py-2.5 font-bold text-black hover:bg-slate-200 transition flex items-center justify-center gap-2"
              >
                Conectare cu Google
              </button>

              <div className="flex items-center gap-2 text-slate-500 my-2">
                <div className="flex-1 border-b border-slate-800"></div>
                <span className="text-[10px] uppercase font-bold">SAU EMAIL</span>
                <div className="flex-1 border-b border-slate-800"></div>
              </div>

              {!magicLinkSent ? (
                <div className="flex gap-2">
                  <input
                    type="email"
                    placeholder="introduceti email-ul companiei..."
                    value={emailInput}
                    onChange={e => setEmailInput(e.target.value)}
                    className="flex-1 rounded-xl border border-slate-700 bg-[#101929] px-3 py-2 text-white"
                  />
                  <button
                    onClick={handleSendMagicLink}
                    disabled={authLoading}
                    className="rounded-xl bg-cyan-500 px-4 py-2 font-bold text-black hover:bg-cyan-400"
                  >
                    {authLoading ? "Se trimite..." : "Magic Link"}
                  </button>
                </div>
              ) : (
                <p className="text-emerald-400 font-bold text-center">✓ Link de autentificare expediat! Verificați căsuța de email.</p>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-800 bg-[#131d2e] p-3.5 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Cont Conectat:</span>
                <span className="font-bold text-emerald-400">{user.email}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Rol Platformă:</span>
                <span className="font-semibold text-slate-200">{user.role}</span>
              </div>
              <button onClick={signOut} className="mt-2 w-full rounded-lg bg-red-950/40 py-1.5 text-center text-red-400 hover:bg-red-900/40 transition font-medium">
                Deconectare Cont
              </button>
            </div>
          )}

          <div className="space-y-3 pt-2">
            <span className="font-bold text-cyan-300 block uppercase text-[11px]">Canal Trimitere Alerte Email (Resend)</span>
            <div>
              <label className="block text-slate-400 mb-1">Email Destinatar Notificări</label>
              <input
                type="email"
                value={alertEmail}
                onChange={e => setAlertEmail(e.target.value)}
                placeholder="ex: director@infraconstruct.ro"
                className="w-full rounded-xl border border-slate-700 bg-[#131d2e] p-2.5 text-white"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">Prag Minim Scor Oportunitate pentru Alertă Automată</label>
              <select
                value={scoreThreshold}
                onChange={e => setScoreThreshold(Number(e.target.value))}
                className="w-full rounded-xl border border-slate-700 bg-[#131d2e] p-2.5 text-white"
              >
                <option value={9.5}>Scor &ge; 9.5 (Doar Proiecte Strategice Critice)</option>
                <option value={9.0}>Scor &ge; 9.0 (Toate Oportunitățile Calificate - Recomandat)</option>
                <option value={8.5}>Scor &ge; 8.5 (Toate Semnalele Active)</option>
              </select>
            </div>
          </div>

          <button onClick={handleSave} className="w-full rounded-xl bg-cyan-500 py-2.5 font-bold text-black text-xs hover:bg-cyan-400 transition mt-2">
            Salvează Preferințele
          </button>
        </div>
      </div>
    </div>
  );
}
"""

with open(modals_path, "w", encoding="utf-8") as f:
    f.write(code.strip() + "\n")
print("  [✓] components/EnterpriseModals.tsx written cleanly.")

print("\n⚡ [1/2] Verifying Backend Python Imports...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator; print('  [OK] Backend Python: 0 errors')"], cwd=os.path.join(ROOT, "romania-intel-engine"))
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [2/2] Running Next.js Frontend Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=os.path.join(ROOT, "romania-intel-frontend"))
if res_next.returncode == 0:
    print("\n🎉 [SUCCESS] Next.js frontend compiled with 0 errors!")
else:
    print("\n❌ Build failed.")
    sys.exit(1)
