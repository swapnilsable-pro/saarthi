import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/* Viewer preferences: language (English / Hindi labels) and Simple / Pro detail level.
   Stored per browser; the app renders correctly when storage is unavailable. */
export type Lang = "en" | "hi";

const HI: Record<string, string> = {
  Today: "आज", Ideas: "आइडिया", "Paper Desk": "पेपर डेस्क", History: "इतिहास", Performance: "प्रदर्शन",
  Replay: "रीप्ले", Learn: "सीखें", "Demo data": "डेमो डेटा", "Live data": "लाइव डेटा",
  "PAPER MODE · no real orders": "पेपर मोड · कोई असली ऑर्डर नहीं", Simple: "सरल", Pro: "विस्तार",
  "Market mood": "बाज़ार का मूड", "Event risk": "इवेंट जोखिम", Watchlist: "वॉचलिस्ट",
  "Sectors and breadth": "सेक्टर और ब्रेड्थ", "Bulk & block deals": "बल्क और ब्लॉक डील", "Exchange filings": "एक्सचेंज फाइलिंग",
  Go: "आगे बढ़ें", Caution: "सावधानी", "Stand aside": "दूर रहें", Unknown: "अज्ञात",
  TAKE: "लें", WATCH: "देखें", SKIP: "छोड़ें", "The plan": "योजना", "Evidence checklist": "सबूत की सूची",
  "In plain English": "आसान भाषा में", "Paper trade ▶": "पेपर ट्रेड ▶", "Scan for breakouts": "ब्रेकआउट खोजें",
  "Evening scan": "शाम का स्कैन", "Pre-market brief": "प्री-मार्केट ब्रीफ", Run: "चलाएं",
  "Place PAPER order": "पेपर ऑर्डर दें", "Order ticket": "ऑर्डर टिकट",
};

interface Prefs { lang: Lang; pro: boolean; setLang: (l: Lang) => void; setPro: (p: boolean) => void; t: (s: string) => string }
const Ctx = createContext<Prefs>({ lang: "en", pro: false, setLang: () => {}, setPro: () => {}, t: (s) => s });

function read<T>(k: string, d: T): T {
  try { const v = localStorage.getItem(k); return v === null ? d : (JSON.parse(v) as T); } catch { return d; }
}
function write(k: string, v: unknown) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ }
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(() => read("saarthi.lang", "en"));
  const [pro, setPro] = useState<boolean>(() => read("saarthi.pro", false));
  useEffect(() => { write("saarthi.lang", lang); document.documentElement.lang = lang; }, [lang]);
  useEffect(() => write("saarthi.pro", pro), [pro]);
  const t = (s: string) => (lang === "hi" ? HI[s] ?? s : s);
  return <Ctx.Provider value={{ lang, pro, setLang, setPro, t }}>{children}</Ctx.Provider>;
}

export const usePrefs = () => useContext(Ctx);

/** Renders children only in Pro mode (raw evidence, plan variants, score maths). */
export function ProOnly({ children }: { children: ReactNode }) {
  return usePrefs().pro ? <>{children}</> : null;
}

export const onboarding = {
  seen: () => read("saarthi.onboarded", false),
  done: () => write("saarthi.onboarded", true),
  reset: () => write("saarthi.onboarded", false),
};
