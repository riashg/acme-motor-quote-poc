package com.acme.platform.pricing;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.acme.platform.vendor.QuoteValues;
import com.acme.platform.vendor.RatingResult;
import com.acme.platform.vendor.VendorClient;

/**
 * Assembles the brief §11/§10 <b>pricing object</b> for a quote (Slice 5).
 *
 * <p>Two responsibilities, kept distinct per the §3 hard line:
 * <ul>
 *   <li><b>Rating</b> comes from the vendor seam ({@link VendorClient#rate}) —
 *       the premium is a value the platform does not own.</li>
 *   <li><b>Underwriting</b> is platform-owned ({@link UnderwritingEngine}) — the
 *       quote / refer / decline decision is the insurer's risk policy.</li>
 * </ul>
 *
 * <p>The mock model is IPT-inclusive (the rated premium already includes IPT),
 * splits the annual premium into a simple 10-instalment plan, and adds a
 * rating-set compulsory excess to the customer's voluntary excess.
 */
@Service
public class PricingService {

    /** Mock rating-set compulsory excess (brief §11 sample). */
    static final int COMPULSORY_EXCESS = 350;
    /** Simple monthly split: a deposit plus this many instalments. */
    static final int INSTALMENTS = 10;

    private final VendorClient vendor;
    private final UnderwritingEngine underwriting;

    public PricingService(VendorClient vendor, UnderwritingEngine underwriting) {
        this.vendor = vendor;
        this.underwriting = underwriting;
    }

    /**
     * Rate (vendor) + underwrite (platform), then build the full pricing object.
     * The premium and breakdown are echoed through from the vendor; the
     * {@code outcome}/{@code reasons} are the platform's decision.
     */
    public Map<String, Object> price(Map<String, Object> quoteData) {
        RatingResult rating = vendor.rate(quoteData);
        UnderwritingOutcome decision = underwriting.assess(quoteData, rating);

        Map<String, Object> cover = section(quoteData, "cover");
        Map<String, Object> driver = section(quoteData, "driver");

        double annualPremium = round2(rating.annualPremium());

        int voluntaryExcess = QuoteValues.intValue(cover.get("voluntaryExcess"), 0);
        int totalExcess = COMPULSORY_EXCESS + voluntaryExcess;
        int ncdYears = QuoteValues.intValue(driver.get("ncdYears"), 0);

        Map<String, Object> pricing = new LinkedHashMap<>();
        pricing.put("annualPremium", annualPremium);
        pricing.put("currency", "GBP");
        pricing.put("iptIncluded", true);
        pricing.put("monthly", monthly(annualPremium));
        pricing.put("compulsoryExcess", COMPULSORY_EXCESS);
        pricing.put("voluntaryExcess", voluntaryExcess);
        pricing.put("totalExcess", totalExcess);
        pricing.put("ncdYears", ncdYears);
        pricing.put("outcome", decision.outcome());
        pricing.put("reasons", decision.reasons());
        pricing.put("breakdown", rating.breakdown());
        return pricing;
    }

    /**
     * Map an underwriting outcome to the §6 journey state:
     * {@code quote→quoted}, {@code refer→referred}, {@code decline→declined}.
     */
    public static String journeyStateFor(String outcome) {
        return switch (outcome) {
            case UnderwritingOutcome.QUOTE -> "quoted";
            case UnderwritingOutcome.REFER -> "referred";
            case UnderwritingOutcome.DECLINE -> "declined";
            default -> "ready_to_price";
        };
    }

    /**
     * Simple monthly split: spread the annual premium over a deposit plus
     * {@value #INSTALMENTS} equal instalments. The deposit absorbs any rounding
     * remainder so {@code deposit + instalment * instalments == annualPremium}.
     */
    private static Map<String, Object> monthly(double annualPremium) {
        BigDecimal total = BigDecimal.valueOf(annualPremium);
        BigDecimal instalment = total
            .divide(BigDecimal.valueOf(INSTALMENTS), 2, RoundingMode.HALF_UP);
        BigDecimal deposit = total
            .subtract(instalment.multiply(BigDecimal.valueOf(INSTALMENTS - 1)))
            .setScale(2, RoundingMode.HALF_UP);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("deposit", deposit.doubleValue());
        m.put("instalment", instalment.doubleValue());
        m.put("instalments", INSTALMENTS);
        return m;
    }

    private static double round2(double value) {
        return BigDecimal.valueOf(value).setScale(2, RoundingMode.HALF_UP).doubleValue();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> section(Map<String, Object> data, String key) {
        Object v = data == null ? null : data.get(key);
        return (v instanceof Map) ? (Map<String, Object>) v : Map.of();
    }
}
