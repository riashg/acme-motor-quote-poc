package com.acme.platform.purchase;

import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

/**
 * Mints and resolves <b>signed, GUID-addressed purchase links</b> (brief §9,
 * Slice 7).
 *
 * <p>A purchase token is a <b>high-entropy capability</b> — 32 random bytes from
 * {@link SecureRandom}, url-safe base64 — minted <b>separately from the
 * sessionId</b>. It is the sole capability for the strict landing page: whoever
 * holds the token in the URL can render that quote, and nothing else. The token
 * maps {@code token → quoteId} only; resolving it never touches the session.
 *
 * <p>Storage is in-memory (PoC). The token is unguessable, so possession of the
 * URL is the access control — there are no user accounts (cf. {@code SessionStore}).
 */
@Component
public class PurchaseLinkService {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Base64.Encoder URL_ENCODER = Base64.getUrlEncoder().withoutPadding();

    private final Map<String, String> tokenToQuoteId = new ConcurrentHashMap<>();

    /**
     * Mint a fresh high-entropy purchase token for {@code quoteId} and store the
     * {@code token → quoteId} mapping. The token is the landing-page capability;
     * it is not derived from, and carries no trace of, the sessionId.
     */
    public String mintToken(String quoteId) {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        String token = URL_ENCODER.encodeToString(bytes);
        tokenToQuoteId.put(token, quoteId);
        return token;
    }

    /** Resolve a purchase token to its quoteId, or {@code null} if unknown. */
    public String resolve(String token) {
        if (token == null || token.isEmpty()) {
            return null;
        }
        return tokenToQuoteId.get(token);
    }

    /** Test helper: clear all stored tokens. */
    public void reset() {
        tokenToQuoteId.clear();
    }
}
