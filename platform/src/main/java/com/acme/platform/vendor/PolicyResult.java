package com.acme.platform.vendor;

/**
 * The result a real UK motor insurer obtains <b>from the vendor over SOAP</b>
 * when binding a quote into a policy (Slice 8): the issued {@code policyNumber},
 * the {@code status} of the policy, and the {@code effectiveDate} cover begins.
 *
 * <p>Issuing a policy is a value the platform does not own — it comes through
 * the vendor seam ({@link VendorClient#issuePolicy}). Today
 * {@link MockVendorClient#issuePolicy} returns a deterministic synthetic policy;
 * a future {@code SoapVendorClient.issuePolicy(...)} would return the same shape.
 *
 * <p><b>Real issuance and payments stay out of scope (brief §2)</b> — only this
 * seam is visible.
 *
 * @param policyNumber  the issued policy number (synthetic in the mock)
 * @param status        the policy status (e.g. {@code "ISSUED"})
 * @param effectiveDate the ISO {@code yyyy-MM-dd} date cover starts
 */
public record PolicyResult(String policyNumber, String status, String effectiveDate) {
}
