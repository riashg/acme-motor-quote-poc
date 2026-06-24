// Types mirror the conversation backend contract (backend/app/main.py).

export type JourneyState =
  | "collecting"
  | "ready_to_price"
  | "quoted"
  | "referred"
  | "declined"
  | "policy_issued"
  | string;

// POST /start -> {session_id, quoteId, journeyState, missingFields}
export interface StartResult {
  session_id: string;
  quoteId: string;
  journeyState: JourneyState;
  missingFields: string[];
}

// A conflict the backend surfaces when an extracted value clashes with a held one.
export interface Conflict {
  path: string;
  current: unknown;
  proposed: unknown;
  chips: unknown[];
  message: string;
}

// SSE events from POST /chat and POST /resolve.
export type ChatEvent =
  | { type: "echo"; data: string }
  | { type: "text"; data: string }
  | { type: "conflict"; data: Conflict }
  | { type: "done" };

// POST /upload (multipart) ->
// {extracted, applied, conflicts, echo, missingFields, journeyState, target}
export interface UploadResult {
  extracted: string[];
  applied: string[];
  conflicts: Conflict[];
  echo: string;
  missingFields: string[];
  journeyState: JourneyState | null;
  target: "applicant" | "named_driver" | string;
}

export interface BreakdownLine {
  label: string;
  amount: number;
}

export interface Monthly {
  deposit: number;
  instalment: number;
  instalments: number;
}

// The platform pricing object (brief §11) returned inside /price.
export interface Pricing {
  annualPremium?: number;
  currency?: string;
  iptIncluded?: boolean;
  monthly?: Monthly;
  compulsoryExcess?: number;
  voluntaryExcess?: number;
  totalExcess?: number;
  ncdYears?: number;
  outcome: "quote" | "refer" | "decline" | string;
  reasons?: string[];
  breakdown?: BreakdownLine[];
}

// POST /price (200) -> {pricing, explanation}
export interface PriceResult {
  pricing: Pricing;
  explanation: string;
}

// POST /price (422) -> {error:"not_ready_to_price", missingFields}
export interface NotReadyToPrice {
  error: "not_ready_to_price";
  missingFields: string[];
}

// POST /purchase -> {purchaseUrl}
export interface PurchaseResult {
  purchaseUrl: string;
}

// POST /issue-policy -> {policyNumber, status, effectiveDate}
export interface PolicyResult {
  policyNumber: string;
  status: string;
  effectiveDate: string;
}
