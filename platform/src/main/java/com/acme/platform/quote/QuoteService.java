package com.acme.platform.quote;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.acme.platform.events.EventStore;
import com.acme.platform.pricing.PricingService;
import com.acme.platform.vendor.PolicyResult;
import com.acme.platform.vendor.VendorClient;

/**
 * Quote service — session-scoped create / get / update (brief §6, §9, §17.4).
 *
 * <p>The backend owns the journey: it stores quote state keyed to a
 * strong-entropy session id, deep-merges partial greedy patches (never blanking
 * siblings), recomputes {@code missingFields} and {@code journeyState}
 * server-side, and emits domain events so the dashboard and audit trail come
 * for free (three-layer discipline).
 *
 * <p>State shape returned to callers (brief §6):
 * {@code {quoteId, journeyState, missingFields, currentOutcome}}.
 * {@code sessionId} is returned <b>only at creation</b> — never by get/patch.
 */
@Service
public class QuoteService {

    /** The clean-quote outcome: only a quote with this outcome can be purchased / issued. */
    static final String OUTCOME_QUOTE = "quote";

    private final SessionStore sessions;
    private final EventStore events;
    private final PricingService pricing;
    private final VendorClient vendor;

    public QuoteService(SessionStore sessions, EventStore events, PricingService pricing, VendorClient vendor) {
        this.sessions = sessions;
        this.events = events;
        this.pricing = pricing;
        this.vendor = vendor;
    }

    /** Create a draft quote bound to a fresh session. Emits {@code QUOTE_CREATED}. */
    public Map<String, Object> createQuote() {
        QuoteRecord record = sessions.create();
        events.append("QUOTE_CREATED", Map.of("quoteId", record.quoteId()), "domain");
        Map<String, Object> state = state(record);
        // sessionId is returned only here, at creation.
        state.put("sessionId", record.sessionId());
        return state;
    }

    /** Return the state for {@code quoteId} iff {@code sessionId} matches; else {@code null}. */
    public Map<String, Object> getQuote(String quoteId, String sessionId) {
        QuoteRecord record = sessions.get(quoteId, sessionId);
        if (record == null) {
            return null;
        }
        return state(record);
    }

    /**
     * Deep-merge {@code patch} into the quote; recompute state; emit
     * {@code QUOTE_UPDATED}. Returns {@code null} on unknown quote or session
     * mismatch (treated as not-found).
     */
    public Map<String, Object> applyPatch(String quoteId, String sessionId, Map<String, Object> patch) {
        QuoteRecord record = sessions.get(quoteId, sessionId);
        if (record == null) {
            return null;
        }
        deepMerge(record.data(), patch == null ? Map.of() : patch);
        events.append("QUOTE_UPDATED", Map.of("quoteId", record.quoteId()), "domain");
        return state(record);
    }

    /** Outcome of a price request: {@code NOT_FOUND}, {@code INCOMPLETE}, or {@code PRICED}. */
    public enum PriceStatus { NOT_FOUND, INCOMPLETE, PRICED }

    /**
     * Result of {@link #priceQuote}: the status, the state object (for
     * {@code PRICED}/{@code INCOMPLETE}), and the standalone pricing object
     * (for {@code PRICED}).
     */
    public record PriceResult(PriceStatus status, Map<String, Object> state, Map<String, Object> pricing) {
    }

    /**
     * Price a quote (Slice 5): session-gated, requires completeness, then rates
     * via the vendor seam and underwrites on the platform. Writes the pricing
     * object and {@code currentOutcome} into the quote, sets {@code journeyState}
     * to {@code quoted}/{@code referred}/{@code declined}, and emits
     * {@code QUOTE_PRICED} (payload: {@code quoteId} + {@code outcome}, never the
     * sessionId).
     *
     * <ul>
     *   <li>Unknown quote or session mismatch → {@code NOT_FOUND}.</li>
     *   <li>Mandatory fields still missing → {@code INCOMPLETE} (can't price an
     *       incomplete quote); the state carries the remaining {@code missingFields}.</li>
     *   <li>Otherwise → {@code PRICED} with the full state + pricing object.</li>
     * </ul>
     */
    public PriceResult priceQuote(String quoteId, String sessionId) {
        QuoteRecord record = sessions.get(quoteId, sessionId);
        if (record == null) {
            return new PriceResult(PriceStatus.NOT_FOUND, null, null);
        }
        List<String> missing = RequiredFields.missingFields(record.data());
        if (!missing.isEmpty()) {
            // Can't price an incomplete quote — surface what remains.
            return new PriceResult(PriceStatus.INCOMPLETE, state(record), null);
        }

        Map<String, Object> pricingObject = pricing.price(record.data());
        String outcome = (String) pricingObject.get("outcome");

        // Persist into the quote so GET /quotes/{id} reflects the priced state.
        record.data().put("pricing", pricingObject);
        record.data().put("currentOutcome", outcome);

        // Domain event: quoteId + outcome only (never the sessionId).
        Map<String, Object> eventPayload = new LinkedHashMap<>();
        eventPayload.put("quoteId", record.quoteId());
        eventPayload.put("outcome", outcome);
        events.append("QUOTE_PRICED", eventPayload, "domain");

        return new PriceResult(PriceStatus.PRICED, state(record), pricingObject);
    }

    /**
     * Status of a purchase / issuance request:
     * <ul>
     *   <li>{@code NOT_FOUND} — unknown quote or session mismatch.</li>
     *   <li>{@code NOT_QUOTE} — the quote isn't cleanly priced (outcome != quote),
     *       so it can't be purchased / issued.</li>
     *   <li>{@code OK} — proceeded.</li>
     * </ul>
     */
    public enum PurchaseStatus { NOT_FOUND, NOT_QUOTE, OK }

    /** Result of {@link #mintPurchaseLink} / {@link #issuePolicy}: status + a value map. */
    public record PurchaseResult(PurchaseStatus status, Map<String, Object> value) {
    }

    /**
     * Mint a purchase token for a <b>cleanly-priced</b> quote (Slice 7):
     * session-gated, and only if {@code currentOutcome == quote}. Stores
     * {@code token → quoteId} via the supplied {@code tokenMinter} and emits
     * {@code PURCHASE_LINK_GENERATED} ({@code quoteId} only — no token, no
     * sessionId).
     *
     * <ul>
     *   <li>Unknown quote or session mismatch → {@code NOT_FOUND}.</li>
     *   <li>Not cleanly priced (outcome != quote) → {@code NOT_QUOTE}.</li>
     *   <li>Otherwise → {@code OK} with {@code {purchaseToken}} in the value map.</li>
     * </ul>
     *
     * @param tokenMinter mints + stores a token for the quoteId (the capability)
     */
    public PurchaseResult mintPurchaseLink(String quoteId, String sessionId,
                                           java.util.function.Function<String, String> tokenMinter) {
        QuoteRecord record = sessions.get(quoteId, sessionId);
        if (record == null) {
            return new PurchaseResult(PurchaseStatus.NOT_FOUND, null);
        }
        if (!isCleanlyPriced(record.data())) {
            return new PurchaseResult(PurchaseStatus.NOT_QUOTE, null);
        }
        String token = tokenMinter.apply(record.quoteId());
        events.append("PURCHASE_LINK_GENERATED", Map.of("quoteId", record.quoteId()), "domain");
        return new PurchaseResult(PurchaseStatus.OK, Map.of("purchaseToken", token));
    }

    /**
     * Issue a (mock) policy for a <b>cleanly-priced</b> quote (Slice 8):
     * session-gated, and only if {@code currentOutcome == quote}. Issues via the
     * vendor SOAP seam ({@link VendorClient#issuePolicy}), stores the policy on
     * the quote under {@code policy}, advances {@code journeyState} to
     * {@code policy_issued}, and emits {@code POLICY_CREATED}
     * ({@code quoteId} + {@code policyNumber} — no sessionId).
     *
     * <ul>
     *   <li>Unknown quote or session mismatch → {@code NOT_FOUND}.</li>
     *   <li>Not cleanly priced (outcome != quote) → {@code NOT_QUOTE}.</li>
     *   <li>Otherwise → {@code OK} with the policy {@code {policyNumber, status,
     *       effectiveDate}} in the value map.</li>
     * </ul>
     */
    public PurchaseResult issuePolicy(String quoteId, String sessionId) {
        QuoteRecord record = sessions.get(quoteId, sessionId);
        if (record == null) {
            return new PurchaseResult(PurchaseStatus.NOT_FOUND, null);
        }
        if (!isCleanlyPriced(record.data())) {
            return new PurchaseResult(PurchaseStatus.NOT_QUOTE, null);
        }

        // Issuance is a value obtained from the vendor over SOAP (mock here).
        PolicyResult policy = vendor.issuePolicy(record.data());

        Map<String, Object> policySection = new LinkedHashMap<>();
        policySection.put("policyNumber", policy.policyNumber());
        policySection.put("status", policy.status());
        policySection.put("effectiveDate", policy.effectiveDate());

        // Persist onto the quote + advance the journey to policy_issued.
        record.data().put("policy", policySection);
        record.data().put("policyIssued", true);

        Map<String, Object> eventPayload = new LinkedHashMap<>();
        eventPayload.put("quoteId", record.quoteId());
        eventPayload.put("policyNumber", policy.policyNumber());
        events.append("POLICY_CREATED", eventPayload, "domain");

        return new PurchaseResult(PurchaseStatus.OK, policySection);
    }

    /**
     * Landing-page view for the strict GUID landing page (Slice 7, brief §17.6):
     * resolve <b>only</b> the quoteId — no session, no ambient fallback — and
     * return the rendered fields <b>only if</b> the quote exists AND is cleanly
     * priced ({@code outcome == quote}); otherwise {@code null} ("Quote not
     * found"). Returns just what the page renders: vehicle, premium, monthly,
     * excess, outcome.
     */
    public Map<String, Object> landingView(String quoteId) {
        QuoteRecord record = sessions.lookup(quoteId);
        if (record == null || !isCleanlyPriced(record.data())) {
            return null;
        }
        Map<String, Object> data = record.data();
        @SuppressWarnings("unchecked")
        Map<String, Object> pricing = (data.get("pricing") instanceof Map)
            ? (Map<String, Object>) data.get("pricing") : Map.of();
        @SuppressWarnings("unchecked")
        Map<String, Object> vehicle = (data.get("vehicle") instanceof Map)
            ? (Map<String, Object>) data.get("vehicle") : Map.of();

        Map<String, Object> view = new LinkedHashMap<>();
        view.put("quoteId", record.quoteId());
        view.put("vehicle", vehicle);
        view.put("annualPremium", pricing.get("annualPremium"));
        view.put("currency", pricing.get("currency"));
        view.put("monthly", pricing.get("monthly"));
        view.put("totalExcess", pricing.get("totalExcess"));
        view.put("outcome", data.get("currentOutcome"));
        return view;
    }

    /** A quote is cleanly priced iff its {@code currentOutcome} is {@code quote}. */
    private static boolean isCleanlyPriced(Map<String, Object> data) {
        return data != null && OUTCOME_QUOTE.equals(data.get("currentOutcome"));
    }

    /** Build the brief §6 state object. Never includes the sessionId. */
    private Map<String, Object> state(QuoteRecord record) {
        Map<String, Object> data = record.data();
        List<String> missing = RequiredFields.missingFields(data);
        String currentOutcome = (String) data.get("currentOutcome");
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("quoteId", record.quoteId());
        state.put("journeyState", journeyState(data, missing, currentOutcome));
        state.put("missingFields", missing);
        state.put("currentOutcome", currentOutcome);
        // Surface the priced pricing object (if any) so GET /quotes/{id} shows it.
        Object pricingObject = data.get("pricing");
        if (pricingObject != null) {
            state.put("pricing", pricingObject);
        }
        // Surface the issued policy (if any) so GET /quotes/{id} reflects it.
        Object policy = data.get("policy");
        if (policy != null) {
            state.put("policy", policy);
        }
        return state;
    }

    /**
     * Derive the journey state (brief §6):
     * {@code quote_started} (nothing collected) →
     * {@code collecting} (some data, gaps) →
     * {@code ready_to_price} (no mandatory fields remain) →
     * {@code quoted}/{@code referred}/{@code declined} (priced, from the outcome) →
     * {@code policy_issued} (a mock policy has been issued, Slice 8).
     */
    private static String journeyState(Map<String, Object> data, List<String> missing, String currentOutcome) {
        // Once a (mock) policy is issued the journey is complete (Slice 8).
        if (data != null && Boolean.TRUE.equals(data.get("policyIssued"))) {
            return "policy_issued";
        }
        if (currentOutcome != null) {
            return PricingService.journeyStateFor(currentOutcome);
        }
        if (missing.isEmpty()) {
            return "ready_to_price";
        }
        if (data == null || data.isEmpty()) {
            return "quote_started";
        }
        return "collecting";
    }

    /**
     * Deep-merge {@code patch} into {@code base} in place (brief §17.4).
     *
     * <ul>
     *   <li>Nested maps merge recursively, so a greedy patch touching one leaf
     *       never blanks its siblings.</li>
     *   <li>Null / empty-string leaves in the patch are dropped (never used to
     *       blank existing data).</li>
     *   <li>Lists (e.g. {@code namedDrivers}) replace wholesale.</li>
     * </ul>
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> deepMerge(Map<String, Object> base, Map<String, Object> patch) {
        for (Map.Entry<String, Object> entry : patch.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();
            if (value instanceof Map<?, ?> patchMap) {
                Object existing = base.get(key);
                Map<String, Object> target = (existing instanceof Map)
                    ? (Map<String, Object>) existing
                    : new LinkedHashMap<>();
                Map<String, Object> merged = deepMerge(target, (Map<String, Object>) patchMap);
                // Only set if the merge produced something (avoid blank sub-objects).
                if (!merged.isEmpty()) {
                    base.put(key, merged);
                }
            } else if (isEmptyLeaf(value)) {
                // Drop — never blank an existing value with null/empty.
            } else {
                base.put(key, value);
            }
        }
        return base;
    }

    /** Null/empty leaves are dropped before merging (brief §17.4). */
    private static boolean isEmptyLeaf(Object value) {
        if (value == null) {
            return true;
        }
        return value instanceof String s && s.strip().isEmpty();
    }
}
