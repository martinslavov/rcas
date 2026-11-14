package com.gbp.rcas.service.impl;

public record CacheEntryEnvelope(long cachedAtEpochMillis, String payload) {
}
