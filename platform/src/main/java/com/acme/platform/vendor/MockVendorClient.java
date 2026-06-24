package com.acme.platform.vendor;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

/**
 * Deterministic, synthetic {@link VendorClient} for the PoC — no real brand,
 * plate, or vehicle data anywhere (brief naming rule).
 *
 * <p>Design decision (documented): for an <b>unknown registration</b> the mock
 * returns a deterministic synthetic fallback vehicle (never {@code null}) so
 * demos always have a make/model to show; address lookup likewise returns a
 * deterministic candidate list for unseeded postcodes.
 *
 * <p>{@code @Primary} so it is injected by default; the future
 * {@code SoapVendorClient} will replace it behind the same interface.
 */
@Component
@Primary
public class MockVendorClient implements VendorClient {

    // Seeded synthetic registrations: one ordinary car, plus a performance /
    // high-value car used later for the referral demo (brief §15).
    private static final Map<String, Map<String, Object>> SEEDED_VEHICLES = new LinkedHashMap<>();
    private static final Map<String, List<Map<String, Object>>> SEEDED_ADDRESSES = new LinkedHashMap<>();

    // ---- Mock rating model (brief §15) — deliberately simple and transparent. ----
    static final double BASE_PREMIUM = 350.0;
    static final double LOADING_UNDER_25 = 600.0;
    static final double LOADING_HIGH_RISK_POSTCODE = 250.0;
    static final double LOADING_PERFORMANCE_VEHICLE = 400.0;
    static final double LOADING_PER_CLAIM = 200.0;
    static final double LOADING_PER_CONVICTION = 300.0;
    static final double LOADING_COMPREHENSIVE = 80.0;
    static final double LOADING_HIGH_MILEAGE = 100.0;
    static final double DISCOUNT_LARGE_EXCESS = 50.0;

    // Mock thresholds (documented, not from real rating material; brief §15).
    static final int PERFORMANCE_VALUE_THRESHOLD = 60_000;   // £ — "performance vehicle" heuristic (value ≥ ~£60k)
    static final int HIGH_MILEAGE_THRESHOLD = 12_000;        // miles/year — "high mileage" (> 12,000)
    static final int LARGE_EXCESS_THRESHOLD = 500;           // £ voluntary excess — "large excess"

    /** Mock high-risk postcode prefixes (outward-area heuristic). */
    static final Set<String> HIGH_RISK_POSTCODE_PREFIXES = Set.of("M1", "B1", "L1", "BD1", "BB1");

    static {
        SEEDED_VEHICLES.put("FX19ZTC", vehicle("Ford", "Focus", "Titanium 1.0 EcoBoost", "Petrol", "Manual"));
        SEEDED_VEHICLES.put("VW68ABC", vehicle("Volkswagen", "Golf", "Life 1.5 TSI", "Petrol", "Automatic"));
        SEEDED_VEHICLES.put("PF21XYZ", vehicle("Performance Marque", "GT Coupe", "Twin-Turbo 600", "Petrol", "Automatic"));

        SEEDED_ADDRESSES.put("RG11AA", List.of(
            address("1", "1 Sample Street", "RG1 1AA"),
            address("2", "2 Sample Street", "RG1 1AA"),
            address("3", "3 Sample Street", "RG1 1AA")
        ));
        SEEDED_ADDRESSES.put("M12AB", List.of(
            address("10", "10 Example Road", "M1 2AB"),
            address("12", "12 Example Road", "M1 2AB")
        ));
    }

    private static Map<String, Object> vehicle(String make, String model, String derivative, String fuel, String transmission) {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("make", make);
        v.put("model", model);
        v.put("derivative", derivative);
        v.put("fuel", fuel);
        v.put("transmission", transmission);
        return v;
    }

    private static Map<String, Object> address(String houseNumberOrName, String line1, String postcode) {
        Map<String, Object> a = new LinkedHashMap<>();
        a.put("houseNumberOrName", houseNumberOrName);
        a.put("line1", line1);
        a.put("postcode", postcode);
        return a;
    }

    private static String normaliseReg(String registration) {
        return (registration == null ? "" : registration).toUpperCase().replace(" ", "");
    }

    private static String normalisePostcode(String postcode) {
        return (postcode == null ? "" : postcode).toUpperCase().replace(" ", "");
    }

    @Override
    public Map<String, Object> lookupVehicle(String registration) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("registration", registration);
        Map<String, Object> seeded = SEEDED_VEHICLES.get(normaliseReg(registration));
        if (seeded != null) {
            result.putAll(seeded);
        } else {
            // Deterministic synthetic fallback so a demo always has a make/model.
            result.putAll(vehicle("Sample Motors", "Saloon", "Standard", "Petrol", "Manual"));
        }
        return result;
    }

    @Override
    public List<Map<String, Object>> lookupAddress(String postcode) {
        List<Map<String, Object>> seeded = SEEDED_ADDRESSES.get(normalisePostcode(postcode));
        if (seeded != null) {
            return new ArrayList<>(seeded);
        }
        // Deterministic synthetic fallback candidate.
        String normalised = (postcode == null ? "" : postcode).strip().toUpperCase();
        List<Map<String, Object>> fallback = new ArrayList<>();
        fallback.add(address("1", "1 Synthetic Avenue", normalised));
        return fallback;
    }

    /**
     * Deterministic mock rating per brief §15. Starts at the base premium and
     * applies each adjustment, recording a {@code {label, amount}} breakdown
     * line for every non-zero step. By construction the breakdown lines sum to
     * the returned premium, so the conversation can explain the number without
     * inventing anything.
     *
     * <p>This is the value a real insurer would obtain from the vendor over
     * SOAP; a future {@code SoapVendorClient.rate(...)} would return the same
     * {@link RatingResult} shape.
     */
    @Override
    public RatingResult rate(Map<String, Object> quoteData) {
        Map<String, Object> data = quoteData == null ? Map.of() : quoteData;
        Map<String, Object> vehicle = section(data, "vehicle");
        Map<String, Object> customer = section(data, "customer");
        Map<String, Object> history = section(data, "history");
        Map<String, Object> cover = section(data, "cover");

        List<Map<String, Object>> breakdown = new ArrayList<>();
        double premium = BASE_PREMIUM;
        breakdown.add(line("Base premium", BASE_PREMIUM));

        Integer age = QuoteValues.ageFromDob(customer.get("dateOfBirth"));
        if (age != null && age < 25) {
            premium += LOADING_UNDER_25;
            breakdown.add(line("Driver under 25", LOADING_UNDER_25));
        }

        String postcode = postcode(customer);
        if (isHighRiskPostcode(postcode)) {
            premium += LOADING_HIGH_RISK_POSTCODE;
            breakdown.add(line("High-risk postcode", LOADING_HIGH_RISK_POSTCODE));
        }

        if (isPerformanceVehicle(vehicle)) {
            premium += LOADING_PERFORMANCE_VEHICLE;
            breakdown.add(line("Performance vehicle", LOADING_PERFORMANCE_VEHICLE));
        }

        int claims = QuoteValues.intValue(history.get("claimsLast3Years"), 0);
        if (claims > 0) {
            double amount = LOADING_PER_CLAIM * claims;
            premium += amount;
            breakdown.add(line(claims + " claim(s) in last 3 years", amount));
        }

        int convictions = QuoteValues.intValue(history.get("offencesLast5Years"), 0);
        if (convictions > 0) {
            double amount = LOADING_PER_CONVICTION * convictions;
            premium += amount;
            breakdown.add(line(convictions + " conviction(s) in last 5 years", amount));
        }

        if (isComprehensive(cover)) {
            premium += LOADING_COMPREHENSIVE;
            breakdown.add(line("Comprehensive cover", LOADING_COMPREHENSIVE));
        }

        int mileage = QuoteValues.intValue(vehicle.get("annualMileage"), 0);
        if (mileage > HIGH_MILEAGE_THRESHOLD) {
            premium += LOADING_HIGH_MILEAGE;
            breakdown.add(line("High annual mileage", LOADING_HIGH_MILEAGE));
        }

        int voluntaryExcess = QuoteValues.intValue(cover.get("voluntaryExcess"), 0);
        if (voluntaryExcess >= LARGE_EXCESS_THRESHOLD) {
            premium -= DISCOUNT_LARGE_EXCESS;
            breakdown.add(line("Large voluntary excess discount", -DISCOUNT_LARGE_EXCESS));
        }

        return new RatingResult(premium, breakdown);
    }

    /**
     * Issue a deterministic, synthetic policy (Slice 8): a policy number with the
     * neutral {@code ACME-POL-} prefix plus a short id, status {@code ISSUED},
     * and an effective date taken from the quote's cover start date (or today if
     * absent/unparseable). No real brand, plate, or vehicle data.
     *
     * <p>This is the value a real insurer would obtain from the vendor over SOAP;
     * a future {@code SoapVendorClient.issuePolicy(...)} would return the same
     * {@link PolicyResult} shape. <b>Real issuance and payments stay out of scope
     * (brief §2)</b> — only this seam is visible.
     */
    @Override
    public PolicyResult issuePolicy(Map<String, Object> quoteData) {
        Map<String, Object> data = quoteData == null ? Map.of() : quoteData;
        Map<String, Object> cover = section(data, "cover");

        String effectiveDate = coverStartDate(cover.get("coverStartDate"));
        String shortId = UUID.randomUUID().toString().substring(0, 8).toUpperCase();
        return new PolicyResult("ACME-POL-" + shortId, "ISSUED", effectiveDate);
    }

    /** The cover start date if it parses as ISO {@code yyyy-MM-dd}, else today. */
    private static String coverStartDate(Object value) {
        if (value instanceof String s && !s.isBlank()) {
            try {
                return LocalDate.parse(s.strip()).toString();
            } catch (DateTimeParseException ignored) {
                // fall through to today
            }
        }
        return LocalDate.now().toString();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> section(Map<String, Object> data, String key) {
        Object v = data.get(key);
        return (v instanceof Map) ? (Map<String, Object>) v : Map.of();
    }

    private static Map<String, Object> line(String label, double amount) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("label", label);
        m.put("amount", amount);
        return m;
    }

    private static String postcode(Map<String, Object> customer) {
        Object addr = customer.get("address");
        if (addr instanceof Map<?, ?> m) {
            Object pc = m.get("postcode");
            return pc == null ? null : pc.toString();
        }
        return null;
    }

    static boolean isHighRiskPostcode(String postcode) {
        if (postcode == null) {
            return false;
        }
        String outward = normalisePostcode(postcode);
        // Outward code is everything before the final three (inward) characters.
        if (outward.length() > 3) {
            outward = outward.substring(0, outward.length() - 3);
        }
        return HIGH_RISK_POSTCODE_PREFIXES.contains(outward);
    }

    /** Mock heuristic: a flagged performance vehicle, or value at/above the threshold. */
    static boolean isPerformanceVehicle(Map<String, Object> vehicle) {
        Object flag = vehicle.get("performance");
        if (flag instanceof Boolean b && b) {
            return true;
        }
        return QuoteValues.intValue(vehicle.get("value"), 0) >= PERFORMANCE_VALUE_THRESHOLD;
    }

    private static boolean isComprehensive(Map<String, Object> cover) {
        Object level = cover.get("coverLevel");
        return level != null && level.toString().toLowerCase().contains("comprehensive");
    }
}
