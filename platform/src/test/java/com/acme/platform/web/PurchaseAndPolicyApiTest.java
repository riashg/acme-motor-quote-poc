package com.acme.platform.web;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Slices 7 & 8: purchase-link minting, the strict GUID landing page, and mock
 * policy issuance via the vendor seam.
 */
@SpringBootTest
@AutoConfigureMockMvc
class PurchaseAndPolicyApiTest {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired com.acme.platform.events.EventStore eventStore;
    @Autowired com.acme.platform.purchase.PurchaseLinkService purchaseLinks;

    // ---------------------------------------------------------------------
    // Slice 7 — purchase link
    // ---------------------------------------------------------------------

    @Test
    void purchaseLinkForPricedQuoteReturnsTokenAndUrlAndEmitsEvent() throws Exception {
        String[] qs = pricedQuote();
        String qid = qs[0], sid = qs[1];

        mvc.perform(post("/quotes/" + qid + "/purchase-link").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.purchaseToken").exists())
            .andExpect(jsonPath("$.purchaseUrl", startsWith("http://localhost:8070/purchase/")));

        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .anyMatch(e -> e.type().equals("PURCHASE_LINK_GENERATED")
                && qid.equals(e.payload().get("quoteId")));
        // Domain event must not carry the sessionId or the token.
        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .filteredOn(e -> e.type().equals("PURCHASE_LINK_GENERATED"))
            .allSatisfy(e -> {
                org.assertj.core.api.Assertions.assertThat(e.payload().toString()).doesNotContain(sid);
                org.assertj.core.api.Assertions.assertThat(e.payload()).containsOnlyKeys("quoteId");
            });
    }

    @Test
    void purchaseLinkForNonQuoteOutcomeIsConflict() throws Exception {
        // A refer outcome (high-value vehicle) is not cleanly priced → not purchasable.
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        ObjectNode patch = completePatch();
        ((ObjectNode) patch.get("vehicle")).put("value", 90000);
        patchComplete(qid, sid, patch);
        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(jsonPath("$.outcome").value("refer"));

        mvc.perform(post("/quotes/" + qid + "/purchase-link").header("X-Session-Id", sid))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.error").value("not_purchasable"));
    }

    @Test
    void purchaseLinkWrongOrMissingSessionIsNotFound() throws Exception {
        String[] qs = pricedQuote();
        String qid = qs[0];
        mvc.perform(post("/quotes/" + qid + "/purchase-link")).andExpect(status().isNotFound());
        mvc.perform(post("/quotes/" + qid + "/purchase-link").header("X-Session-Id", "wrong"))
            .andExpect(status().isNotFound());
    }

    // ---------------------------------------------------------------------
    // Slice 7 — strict GUID landing page
    // ---------------------------------------------------------------------

    @Test
    void landingForValidTokenRendersQuoteHtmlWithPremium() throws Exception {
        String[] qs = pricedQuote();
        String token = mintToken(qs[0], qs[1]);

        mvc.perform(get("/purchase/" + token))
            .andExpect(status().isOk())
            .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_HTML))
            .andExpect(content().string(containsString("Annual premium")))
            .andExpect(content().string(containsString("GBP")));
    }

    @Test
    void landingForUnknownTokenIsNotFoundWithCleanPage() throws Exception {
        mvc.perform(get("/purchase/this-is-not-a-real-token-zzzz"))
            .andExpect(status().isNotFound())
            .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_HTML))
            .andExpect(content().string(containsString("Quote not found")));
    }

    @Test
    void landingForTokenOfNotCleanlyPricedQuoteIsNotFound() throws Exception {
        // Mint a token directly for a refer quote (service allows it only for clean
        // quotes via the endpoint, so we mint via the bean to prove the landing page
        // itself re-checks cleanliness and returns 404).
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        ObjectNode patch = completePatch();
        ((ObjectNode) patch.get("vehicle")).put("value", 90000);
        patchComplete(qid, sid, patch);
        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(jsonPath("$.outcome").value("refer"));

        String token = purchaseLinks.mintToken(qid); // bypass the endpoint guard
        mvc.perform(get("/purchase/" + token))
            .andExpect(status().isNotFound())
            .andExpect(content().string(containsString("Quote not found")));
    }

    // ---------------------------------------------------------------------
    // Slice 8 — mock policy issuance
    // ---------------------------------------------------------------------

    @Test
    void issuePolicyForPricedQuoteIssuesAndAdvancesJourneyAndEmitsEvent() throws Exception {
        String[] qs = pricedQuote();
        String qid = qs[0], sid = qs[1];

        MvcResult res = mvc.perform(post("/quotes/" + qid + "/issue-policy").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.policyNumber", startsWith("ACME-POL-")))
            .andExpect(jsonPath("$.status").value("ISSUED"))
            .andExpect(jsonPath("$.effectiveDate").exists())
            .andReturn();
        String policyNumber = mapper.readTree(res.getResponse().getContentAsString())
            .get("policyNumber").asText();

        // GET reflects the policy_issued journey state + stored policy.
        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", sid))
            .andExpect(jsonPath("$.journeyState").value("policy_issued"))
            .andExpect(jsonPath("$.policy.policyNumber").value(policyNumber))
            .andExpect(jsonPath("$.policy.status").value("ISSUED"));

        // POLICY_CREATED domain event with quoteId + policyNumber, no sessionId.
        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .anyMatch(e -> e.type().equals("POLICY_CREATED")
                && qid.equals(e.payload().get("quoteId"))
                && policyNumber.equals(e.payload().get("policyNumber")));
        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .filteredOn(e -> e.type().equals("POLICY_CREATED"))
            .allSatisfy(e ->
                org.assertj.core.api.Assertions.assertThat(e.payload().toString()).doesNotContain(sid));
    }

    @Test
    void issuePolicyForRefereeOutcomeIsConflict() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        ObjectNode patch = completePatch();
        ((ObjectNode) patch.get("vehicle")).put("value", 90000);
        patchComplete(qid, sid, patch);
        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(jsonPath("$.outcome").value("refer"));

        mvc.perform(post("/quotes/" + qid + "/issue-policy").header("X-Session-Id", sid))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.error").value("not_issuable"));
    }

    @Test
    void issuePolicyWrongSessionIsNotFound() throws Exception {
        String[] qs = pricedQuote();
        mvc.perform(post("/quotes/" + qs[0] + "/issue-policy").header("X-Session-Id", "wrong"))
            .andExpect(status().isNotFound());
    }

    // ---------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------

    /** Create + complete + price a clean quote; return {quoteId, sessionId}. */
    private String[] pricedQuote() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        patchComplete(qid, sid, completePatch());
        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.outcome").value("quote"));
        return new String[]{qid, sid};
    }

    private String mintToken(String qid, String sid) throws Exception {
        MvcResult res = mvc.perform(post("/quotes/" + qid + "/purchase-link").header("X-Session-Id", sid))
            .andExpect(status().isOk()).andReturn();
        return mapper.readTree(res.getResponse().getContentAsString()).get("purchaseToken").asText();
    }

    private JsonNode create() throws Exception {
        MvcResult res = mvc.perform(post("/quotes")).andExpect(status().isCreated()).andReturn();
        return mapper.readTree(res.getResponse().getContentAsString());
    }

    private void patchComplete(String qid, String sid, ObjectNode patch) throws Exception {
        ObjectNode body = mapper.createObjectNode();
        body.set("patch", patch);
        mvc.perform(patch("/quotes/" + qid)
                .header("X-Session-Id", sid)
                .contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(body)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.missingFields", is(java.util.Collections.emptyList())));
    }

    private ObjectNode completePatch() {
        ObjectNode patch = mapper.createObjectNode();
        for (String path : com.acme.platform.quote.RequiredFields.MANDATORY_FIELDS) {
            setPath(patch, path, "filled");
        }
        setPath(patch, "customer.dateOfBirth", "1990-01-01");
        setPath(patch, "customer.address.postcode", "RG1 1AA");
        setNumber(patch, "vehicle.value", 12000);
        setNumber(patch, "vehicle.annualMileage", 8000);
        setNumber(patch, "history.claimsLast3Years", 0);
        setNumber(patch, "history.offencesLast5Years", 0);
        setPath(patch, "cover.coverLevel", "Comprehensive");
        setPath(patch, "cover.coverStartDate", "2026-07-01");
        setNumber(patch, "cover.voluntaryExcess", 250);
        setNumber(patch, "driver.ncdYears", 5);
        return patch;
    }

    private void setPath(ObjectNode root, String dotPath, String value) {
        walk(root, dotPath).put(lastSegment(dotPath), value);
    }

    private void setNumber(ObjectNode root, String dotPath, int value) {
        walk(root, dotPath).put(lastSegment(dotPath), value);
    }

    private ObjectNode walk(ObjectNode root, String dotPath) {
        String[] parts = dotPath.split("\\.");
        ObjectNode cur = root;
        for (int i = 0; i < parts.length - 1; i++) {
            if (!(cur.get(parts[i]) instanceof ObjectNode)) {
                cur.set(parts[i], mapper.createObjectNode());
            }
            cur = (ObjectNode) cur.get(parts[i]);
        }
        return cur;
    }

    private static String lastSegment(String dotPath) {
        String[] parts = dotPath.split("\\.");
        return parts[parts.length - 1];
    }
}
