package com.acme.platform.quote;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

/**
 * Session-scoped quote store (in-memory). Quotes are keyed by {@code quoteId}
 * and bound to a <b>strong-entropy session id</b> (32 random bytes,
 * base64url-encoded, from {@link SecureRandom}). A quote is retrievable /
 * updatable <b>only</b> by presenting its session id; a missing/empty session,
 * an unknown id, or a mismatch all yield not-found — indistinguishable, so
 * existence is never revealed (brief §17.6).
 *
 * <p>There are no user accounts: the high-entropy session id is the sole access
 * control. Comparison is constant-time to avoid leaking the id by timing.
 */
@Component
public class SessionStore {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Base64.Encoder URL_ENCODER = Base64.getUrlEncoder().withoutPadding();

    private final Map<String, QuoteRecord> records = new ConcurrentHashMap<>();

    /** A GUID quote id (brief §9 — crypto.randomUUID style). */
    public static String newQuoteId() {
        return UUID.randomUUID().toString();
    }

    /** A strong-entropy session id (32 bytes → ~43 url-safe chars). */
    public static String newSessionId() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return URL_ENCODER.encodeToString(bytes);
    }

    public QuoteRecord create() {
        return create(new LinkedHashMap<>());
    }

    public QuoteRecord create(Map<String, Object> data) {
        QuoteRecord record = new QuoteRecord(newQuoteId(), newSessionId(), data);
        records.put(record.quoteId(), record);
        return record;
    }

    /** Insert/replace a record verbatim (used to self-seed the demo quote). */
    public QuoteRecord put(QuoteRecord record) {
        records.put(record.quoteId(), record);
        return record;
    }

    /**
     * Return the record only if the session id matches; else {@code null}.
     * A missing/empty session id, an unknown quote id, or a mismatch all yield
     * {@code null} — indistinguishable, so existence is never revealed.
     */
    public QuoteRecord get(String quoteId, String sessionId) {
        QuoteRecord record = records.get(quoteId);
        if (record == null || sessionId == null || sessionId.isEmpty()) {
            return null;
        }
        if (!constantTimeEquals(record.sessionId(), sessionId)) {
            return null;
        }
        return record;
    }

    /**
     * Resolve a record by quote id <b>without</b> a session, for the strict GUID
     * purchase/quote landing page (brief §17.6). The capability is the
     * high-entropy purchase token in the URL (resolved upstream to this id), not
     * the session; this never reveals or compares the session id. Returns
     * {@code null} for an unknown id. Do <b>not</b> use on the session-gated
     * quote routes — those must go through {@link #get}.
     */
    public QuoteRecord lookup(String quoteId) {
        return records.get(quoteId);
    }

    public boolean exists(String quoteId) {
        return records.containsKey(quoteId);
    }

    /** Test helper: clear all stored quotes. */
    public void reset() {
        records.clear();
    }

    private static boolean constantTimeEquals(String a, String b) {
        return MessageDigest.isEqual(
            a.getBytes(StandardCharsets.UTF_8),
            b.getBytes(StandardCharsets.UTF_8)
        );
    }
}
