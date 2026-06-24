package com.acme.platform.quote;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.acme.platform.events.Event;
import com.acme.platform.events.EventStore;
import com.acme.platform.pricing.PricingService;
import com.acme.platform.pricing.UnderwritingEngine;
import com.acme.platform.vendor.MockVendorClient;

class QuoteServiceTest {

    private EventStore events;
    private SessionStore sessions;
    private QuoteService service;

    @BeforeEach
    void setUp() {
        events = new EventStore();
        sessions = new SessionStore();
        MockVendorClient vendor = new MockVendorClient();
        PricingService pricing = new PricingService(vendor, new UnderwritingEngine());
        service = new QuoteService(sessions, events, pricing, vendor);
    }

    @Test
    void createReturnsStartedStateWithSessionAndEmitsDomainEvent() {
        Map<String, Object> created = service.createQuote();

        assertThat(created).containsKeys("quoteId", "sessionId", "journeyState", "missingFields");
        assertThat(created.get("journeyState")).isEqualTo("quote_started");
        assertThat((List<?>) created.get("missingFields")).isNotEmpty();

        List<Event> domain = events.all().stream().filter(e -> e.type().equals("QUOTE_CREATED")).toList();
        assertThat(domain).hasSize(1);
        // sessionId must never appear in any event payload.
        String sid = (String) created.get("sessionId");
        assertThat(events.all()).noneMatch(e -> e.payload().toString().contains(sid));
    }

    @Test
    void getRequiresMatchingSession() {
        Map<String, Object> created = service.createQuote();
        String qid = (String) created.get("quoteId");
        String sid = (String) created.get("sessionId");

        assertThat(service.getQuote(qid, sid)).isNotNull();
        assertThat(service.getQuote(qid, "wrong")).isNull();
        assertThat(service.getQuote(qid, "")).isNull();
        assertThat(service.getQuote(qid, null)).isNull();
        // get state never leaks sessionId.
        assertThat(service.getQuote(qid, sid)).doesNotContainKey("sessionId");
    }

    @Test
    void patchDeepMergesPreservingSiblingsAndRecomputesState() {
        Map<String, Object> created = service.createQuote();
        String qid = (String) created.get("quoteId");
        String sid = (String) created.get("sessionId");

        service.applyPatch(qid, sid, Map.of("customer", Map.of("firstName", "Sam")));
        Map<String, Object> state = service.applyPatch(qid, sid, Map.of("customer", Map.of("surname", "Sample")));

        QuoteRecord rec = sessions.get(qid, sid);
        assertThat(rec.data().get("customer")).isEqualTo(Map.of("firstName", "Sam", "surname", "Sample"));
        assertThat(state.get("journeyState")).isEqualTo("collecting");
    }

    @Test
    void patchWrongSessionIsNotFound() {
        Map<String, Object> created = service.createQuote();
        String qid = (String) created.get("quoteId");
        assertThat(service.applyPatch(qid, "wrong", Map.of("customer", Map.of("firstName", "X")))).isNull();
    }

    @Test
    void deepMergeDropsNullAndEmptyLeavesNeverBlankingSiblings() {
        Map<String, Object> base = new LinkedHashMap<>();
        base.put("vehicle", new LinkedHashMap<>(Map.of("make", "Ford", "model", "Focus")));

        Map<String, Object> patch = new LinkedHashMap<>();
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("make", null);     // dropped — must not blank existing
        v.put("model", "  ");    // blank string dropped
        v.put("fuel", "Petrol"); // applied
        patch.put("vehicle", v);

        QuoteService.deepMerge(base, patch);

        assertThat(base.get("vehicle")).isEqualTo(Map.of("make", "Ford", "model", "Focus", "fuel", "Petrol"));
    }

    @Test
    void fullyPopulatedReachesReadyToPrice() {
        QuoteRecord rec = sessions.create();
        // missingFields for an empty quote = all mandatory; patch them all in.
        Map<String, Object> patch = new LinkedHashMap<>();
        for (String path : RequiredFields.MANDATORY_FIELDS) {
            put(patch, path, "X");
        }
        Map<String, Object> state = service.applyPatch(rec.quoteId(), rec.sessionId(), patch);
        assertThat((List<?>) state.get("missingFields")).isEmpty();
        assertThat(state.get("journeyState")).isEqualTo("ready_to_price");
    }

    @Test
    void priceUnknownSessionIsNotFound() {
        Map<String, Object> created = service.createQuote();
        String qid = (String) created.get("quoteId");
        assertThat(service.priceQuote(qid, "wrong").status()).isEqualTo(QuoteService.PriceStatus.NOT_FOUND);
        assertThat(service.priceQuote("nope", "nope").status()).isEqualTo(QuoteService.PriceStatus.NOT_FOUND);
    }

    @Test
    void priceIncompleteQuoteReportsMissingFields() {
        Map<String, Object> created = service.createQuote();
        String qid = (String) created.get("quoteId");
        String sid = (String) created.get("sessionId");

        QuoteService.PriceResult result = service.priceQuote(qid, sid);
        assertThat(result.status()).isEqualTo(QuoteService.PriceStatus.INCOMPLETE);
        assertThat((List<?>) result.state().get("missingFields")).isNotEmpty();
        assertThat(result.pricing()).isNull();
    }

    @Test
    void priceCompleteQuoteWritesPricingSetsQuotedAndEmitsQuotePriced() {
        QuoteRecord rec = sessions.create(completeQuoteData());
        QuoteService.PriceResult result = service.priceQuote(rec.quoteId(), rec.sessionId());

        assertThat(result.status()).isEqualTo(QuoteService.PriceStatus.PRICED);
        assertThat(result.pricing().get("outcome")).isEqualTo("quote");
        assertThat(result.pricing().get("currency")).isEqualTo("GBP");
        assertThat(result.state().get("journeyState")).isEqualTo("quoted");
        assertThat(result.state().get("currentOutcome")).isEqualTo("quote");

        // QUOTE_PRICED emitted with quoteId + outcome, never the sessionId.
        List<Event> priced = events.all().stream().filter(e -> e.type().equals("QUOTE_PRICED")).toList();
        assertThat(priced).hasSize(1);
        assertThat(priced.get(0).payload()).containsEntry("quoteId", rec.quoteId());
        assertThat(priced.get(0).payload()).containsEntry("outcome", "quote");
        assertThat(events.all()).noneMatch(e -> e.payload().toString().contains(rec.sessionId()));

        // GET reflects the priced state, including the pricing object.
        Map<String, Object> got = service.getQuote(rec.quoteId(), rec.sessionId());
        assertThat(got.get("journeyState")).isEqualTo("quoted");
        assertThat(got).containsKey("pricing");
    }

    /** A fully-populated, mandatory-complete quote yielding a clean quote outcome. */
    static Map<String, Object> completeQuoteData() {
        Map<String, Object> data = new LinkedHashMap<>();
        for (String path : RequiredFields.MANDATORY_FIELDS) {
            put(data, path, "filled");
        }
        // Realistic rating/underwriting inputs for a clean quote.
        put(data, "customer.dateOfBirth", "1990-01-01");
        put(data, "customer.address.postcode", "RG1 1AA");
        put(data, "vehicle.value", 12000);
        put(data, "vehicle.annualMileage", 8000);
        put(data, "history.claimsLast3Years", 0);
        put(data, "history.offencesLast5Years", 0);
        put(data, "cover.coverLevel", "Comprehensive");
        put(data, "cover.voluntaryExcess", 250);
        put(data, "driver.ncdYears", 5);
        return data;
    }

    @SuppressWarnings("unchecked")
    private static void put(Map<String, Object> root, String dotPath, Object value) {
        String[] parts = dotPath.split("\\.");
        Map<String, Object> cur = root;
        for (int i = 0; i < parts.length - 1; i++) {
            cur = (Map<String, Object>) cur.computeIfAbsent(parts[i], k -> new LinkedHashMap<>());
        }
        cur.put(parts[parts.length - 1], value);
    }
}
