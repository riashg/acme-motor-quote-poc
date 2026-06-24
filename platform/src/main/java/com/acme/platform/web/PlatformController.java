package com.acme.platform.web;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.acme.platform.events.ApiActivity;
import com.acme.platform.purchase.PurchaseLinkService;
import com.acme.platform.quote.DemoSeeder;
import com.acme.platform.quote.QuoteService;
import com.acme.platform.quote.QuoteService.PriceResult;
import com.acme.platform.quote.QuoteService.PurchaseResult;
import com.acme.platform.vendor.VendorClient;

/**
 * The platform's REST surface. Preserves the exact contract of the Python
 * platform so the unchanged MCP server, conversation backend, and dashboard
 * keep working.
 *
 * <p>Three-layer discipline: each route logs an {@code API_CALL} (request +
 * response) via {@link ApiActivity#record}, then the service mutates state and
 * appends a {@code QUOTE_*} domain event.
 */
@RestController
public class PlatformController {

    private final QuoteService quotes;
    private final VendorClient vendor;
    private final ApiActivity api;
    private final DemoSeeder demo;
    private final PurchaseLinkService purchaseLinks;
    private final String publicBaseUrl;

    public PlatformController(QuoteService quotes, VendorClient vendor, ApiActivity api, DemoSeeder demo,
                              PurchaseLinkService purchaseLinks,
                              @Value("${platform.public-base-url:http://localhost:8070}") String publicBaseUrl) {
        this.quotes = quotes;
        this.vendor = vendor;
        this.api = api;
        this.demo = demo;
        this.purchaseLinks = purchaseLinks;
        // Trim any trailing slash so purchaseUrl is well-formed.
        this.publicBaseUrl = publicBaseUrl.endsWith("/")
            ? publicBaseUrl.substring(0, publicBaseUrl.length() - 1)
            : publicBaseUrl;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "ok");
    }

    @PostMapping("/ping")
    public Map<String, Object> ping(@RequestBody(required = false) Map<String, Object> body) {
        Map<String, Object> request = body == null ? Map.of() : body;
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("pong", true);
        result.put("echo", request);

        // API layer: log request + response.
        api.record("ping", request, result);
        // Domain layer: mutate state (none yet) + append a domain event.
        // (Kept for three-layer parity with the Python platform.)
        return result;
    }

    /** Create a draft quote. Returns quoteId, sessionId, journeyState, missingFields. */
    @PostMapping("/quotes")
    public ResponseEntity<Map<String, Object>> postQuote() {
        Map<String, Object> result = quotes.createQuote(); // emits QUOTE_CREATED (domain)
        // API-layer log must not leak the sessionId beyond the creator.
        Map<String, Object> logged = new LinkedHashMap<>(result);
        logged.remove("sessionId");
        api.record("create_quote", Map.of(), logged);
        return ResponseEntity.status(HttpStatus.CREATED).body(result);
    }

    /** Retrieve a quote. Requires X-Session-Id; 404 on unknown id or mismatch. */
    @GetMapping("/quotes/{quoteId}")
    public Map<String, Object> getQuote(
        @PathVariable String quoteId,
        @RequestHeader(name = "X-Session-Id", required = false) String sessionId
    ) {
        if (DemoSeeder.DEMO_QUOTE_ID.equals(quoteId)) {
            // Self-seed the stable demo quote on first access (brief §9, §17.7).
            demo.ensureSeeded();
        }
        Map<String, Object> state = quotes.getQuote(quoteId, sessionId == null ? "" : sessionId);
        api.record("get_quote", Map.of("quoteId", quoteId), state != null ? state : Map.of("error", "not_found"));
        if (state == null) {
            // Do not reveal whether the quote exists.
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Quote not found");
        }
        return state;
    }

    /** Apply a partial patch. Body: {"patch": {...}}. 404 on mismatch. */
    @PatchMapping("/quotes/{quoteId}")
    public Map<String, Object> patchQuote(
        @PathVariable String quoteId,
        @RequestBody(required = false) Map<String, Object> body,
        @RequestHeader(name = "X-Session-Id", required = false) String sessionId
    ) {
        Object rawPatch = body == null ? null : body.get("patch");
        @SuppressWarnings("unchecked")
        Map<String, Object> patch = (rawPatch instanceof Map) ? (Map<String, Object>) rawPatch : Map.of();
        Map<String, Object> state = quotes.applyPatch(quoteId, sessionId == null ? "" : sessionId, patch);
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("quoteId", quoteId);
        req.put("patch", patch);
        api.record("update_quote", req, state != null ? state : Map.of("error", "not_found"));
        if (state == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Quote not found");
        }
        return state;
    }

    /**
     * Price a quote: rate (via the vendor SOAP seam) + underwrite (platform),
     * returning the brief §11 pricing object. Requires X-Session-Id; 404 on
     * unknown id or mismatch (same as other quote routes). 422 if mandatory
     * fields remain (can't price an incomplete quote).
     */
    @PostMapping("/quotes/{quoteId}/price")
    public ResponseEntity<Map<String, Object>> priceQuote(
        @PathVariable String quoteId,
        @RequestHeader(name = "X-Session-Id", required = false) String sessionId
    ) {
        if (DemoSeeder.DEMO_QUOTE_ID.equals(quoteId)) {
            demo.ensureSeeded();
        }
        PriceResult result = quotes.priceQuote(quoteId, sessionId == null ? "" : sessionId);

        Map<String, Object> response = switch (result.status()) {
            case NOT_FOUND -> Map.of("error", "not_found");
            case INCOMPLETE -> {
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("error", "not_ready_to_price");
                body.put("missingFields", result.state().get("missingFields"));
                yield body;
            }
            case PRICED -> result.pricing();
        };

        // API layer: log request + response (never the sessionId).
        api.record("price_quote", Map.of("quoteId", quoteId), response);

        return switch (result.status()) {
            case NOT_FOUND -> throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Quote not found");
            case INCOMPLETE -> ResponseEntity.unprocessableEntity().body(response);
            case PRICED -> ResponseEntity.ok(response);
        };
    }

    /**
     * Mint a purchase link for a cleanly-priced quote (Slice 7). Requires
     * X-Session-Id; 404 on unknown id or mismatch. 409 if the quote isn't
     * cleanly priced (outcome != quote) — can't purchase a refer/decline/unpriced
     * quote. On success returns {@code {purchaseToken, purchaseUrl}} where the URL
     * is {@code <publicBaseUrl>/purchase/<token>}; emits PURCHASE_LINK_GENERATED.
     */
    @PostMapping("/quotes/{quoteId}/purchase-link")
    public ResponseEntity<Map<String, Object>> purchaseLink(
        @PathVariable String quoteId,
        @RequestHeader(name = "X-Session-Id", required = false) String sessionId
    ) {
        if (DemoSeeder.DEMO_QUOTE_ID.equals(quoteId)) {
            demo.ensureSeeded();
        }
        PurchaseResult result = quotes.mintPurchaseLink(
            quoteId, sessionId == null ? "" : sessionId, purchaseLinks::mintToken);

        Map<String, Object> response = switch (result.status()) {
            case NOT_FOUND -> Map.of("error", "not_found");
            case NOT_QUOTE -> Map.of("error", "not_purchasable");
            case OK -> {
                String token = (String) result.value().get("purchaseToken");
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("purchaseToken", token);
                body.put("purchaseUrl", publicBaseUrl + "/purchase/" + token);
                yield body;
            }
        };

        // API layer: log request + response. Never the sessionId; the token is the
        // capability for the (separate) landing page, so it may appear in the API log.
        api.record("purchase_link", Map.of("quoteId", quoteId), response);

        return switch (result.status()) {
            case NOT_FOUND -> throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Quote not found");
            case NOT_QUOTE -> ResponseEntity.status(HttpStatus.CONFLICT).body(response);
            case OK -> ResponseEntity.ok(response);
        };
    }

    /**
     * Issue a (mock) policy for a cleanly-priced quote (Slice 8). Requires
     * X-Session-Id; 404 on unknown id or mismatch. 409 if the quote isn't cleanly
     * priced (outcome != quote). Issues via the vendor SOAP seam, stores the
     * policy on the quote, advances journeyState to {@code policy_issued}, emits
     * POLICY_CREATED, and returns the policy details. Real issuance/payments stay
     * out of scope (brief §2) — only the seam is visible.
     */
    @PostMapping("/quotes/{quoteId}/issue-policy")
    public ResponseEntity<Map<String, Object>> issuePolicy(
        @PathVariable String quoteId,
        @RequestHeader(name = "X-Session-Id", required = false) String sessionId
    ) {
        if (DemoSeeder.DEMO_QUOTE_ID.equals(quoteId)) {
            demo.ensureSeeded();
        }
        PurchaseResult result = quotes.issuePolicy(quoteId, sessionId == null ? "" : sessionId);

        Map<String, Object> response = switch (result.status()) {
            case NOT_FOUND -> Map.of("error", "not_found");
            case NOT_QUOTE -> Map.of("error", "not_issuable");
            case OK -> result.value();
        };

        api.record("issue_policy", Map.of("quoteId", quoteId), response);

        return switch (result.status()) {
            case NOT_FOUND -> throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Quote not found");
            case NOT_QUOTE -> ResponseEntity.status(HttpStatus.CONFLICT).body(response);
            case OK -> ResponseEntity.ok(response);
        };
    }

    /** Vehicle lookup via the vendor SOAP seam (no session required). */
    @GetMapping("/vehicles/{registration}")
    public Map<String, Object> lookupVehicle(@PathVariable String registration) {
        Map<String, Object> result = vendor.lookupVehicle(registration);
        api.record("lookup_vehicle", Map.of("registration", registration), result);
        if (result == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Vehicle not found");
        }
        return result;
    }

    /** Address candidates via the vendor SOAP seam (no session required). */
    @GetMapping("/addresses")
    public Map<String, Object> lookupAddress(@RequestParam String postcode) {
        List<Map<String, Object>> candidates = vendor.lookupAddress(postcode);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("postcode", postcode);
        result.put("candidates", candidates);
        api.record("lookup_address", Map.of("postcode", postcode), result);
        return result;
    }
}
