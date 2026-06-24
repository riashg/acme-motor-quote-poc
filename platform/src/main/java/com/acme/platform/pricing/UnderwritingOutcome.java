package com.acme.platform.pricing;

import java.util.List;

/**
 * The platform's underwriting decision (brief §15): one of {@code quote},
 * {@code refer}, {@code decline}, with the reasons that drove a non-quote.
 *
 * <p>Underwriting is <b>platform-owned</b> — unlike the premium (which comes
 * from the vendor seam), the decision to accept, refer to a human, or decline
 * is the insurer's risk policy and is decided here.
 *
 * @param outcome {@code "quote"} | {@code "refer"} | {@code "decline"}
 * @param reasons human-readable reasons (empty for a clean {@code quote})
 */
public record UnderwritingOutcome(String outcome, List<String> reasons) {

    public static final String QUOTE = "quote";
    public static final String REFER = "refer";
    public static final String DECLINE = "decline";

    public UnderwritingOutcome {
        reasons = reasons == null ? List.of() : List.copyOf(reasons);
    }
}
