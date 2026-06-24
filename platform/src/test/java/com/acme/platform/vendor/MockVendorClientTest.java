package com.acme.platform.vendor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class MockVendorClientTest {

    private final MockVendorClient vendor = new MockVendorClient();

    @Test
    void seededRegistrationReturnsKnownVehicleEchoingRegistration() {
        Map<String, Object> v = vendor.lookupVehicle("FX19ZTC");
        assertThat(v.get("make")).isEqualTo("Ford");
        assertThat(v.get("model")).isEqualTo("Focus");
        assertThat(v.get("registration")).isEqualTo("FX19ZTC");
        assertThat(v).containsKeys("derivative", "fuel", "transmission");
    }

    @Test
    void unknownRegistrationReturnsDeterministicSyntheticFallback() {
        Map<String, Object> v = vendor.lookupVehicle("ZZ99ZZZ");
        assertThat(v.get("make")).isEqualTo("Sample Motors");
        assertThat(v.get("registration")).isEqualTo("ZZ99ZZZ");
    }

    @Test
    void seededPostcodeReturnsCandidateList() {
        List<Map<String, Object>> candidates = vendor.lookupAddress("RG1 1AA");
        assertThat(candidates).hasSizeGreaterThanOrEqualTo(2);
        assertThat(candidates.get(0)).containsKey("houseNumberOrName");
    }

    @Test
    void unseededPostcodeReturnsFallbackCandidate() {
        List<Map<String, Object>> candidates = vendor.lookupAddress("ZZ9 9ZZ");
        assertThat(candidates).hasSize(1);
        // Fallback echoes the postcode upper-cased and trimmed (internal space kept),
        // matching the Python platform's behaviour.
        assertThat(candidates.get(0).get("postcode")).isEqualTo("ZZ9 9ZZ");
    }

    // ---------------------------------------------------------------------
    // Rating via the vendor seam (brief §15).
    // ---------------------------------------------------------------------

    /** A clean, low-risk profile: just the base premium. */
    private static Map<String, Object> baseQuote() {
        Map<String, Object> data = new LinkedHashMap<>();
        Map<String, Object> customer = new LinkedHashMap<>();
        customer.put("dateOfBirth", "1990-01-01"); // > 25
        customer.put("address", Map.of("postcode", "RG1 1AA")); // low-risk
        data.put("customer", customer);
        data.put("vehicle", new LinkedHashMap<>(Map.of("value", 12000, "annualMileage", 8000)));
        data.put("history", new LinkedHashMap<>(Map.of("claimsLast3Years", 0, "offencesLast5Years", 0)));
        data.put("cover", new LinkedHashMap<>(Map.of("coverLevel", "Third party", "voluntaryExcess", 250)));
        return data;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> sub(Map<String, Object> data, String key) {
        return (Map<String, Object>) data.get(key);
    }

    @Test
    void baseCaseIsJustTheBasePremium() {
        RatingResult r = vendor.rate(baseQuote());
        assertThat(r.annualPremium()).isEqualTo(350.0);
        assertThat(r.breakdown()).hasSize(1);
        assertThat(r.breakdown().get(0).get("label")).isEqualTo("Base premium");
    }

    @Test
    void driverUnder25AddsLoading() {
        Map<String, Object> data = baseQuote();
        sub(data, "customer").put("dateOfBirth", LocalDate.now().minusYears(20).toString());
        RatingResult r = vendor.rate(data);
        assertThat(r.annualPremium()).isEqualTo(350.0 + 600.0);
    }

    @Test
    void claimsAndConvictionsAddPerOccurrence() {
        Map<String, Object> data = baseQuote();
        sub(data, "history").put("claimsLast3Years", 2);      // +£400
        sub(data, "history").put("offencesLast5Years", 1);    // +£300
        RatingResult r = vendor.rate(data);
        assertThat(r.annualPremium()).isEqualTo(350.0 + 400.0 + 300.0);
    }

    @Test
    void comprehensiveHighMileageAndLargeExcessAdjust() {
        Map<String, Object> data = baseQuote();
        sub(data, "cover").put("coverLevel", "Comprehensive");   // +£80
        sub(data, "vehicle").put("annualMileage", 20000);        // +£100 (> 12k)
        sub(data, "cover").put("voluntaryExcess", 500);          // -£50 (>= 500)
        RatingResult r = vendor.rate(data);
        assertThat(r.annualPremium()).isEqualTo(350.0 + 80.0 + 100.0 - 50.0);
    }

    @Test
    void highRiskPostcodeAndPerformanceVehicleAdd() {
        Map<String, Object> data = baseQuote();
        sub(data, "customer").put("address", Map.of("postcode", "M1 2AB")); // high-risk +£250
        sub(data, "vehicle").put("value", 60000);                            // performance +£400
        RatingResult r = vendor.rate(data);
        assertThat(r.annualPremium()).isEqualTo(350.0 + 250.0 + 400.0);
    }

    @Test
    void breakdownLinesSumToThePremium() {
        Map<String, Object> data = baseQuote();
        sub(data, "customer").put("dateOfBirth", LocalDate.now().minusYears(19).toString());
        sub(data, "customer").put("address", Map.of("postcode", "M1 2AB"));
        sub(data, "vehicle").put("value", 80000);
        sub(data, "vehicle").put("annualMileage", 25000);
        sub(data, "history").put("claimsLast3Years", 1);
        sub(data, "history").put("offencesLast5Years", 1);
        sub(data, "cover").put("coverLevel", "Comprehensive");
        sub(data, "cover").put("voluntaryExcess", 600);

        RatingResult r = vendor.rate(data);
        double sum = r.breakdown().stream()
            .mapToDouble(line -> ((Number) line.get("amount")).doubleValue())
            .sum();
        assertThat(sum).isCloseTo(r.annualPremium(), within(0.001));
    }

    // ---------------------------------------------------------------------
    // Mock policy issuance via the vendor seam (Slice 8). Real issuance/payments
    // stay out of scope (brief §2) — only the seam is exercised here.
    // ---------------------------------------------------------------------

    @Test
    void issuePolicyReturnsSyntheticIssuedPolicyWithCoverStartDate() {
        Map<String, Object> data = baseQuote();
        data.put("cover", new LinkedHashMap<>(Map.of("coverStartDate", "2026-07-01")));

        PolicyResult policy = vendor.issuePolicy(data);
        assertThat(policy.policyNumber()).startsWith("ACME-POL-");
        assertThat(policy.status()).isEqualTo("ISSUED");
        assertThat(policy.effectiveDate()).isEqualTo("2026-07-01");
    }

    @Test
    void issuePolicyDefaultsEffectiveDateToTodayWhenCoverStartAbsentOrBad() {
        PolicyResult policy = vendor.issuePolicy(baseQuote()); // no coverStartDate
        assertThat(policy.effectiveDate()).isEqualTo(LocalDate.now().toString());
        assertThat(policy.policyNumber()).startsWith("ACME-POL-");
    }

    @Test
    void issuePolicyMintsDistinctPolicyNumbers() {
        PolicyResult a = vendor.issuePolicy(baseQuote());
        PolicyResult b = vendor.issuePolicy(baseQuote());
        assertThat(a.policyNumber()).isNotEqualTo(b.policyNumber());
    }
}
