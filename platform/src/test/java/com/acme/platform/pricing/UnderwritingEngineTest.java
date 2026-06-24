package com.acme.platform.pricing;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.acme.platform.vendor.RatingResult;

class UnderwritingEngineTest {

    private final UnderwritingEngine engine = new UnderwritingEngine();
    private final RatingResult anyRating = new RatingResult(350.0, java.util.List.of());

    /** A normal, acceptable profile. */
    private static Map<String, Object> normalProfile() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("customer", new LinkedHashMap<>(Map.of("dateOfBirth", "1990-01-01")));
        data.put("vehicle", new LinkedHashMap<>(Map.of("value", 12000)));
        data.put("history", new LinkedHashMap<>(Map.of("claimsLast3Years", 0, "offencesLast5Years", 0)));
        return data;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> sub(Map<String, Object> data, String key) {
        return (Map<String, Object>) data.get(key);
    }

    @Test
    void normalProfileIsQuoteWithNoReasons() {
        UnderwritingOutcome o = engine.assess(normalProfile(), anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.QUOTE);
        assertThat(o.reasons()).isEmpty();
    }

    @Test
    void vehicleValueAbove75kRefers() {
        Map<String, Object> data = normalProfile();
        sub(data, "vehicle").put("value", 80000);
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.REFER);
        assertThat(o.reasons()).anyMatch(r -> r.contains("75,000"));
    }

    @Test
    void moreThanThreeClaimsRefers() {
        Map<String, Object> data = normalProfile();
        sub(data, "history").put("claimsLast3Years", 4);
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.REFER);
        assertThat(o.reasons()).anyMatch(r -> r.contains("claims"));
    }

    @Test
    void moreThanTwoConvictionsRefers() {
        Map<String, Object> data = normalProfile();
        sub(data, "history").put("offencesLast5Years", 3);
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.REFER);
        assertThat(o.reasons()).anyMatch(r -> r.contains("convictions"));
    }

    @Test
    void driverUnder18Declines() {
        Map<String, Object> data = normalProfile();
        sub(data, "customer").put("dateOfBirth", LocalDate.now().minusYears(17).toString());
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.DECLINE);
        assertThat(o.reasons()).anyMatch(r -> r.contains("under 18"));
    }

    @Test
    void unsupportedVehicleDeclines() {
        Map<String, Object> data = normalProfile();
        sub(data, "vehicle").put("supported", false);
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.DECLINE);
        assertThat(o.reasons()).anyMatch(r -> r.contains("not supported"));
    }

    @Test
    void declineTakesPrecedenceOverRefer() {
        // Under-18 (decline) and high-value (refer) together → decline wins.
        Map<String, Object> data = normalProfile();
        sub(data, "customer").put("dateOfBirth", LocalDate.now().minusYears(16).toString());
        sub(data, "vehicle").put("value", 90000);
        UnderwritingOutcome o = engine.assess(data, anyRating);
        assertThat(o.outcome()).isEqualTo(UnderwritingOutcome.DECLINE);
    }
}
