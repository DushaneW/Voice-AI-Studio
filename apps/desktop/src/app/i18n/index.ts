import { en } from "./en";
import { pl } from "./pl";

export { en, pl };
export type Key = keyof typeof en;
export type Language = "en" | "pl";

export function translator(language: Language) {
  return (key: Key): string => (language === "pl" ? pl : en)[key];
}

export function errorMessage(error: unknown, language: Language): string {
  const code = String(error instanceof Error ? error.message : error).replace(
    /^Error: /,
    "",
  );
  return translator(language)(code in en ? (code as Key) : "unknownError");
}
