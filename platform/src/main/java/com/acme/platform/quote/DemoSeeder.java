package com.acme.platform.quote;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.acme.platform.pricing.PricingService;

/**
 * Stable demo GUID + session (brief §9, §17.6, §17.7).
 *
 * <p>A single, fixed quote id and session id that always resolve to a
 * fully-populated {@code ready_to_price} sample quote for demos / screenshots.
 * The sample is <b>self-seeded on first access</b> and isolated in the same
 * session store as in-progress quotes, but with a fixed id so it never collides
 * with a real (random-GUID) quote. A wrong session yields 404.
 *
 * <p>The two constants are the demo's contract — reused verbatim from the
 * Python platform for continuity:
 * <pre>
 *   DEMO_QUOTE_ID   = "00000000-0000-4000-8000-000000000001"
 *   DEMO_SESSION_ID = "demo-session-0000000000000000000000000000000"
 * </pre>
 *
 * <p>All sample data is synthetic. The sample is pre-priced on seed (Slice 5)
 * so the demo GUID resolves to a fully-priced {@code quoted} quote.
 */
@Component
public class DemoSeeder {

    public static final String DEMO_QUOTE_ID = "00000000-0000-4000-8000-000000000001";
    public static final String DEMO_SESSION_ID = "demo-session-0000000000000000000000000000000";

    private final SessionStore sessions;
    private final PricingService pricing;

    public DemoSeeder(SessionStore sessions, PricingService pricing) {
        this.sessions = sessions;
        this.pricing = pricing;
    }

    /**
     * Seed the demo quote on first access; return its record. Idempotent:
     * re-seeds only if the fixed id is not already present, so it never disturbs
     * an in-progress quote (which carries a random GUID).
     *
     * <p>The sample is pre-priced on seed so the stable demo GUID always resolves
     * to a fully-priced {@code quoted} sample (brief §9, §17.7) — no need to call
     * {@code /price} first for demos / screenshots.
     */
    public synchronized QuoteRecord ensureSeeded() {
        if (!sessions.exists(DEMO_QUOTE_ID)) {
            Map<String, Object> data = buildDemoData();
            Map<String, Object> pricingObject = pricing.price(data);
            data.put("pricing", pricingObject);
            data.put("currentOutcome", pricingObject.get("outcome"));
            sessions.put(new QuoteRecord(DEMO_QUOTE_ID, DEMO_SESSION_ID, data));
        }
        return sessions.get(DEMO_QUOTE_ID, DEMO_SESSION_ID);
    }

    private static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    /** A fully-populated sample quote: every mandatory field filled → ready_to_price. */
    private static Map<String, Object> buildDemoData() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("vehicle", map(
            "registration", "FX19ZTC",
            "make", "Ford",
            "model", "Focus",
            "derivative", "Titanium 1.0 EcoBoost",
            "fuel", "Petrol",
            "transmission", "Manual",
            "datePurchased", map("month", 6, "year", 2020),
            "value", 12000,
            "useOfVehicle", "Social + commuting",
            "security", "Factory-fitted",
            "dashcam", true,
            "modified", false,
            "imported", "No",
            "daytimeLocation", "Street",
            "overnightLocation", "Drive",
            "annualMileage", 8000,
            "registeredKeeper", true,
            "legalOwner", true
        ));
        data.put("customer", map(
            "title", "Mr",
            "firstName", "Sam",
            "surname", "Sample",
            "dateOfBirth", "1990-01-01",
            "maritalStatus", "Single",
            "childrenUnder16", "0",
            "employmentStatus", "Employed",
            "partTimeJob", false,
            "yearsLivedInUK", "Since birth",
            "address", map("houseNumberOrName", "1", "postcode", "RG1 1AA"),
            "ownsProperty", true,
            "carKeptOvernightAtAddress", true,
            "email", "sam.sample@example.com",
            "mobile", "07000000000"
        ));
        data.put("driver", map(
            "licenceType", "Full UK",
            "licenceHeldFor", "10",
            "insuranceCancelledOrVoid", false,
            "ncdYears", 5,
            "ncdOnCompanyCar", false
        ));
        data.put("history", map(
            "claimsLast3Years", 0,
            "offencesLast5Years", 0,
            "unspentCriminalConvictions", false
        ));
        data.put("household", map(
            "carsInHousehold", "1",
            "anotherCarHasCover", false,
            "regularUseOfOtherVehicles", "None"
        ));
        data.put("cover", map(
            "paymentMethod", "Monthly instalments",
            "coverLevel", "Comprehensive",
            "coverStartDate", "2026-07-01",
            "voluntaryExcess", 250
        ));
        data.put("namedDrivers", new ArrayList<>());
        data.put("marketing", map("email", true, "telephone", false, "sms", false));
        // Pricing is computed on seed (see ensureSeeded) so the demo is pre-priced.
        return data;
    }
}
