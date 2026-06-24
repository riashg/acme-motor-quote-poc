package com.acme.platform.pricing;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.acme.platform.vendor.QuoteValues;
import com.acme.platform.vendor.RatingResult;

/**
 * Platform-owned underwriting (brief §15). Given the quote data and the
 * vendor's {@link RatingResult}, decide whether to {@code quote}, {@code refer}
 * to a human, or {@code decline} — and say why.
 *
 * <p>This is the hard line of [§3]: the <b>premium</b> comes from the vendor
 * seam ({@code VendorClient.rate}); the <b>decision</b> is the insurer's risk
 * policy and lives here, never behind the seam.
 *
 * <p>Rules (deliberately simple and transparent):
 * <ul>
 *   <li><b>Decline</b> (checked first — most restrictive): driver under 18; or
 *       an unsupported vehicle (mock flag {@code vehicle.supported == false}).</li>
 *   <li><b>Refer</b>: vehicle value &gt; £75,000; or more than 3 claims; or more
 *       than 2 convictions.</li>
 *   <li>Otherwise <b>quote</b>.</li>
 * </ul>
 */
@Component
public class UnderwritingEngine {

    static final int VALUE_REFER_THRESHOLD = 75_000;   // £ — refer above this
    static final int CLAIMS_REFER_THRESHOLD = 3;       // refer when claims > this
    static final int CONVICTIONS_REFER_THRESHOLD = 2;  // refer when convictions > this
    static final int MIN_DRIVER_AGE = 18;              // decline below this

    /**
     * Assess a quote. {@code ratingResult} is accepted so a future model can
     * gate on premium too; the current rules depend only on the quote data.
     */
    public UnderwritingOutcome assess(Map<String, Object> quoteData, RatingResult ratingResult) {
        Map<String, Object> data = quoteData == null ? Map.of() : quoteData;
        Map<String, Object> vehicle = section(data, "vehicle");
        Map<String, Object> customer = section(data, "customer");
        Map<String, Object> history = section(data, "history");

        // ---- Decline (most restrictive) ----
        List<String> declineReasons = new ArrayList<>();
        Integer age = QuoteValues.ageFromDob(customer.get("dateOfBirth"));
        if (age != null && age < MIN_DRIVER_AGE) {
            declineReasons.add("Driver is under 18");
        }
        if (Boolean.FALSE.equals(vehicle.get("supported"))) {
            declineReasons.add("Vehicle is not supported for cover");
        }
        if (!declineReasons.isEmpty()) {
            return new UnderwritingOutcome(UnderwritingOutcome.DECLINE, declineReasons);
        }

        // ---- Refer ----
        List<String> referReasons = new ArrayList<>();
        int value = QuoteValues.intValue(vehicle.get("value"), 0);
        if (value > VALUE_REFER_THRESHOLD) {
            referReasons.add("Vehicle value exceeds £75,000");
        }
        int claims = QuoteValues.intValue(history.get("claimsLast3Years"), 0);
        if (claims > CLAIMS_REFER_THRESHOLD) {
            referReasons.add("More than 3 claims in the last 3 years");
        }
        int convictions = QuoteValues.intValue(history.get("offencesLast5Years"), 0);
        if (convictions > CONVICTIONS_REFER_THRESHOLD) {
            referReasons.add("More than 2 convictions in the last 5 years");
        }
        if (!referReasons.isEmpty()) {
            return new UnderwritingOutcome(UnderwritingOutcome.REFER, referReasons);
        }

        return new UnderwritingOutcome(UnderwritingOutcome.QUOTE, List.of());
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> section(Map<String, Object> data, String key) {
        Object v = data.get(key);
        return (v instanceof Map) ? (Map<String, Object>) v : Map.of();
    }
}
