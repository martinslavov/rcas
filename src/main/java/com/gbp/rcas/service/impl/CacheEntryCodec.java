package com.gbp.rcas.service.impl;

import tools.jackson.databind.ObjectMapper;

import reactor.core.publisher.Mono;

final class CacheEntryCodec {

    private final ObjectMapper objectMapper;

    CacheEntryCodec(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    Mono<String> encode(CacheEntry entry) {
        return serialize(entry.value())
                .flatMap(payload -> serialize(new CacheEntryEnvelope(entry.cachedAtEpochMillis(), payload)));
    }

    <T> Mono<CacheEntry> decodeItem(String json, Class<T> cls) {
        return deserialize(json, CacheEntryEnvelope.class)
                .flatMap(envelope -> {
                    if (envelope.payload() == null) {
                        return Mono.error(new IllegalArgumentException("Cache entry has no timestamped payload"));
                    }
                    return deserialize(envelope.payload(), cls)
                            .map(value -> new CacheEntry(envelope.cachedAtEpochMillis(), value));
                });
    }

    <T> Mono<CacheEntry> decodeList(String json, Class<T> cls) {
        return deserialize(json, CacheEntryEnvelope.class)
                .flatMap(envelope -> {
                    if (envelope.payload() == null) {
                        return Mono.error(new IllegalArgumentException("Cache entry has no timestamped payload"));
                    }
                    return deserializeList(envelope.payload(), cls)
                            .map(values -> new CacheEntry(envelope.cachedAtEpochMillis(), values));
                });
    }

    private <T> Mono<String> serialize(T value) {
        return Mono.fromCallable(() -> objectMapper.writeValueAsString(value));
    }

    private <T> Mono<T> deserialize(String json, Class<T> cls) {
        return Mono.fromCallable(() -> objectMapper.readValue(json, cls));
    }

    private <T> Mono<java.util.List<T>> deserializeList(String json, Class<T> cls) {
        var listType = objectMapper.getTypeFactory().constructCollectionType(java.util.List.class, cls);
        return Mono.fromCallable(() -> objectMapper.readValue(json, listType));
    }
}
