package com.acme.platform.web;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import com.acme.platform.purchase.PurchaseLinkService;
import com.acme.platform.quote.QuoteService;

/**
 * The <b>strict GUID-addressed purchase/quote landing page</b> (Slice 7,
 * brief §17.6). This is a <b>mock</b> purchase/quote landing page — synthetic,
 * no real brand.
 *
 * <p>It resolves <b>only</b> the high-entropy purchase token in the URL:
 * token → quoteId (via {@link PurchaseLinkService}), then renders the quote
 * <b>only if</b> the token resolves AND the quote exists AND is cleanly priced
 * ({@code outcome == quote}). Otherwise it returns <b>404</b> with a clean
 * "Quote not found" page. There is <b>no session, and no ambient/local
 * fallback</b> — possession of the token is the sole capability. Every
 * interpolated value is HTML-escaped.
 */
@RestController
public class LandingController {

    private final PurchaseLinkService purchaseLinks;
    private final QuoteService quotes;

    public LandingController(PurchaseLinkService purchaseLinks, QuoteService quotes) {
        this.purchaseLinks = purchaseLinks;
        this.quotes = quotes;
    }

    @GetMapping(value = "/purchase/{token}", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> landing(@PathVariable String token) {
        // Resolve ONLY the token in the URL — no session, no ambient fallback.
        String quoteId = purchaseLinks.resolve(token);
        Map<String, Object> view = quoteId == null ? null : quotes.landingView(quoteId);

        if (view == null) {
            // Clean "Quote not found" — never reveal whether the token/quote exists.
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .contentType(MediaType.TEXT_HTML)
                .body(notFoundPage());
        }
        return ResponseEntity.ok()
            .contentType(MediaType.TEXT_HTML)
            .body(quotePage(view));
    }

    @SuppressWarnings("unchecked")
    private static String quotePage(Map<String, Object> view) {
        Map<String, Object> vehicle = (view.get("vehicle") instanceof Map)
            ? (Map<String, Object>) view.get("vehicle") : Map.of();
        Map<String, Object> monthly = (view.get("monthly") instanceof Map)
            ? (Map<String, Object>) view.get("monthly") : Map.of();

        String currency = str(view.get("currency"));
        String vehicleDesc = (str(vehicle.get("make")) + " " + str(vehicle.get("model")) + " "
            + str(vehicle.get("derivative"))).strip();
        String registration = str(vehicle.get("registration"));
        String annual = currency + " " + str(view.get("annualPremium"));
        String monthlyAmount = monthly.get("instalment") == null
            ? "" : currency + " " + str(monthly.get("instalment")) + " x " + str(monthly.get("instalments"));
        String excess = currency + " " + str(view.get("totalExcess"));
        String outcome = str(view.get("outcome"));

        StringBuilder sb = new StringBuilder();
        sb.append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">")
          .append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
          .append("<title>Your motor quote</title>")
          .append("<style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:3rem auto;padding:0 1rem;color:#1a1a1a}")
          .append("h1{font-size:1.4rem}.card{border:1px solid #ddd;border-radius:8px;padding:1.5rem;margin-top:1rem}")
          .append("dt{font-weight:600;margin-top:.75rem}.premium{font-size:2rem;font-weight:700}")
          .append(".note{color:#666;font-size:.85rem;margin-top:2rem}</style></head><body>");
        sb.append("<h1>Your motor insurance quote</h1>");
        sb.append("<p class=\"note\">This is a synthetic mock landing page for a proof of concept. No real brand or data.</p>");
        sb.append("<div class=\"card\">");
        sb.append("<dl>");
        sb.append("<dt>Vehicle</dt><dd>").append(esc(vehicleDesc.isEmpty() ? "—" : vehicleDesc)).append("</dd>");
        if (!registration.isEmpty()) {
            sb.append("<dt>Registration</dt><dd>").append(esc(registration)).append("</dd>");
        }
        sb.append("<dt>Annual premium</dt><dd class=\"premium\">").append(esc(annual)).append("</dd>");
        if (!monthlyAmount.isBlank()) {
            sb.append("<dt>Monthly</dt><dd>").append(esc(monthlyAmount)).append("</dd>");
        }
        sb.append("<dt>Total excess</dt><dd>").append(esc(excess)).append("</dd>");
        sb.append("<dt>Outcome</dt><dd>").append(esc(outcome)).append("</dd>");
        sb.append("</dl></div>");
        sb.append("</body></html>");
        return sb.toString();
    }

    private static String notFoundPage() {
        return "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            + "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            + "<title>Quote not found</title>"
            + "<style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:3rem auto;"
            + "padding:0 1rem;color:#1a1a1a}h1{font-size:1.4rem}.note{color:#666}</style></head><body>"
            + "<h1>Quote not found</h1>"
            + "<p class=\"note\">This link is invalid or has expired, or the quote is not available to view.</p>"
            + "</body></html>";
    }

    private static String str(Object value) {
        return value == null ? "" : value.toString();
    }

    /** HTML-escape an interpolated value (defends against any injected markup). */
    private static String esc(String s) {
        if (s == null) {
            return "";
        }
        StringBuilder out = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '&' -> out.append("&amp;");
                case '<' -> out.append("&lt;");
                case '>' -> out.append("&gt;");
                case '"' -> out.append("&quot;");
                case '\'' -> out.append("&#39;");
                default -> out.append(c);
            }
        }
        return out.toString();
    }
}
