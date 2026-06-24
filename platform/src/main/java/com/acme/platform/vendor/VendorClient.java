package com.acme.platform.vendor;

import java.util.List;
import java.util.Map;

/**
 * The external-vendor seam a real UK motor insurer calls <b>over SOAP</b> for
 * values it does not own — vehicle data from a registration, and address
 * candidates from a postcode. Services depend only on this interface, never on
 * the transport.
 *
 * <p>Today {@link MockVendorClient} implements it with deterministic synthetic
 * data. Later, a {@code SoapVendorClient} — generated from the vendor WSDL with
 * JAX-WS / Spring-WS stubs and WS-Security as needed — will implement this same
 * interface, so swapping mock&rarr;SOAP changes nothing in the callers.
 *
 * <p><b>Rating</b> ({@link #rate}) belongs here too: in a real insurer the
 * premium is a value obtained from the vendor over SOAP, not something the
 * platform computes. The platform owns only <i>underwriting</i> (quote / refer /
 * decline); the price itself comes through this seam.
 */
public interface VendorClient {

    /** Resolve a registration to make/model/derivative/fuel/transmission (+ echoed registration). */
    Map<String, Object> lookupVehicle(String registration);

    /** Resolve a postcode to a list of candidate addresses. */
    List<Map<String, Object>> lookupAddress(String postcode);

    /**
     * Rate a quote: return the annual premium plus a transparent breakdown
     * (brief §15). A real insurer obtains this from the vendor over SOAP, so it
     * lives behind the seam; {@link MockVendorClient#rate} implements the brief's
     * deterministic mock model.
     *
     * @param quoteData the whole-model quote payload (nested maps)
     * @return the rated premium and its {@code {label, amount}} breakdown lines
     */
    RatingResult rate(Map<String, Object> quoteData);

    /**
     * Issue a policy from a priced quote (Slice 8): bind the quote into a
     * policy and return the issued {@code policyNumber}, {@code status}, and
     * {@code effectiveDate}. In a real insurer this is a vendor call
     * <b>over SOAP</b> (a future {@code SoapVendorClient.issuePolicy(...)}
     * behind this same seam), so callers depend only on this interface, never
     * on the transport.
     *
     * <p>{@link MockVendorClient#issuePolicy} implements it with a deterministic
     * synthetic policy. <b>Real issuance and payments stay out of scope
     * (brief §2)</b> — only the seam is visible.
     *
     * @param quoteData the whole-model quote payload (nested maps)
     * @return the issued policy: {@code {policyNumber, status, effectiveDate}}
     */
    PolicyResult issuePolicy(Map<String, Object> quoteData);
}
