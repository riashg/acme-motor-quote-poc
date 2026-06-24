package com.acme.platform.vendor;

import java.time.LocalDate;
import java.time.Period;
import java.time.format.DateTimeParseException;

/**
 * Small, neutral coercion helpers for reading values out of the loosely-typed
 * whole-model quote payload (nested {@code Map}s where leaves may arrive as
 * {@code Number}s or {@code String}s). Shared by the rating mock and the
 * platform-owned underwriting engine so both read inputs identically.
 */
public final class QuoteValues {

    private QuoteValues() {
    }

    /** Age in whole years from an ISO {@code yyyy-MM-dd} date of birth; {@code null} if unparseable. */
    public static Integer ageFromDob(Object dobValue) {
        if (!(dobValue instanceof String s) || s.isBlank()) {
            return null;
        }
        try {
            LocalDate dob = LocalDate.parse(s.strip());
            return Period.between(dob, LocalDate.now()).getYears();
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    /** Best-effort integer from a Number or numeric String; {@code fallback} otherwise. */
    public static int intValue(Object value, int fallback) {
        if (value instanceof Number n) {
            return n.intValue();
        }
        if (value instanceof String s && !s.isBlank()) {
            try {
                return (int) Double.parseDouble(s.strip());
            } catch (NumberFormatException ignored) {
                return fallback;
            }
        }
        return fallback;
    }
}
