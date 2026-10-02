import { useEffect, useState } from "react";

export const UI = window.HomeEnergyUI;
export const t = UI.t.bind(UI);

export function useLanguage() {
  const [language, setLanguageState] = useState(UI.language);
  useEffect(() => {
    const update = () => setLanguageState(UI.language);
    window.addEventListener("languagechange", update);
    return () => window.removeEventListener("languagechange", update);
  }, []);
  return {
    language,
    setLanguage: (next: "zh-CN" | "en") => UI.setLanguage(next)
  };
}
