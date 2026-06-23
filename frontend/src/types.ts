// A candidate is the country-specific submit shape produced by the backend
// just before confirmation. GB candidates carry cover_tier/voluntary_excess and
// a GB driver shape; FR candidates carry formule/franchise and an FR driver shape.
export interface Candidate {
  vehicle: Record<string, unknown>;
  driver: Record<string, unknown>;
  cover_tier?: string;
  voluntary_excess?: number;
  formule?: string;
  franchise?: number;
}

export interface ChatEvent {
  type: "text" | "confirm" | "done";
  data?: string | Candidate;
}

export interface Quote {
  quote_ref: string;
  currency: string;
  annual_premium: number;
  monthly_premium: number;
  country_code: string;
  input: Record<string, unknown>;
}

export interface ConfirmResult {
  quote: Quote;
  handoff_url: string;
  guid: string;
}

export interface UploadResult {
  country_code: string;
  fields: Record<string, unknown>;
  schema: Record<string, unknown>;
}
