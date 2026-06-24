package com.acme.platform.vendor;

import java.util.List;
import java.util.Map;

/**
 * The rating a real UK motor insurer obtains <b>from the vendor over SOAP</b>
 * (brief §15): the computed annual premium plus a transparent
 * {@code breakdown} of the lines that produced it.
 *
 * <p>The premium is a value the platform does not own — it comes from the
 * vendor seam ({@link VendorClient#rate}). The {@code breakdown} lines exist so
 * the conversation layer can explain the number without inventing anything; by
 * construction the line amounts sum to {@link #annualPremium()}.
 *
 * <p>Each breakdown line is a {@code {label, amount}} map (insertion-ordered),
 * carried as plain {@code Map}/{@code List} so it serialises straight into the
 * pricing object's {@code breakdown} array.
 *
 * @param annualPremium the rated annual premium (IPT-inclusive in this mock model)
 * @param breakdown     ordered {@code {label, amount}} lines that sum to the premium
 */
public record RatingResult(double annualPremium, List<Map<String, Object>> breakdown) {

    public RatingResult {
        breakdown = breakdown == null ? List.of() : List.copyOf(breakdown);
    }
}
