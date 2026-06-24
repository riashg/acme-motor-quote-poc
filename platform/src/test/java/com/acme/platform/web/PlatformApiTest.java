package com.acme.platform.web;

import static org.hamcrest.Matchers.empty;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import com.acme.platform.quote.DemoSeeder;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

@SpringBootTest
@AutoConfigureMockMvc
class PlatformApiTest {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired com.acme.platform.events.EventStore eventStore;

    @Test
    void health() throws Exception {
        mvc.perform(get("/health"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("ok"));
    }

    @Test
    void ping() throws Exception {
        mvc.perform(post("/ping").contentType(MediaType.APPLICATION_JSON).content("{\"hi\":1}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.pong").value(true))
            .andExpect(jsonPath("$.echo.hi").value(1));
    }

    @Test
    void postQuoteReturns201WithSessionAndStartedState() throws Exception {
        mvc.perform(post("/quotes"))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.quoteId").exists())
            .andExpect(jsonPath("$.sessionId").exists())
            .andExpect(jsonPath("$.journeyState").value("quote_started"))
            .andExpect(jsonPath("$.missingFields").isNotEmpty());
    }

    @Test
    void getQuoteSessionGated() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();

        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.quoteId").value(qid))
            .andExpect(jsonPath("$.sessionId").doesNotExist())
            .andExpect(jsonPath("$.currentOutcome").doesNotExist()); // present-but-null

        mvc.perform(get("/quotes/" + qid)).andExpect(status().isNotFound());
        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", "wrong")).andExpect(status().isNotFound());
    }

    @Test
    void patchDeepMergesAndDropsRegistrationFromMissing() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();

        mvc.perform(patch("/quotes/" + qid)
                .header("X-Session-Id", sid)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"patch\":{\"vehicle\":{\"registration\":\"FX19ZTC\"}}}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.journeyState").value("collecting"))
            .andExpect(jsonPath("$.missingFields", not(hasItem("vehicle.registration"))))
            .andExpect(jsonPath("$.missingFields", hasItem("vehicle.make")));
    }

    @Test
    void patchWrongSessionIsNotFound() throws Exception {
        JsonNode created = create();
        mvc.perform(patch("/quotes/" + created.get("quoteId").asText())
                .header("X-Session-Id", "wrong")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"patch\":{\"vehicle\":{\"registration\":\"X\"}}}"))
            .andExpect(status().isNotFound());
    }

    @Test
    void vehicleLookup() throws Exception {
        mvc.perform(get("/vehicles/FX19ZTC"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.make").value("Ford"))
            .andExpect(jsonPath("$.model").value("Focus"))
            .andExpect(jsonPath("$.registration").value("FX19ZTC"));
    }

    @Test
    void addressLookup() throws Exception {
        mvc.perform(get("/addresses").param("postcode", "RG1 1AA"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.postcode").value("RG1 1AA"))
            .andExpect(jsonPath("$.candidates").isArray())
            .andExpect(jsonPath("$.candidates[1]").exists());
    }

    @Test
    void demoQuoteResolvesWithDemoSessionAndIsPricedAndQuoted() throws Exception {
        // The stable demo GUID is pre-priced on seed (Slice 5): a full sample
        // that ends up quoted with a visible pricing object.
        mvc.perform(get("/quotes/" + DemoSeeder.DEMO_QUOTE_ID).header("X-Session-Id", DemoSeeder.DEMO_SESSION_ID))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.quoteId").value(DemoSeeder.DEMO_QUOTE_ID))
            .andExpect(jsonPath("$.missingFields", is(empty())))
            .andExpect(jsonPath("$.journeyState").value("quoted"))
            .andExpect(jsonPath("$.currentOutcome").value("quote"))
            .andExpect(jsonPath("$.pricing.annualPremium").exists())
            .andExpect(jsonPath("$.pricing.currency").value("GBP"))
            .andExpect(jsonPath("$.pricing.outcome").value("quote"));
    }

    @Test
    void demoQuoteWrongSessionIsNotFound() throws Exception {
        mvc.perform(get("/quotes/" + DemoSeeder.DEMO_QUOTE_ID).header("X-Session-Id", "nope"))
            .andExpect(status().isNotFound());
    }

    @Test
    void priceCompleteQuoteReturnsPricingObjectQuotedAndEmitsQuotePriced() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        patchComplete(qid, sid, completePatch());

        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.outcome").value("quote"))
            .andExpect(jsonPath("$.currency").value("GBP"))
            .andExpect(jsonPath("$.iptIncluded").value(true))
            .andExpect(jsonPath("$.annualPremium").exists())
            .andExpect(jsonPath("$.monthly.instalments").value(10))
            .andExpect(jsonPath("$.totalExcess").exists())
            .andExpect(jsonPath("$.breakdown").isArray());

        // GET reflects quoted + pricing.
        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.journeyState").value("quoted"))
            .andExpect(jsonPath("$.currentOutcome").value("quote"))
            .andExpect(jsonPath("$.pricing.outcome").value("quote"));

        // QUOTE_PRICED domain event emitted (payload has quoteId + outcome, no sessionId).
        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .anyMatch(e -> e.type().equals("QUOTE_PRICED")
                && qid.equals(e.payload().get("quoteId"))
                && "quote".equals(e.payload().get("outcome")));
        org.assertj.core.api.Assertions.assertThat(eventStore.all())
            .noneMatch(e -> e.payload().toString().contains(sid));
    }

    @Test
    void priceHighValueVehicleRefers() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        com.fasterxml.jackson.databind.node.ObjectNode patch = completePatch();
        ((com.fasterxml.jackson.databind.node.ObjectNode) patch.get("vehicle")).put("value", 90000);
        patchComplete(qid, sid, patch);

        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.outcome").value("refer"))
            .andExpect(jsonPath("$.reasons").isNotEmpty());

        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", sid))
            .andExpect(jsonPath("$.journeyState").value("referred"));
    }

    @Test
    void priceUnder18Declines() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();
        com.fasterxml.jackson.databind.node.ObjectNode patch = completePatch();
        ((com.fasterxml.jackson.databind.node.ObjectNode) patch.get("customer"))
            .put("dateOfBirth", java.time.LocalDate.now().minusYears(17).toString());
        patchComplete(qid, sid, patch);

        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.outcome").value("decline"))
            .andExpect(jsonPath("$.reasons").isNotEmpty());

        mvc.perform(get("/quotes/" + qid).header("X-Session-Id", sid))
            .andExpect(jsonPath("$.journeyState").value("declined"));
    }

    @Test
    void priceWrongOrMissingSessionIsNotFound() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        mvc.perform(post("/quotes/" + qid + "/price")).andExpect(status().isNotFound());
        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", "wrong"))
            .andExpect(status().isNotFound());
    }

    @Test
    void priceIncompleteQuoteIsUnprocessableWithMissingFields() throws Exception {
        JsonNode created = create();
        String qid = created.get("quoteId").asText();
        String sid = created.get("sessionId").asText();

        mvc.perform(post("/quotes/" + qid + "/price").header("X-Session-Id", sid))
            .andExpect(status().isUnprocessableEntity())
            .andExpect(jsonPath("$.error").value("not_ready_to_price"))
            .andExpect(jsonPath("$.missingFields").isNotEmpty());
    }

    private JsonNode create() throws Exception {
        MvcResult res = mvc.perform(post("/quotes")).andExpect(status().isCreated()).andReturn();
        return mapper.readTree(res.getResponse().getContentAsString());
    }

    /** Patch the quote to mandatory-completeness; assert no missing fields remain. */
    private void patchComplete(String qid, String sid, com.fasterxml.jackson.databind.node.ObjectNode patch) throws Exception {
        com.fasterxml.jackson.databind.node.ObjectNode body = mapper.createObjectNode();
        body.set("patch", patch);
        mvc.perform(patch("/quotes/" + qid)
                .header("X-Session-Id", sid)
                .contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(body)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.missingFields", is(empty())))
            .andExpect(jsonPath("$.journeyState").value("ready_to_price"));
    }

    /** A whole-model patch filling every mandatory field with realistic values. */
    private com.fasterxml.jackson.databind.node.ObjectNode completePatch() {
        com.fasterxml.jackson.databind.node.ObjectNode patch = mapper.createObjectNode();
        for (String path : com.acme.platform.quote.RequiredFields.MANDATORY_FIELDS) {
            setPath(patch, path, "filled");
        }
        // Realistic rating/underwriting inputs for a clean quote.
        setPath(patch, "customer.dateOfBirth", "1990-01-01");
        setPath(patch, "customer.address.postcode", "RG1 1AA");
        setNumber(patch, "vehicle.value", 12000);
        setNumber(patch, "vehicle.annualMileage", 8000);
        setNumber(patch, "history.claimsLast3Years", 0);
        setNumber(patch, "history.offencesLast5Years", 0);
        setPath(patch, "cover.coverLevel", "Comprehensive");
        setNumber(patch, "cover.voluntaryExcess", 250);
        setNumber(patch, "driver.ncdYears", 5);
        return patch;
    }

    private void setPath(com.fasterxml.jackson.databind.node.ObjectNode root, String dotPath, String value) {
        com.fasterxml.jackson.databind.node.ObjectNode node = walk(root, dotPath);
        node.put(lastSegment(dotPath), value);
    }

    private void setNumber(com.fasterxml.jackson.databind.node.ObjectNode root, String dotPath, int value) {
        com.fasterxml.jackson.databind.node.ObjectNode node = walk(root, dotPath);
        node.put(lastSegment(dotPath), value);
    }

    private com.fasterxml.jackson.databind.node.ObjectNode walk(com.fasterxml.jackson.databind.node.ObjectNode root, String dotPath) {
        String[] parts = dotPath.split("\\.");
        com.fasterxml.jackson.databind.node.ObjectNode cur = root;
        for (int i = 0; i < parts.length - 1; i++) {
            if (!(cur.get(parts[i]) instanceof com.fasterxml.jackson.databind.node.ObjectNode)) {
                cur.set(parts[i], mapper.createObjectNode());
            }
            cur = (com.fasterxml.jackson.databind.node.ObjectNode) cur.get(parts[i]);
        }
        return cur;
    }

    private static String lastSegment(String dotPath) {
        String[] parts = dotPath.split("\\.");
        return parts[parts.length - 1];
    }
}
