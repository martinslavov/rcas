package com.gbp.rcas.service.impl;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tags;
import io.micrometer.core.instrument.Timer;

final class CacheMetrics {

    private final MeterRegistry registry;

    CacheMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    Timer.Sample start() {
        return Timer.start(registry);
    }

    void recordLookup(Timer.Sample sample, String layer, String cache, String operation, String outcome) {
        record(sample, "rcas.cache.lookup",
                Tags.of("layer", layer, "cache", cache, "operation", operation), outcome);
    }

    void recordDatabaseRead(Timer.Sample sample, String cache, String operation, String outcome) {
        record(sample, "rcas.database.read", Tags.of("cache", cache, "operation", operation), outcome);
    }

    void recordCacheWrite(Timer.Sample sample, String layer, String cache, String operation, String outcome) {
        record(sample, "rcas.cache.write",
                Tags.of("layer", layer, "cache", cache, "operation", operation), outcome);
    }

    void recordTtlRefresh(Timer.Sample sample, String cache, String operation, String trigger, String outcome) {
        record(sample, "rcas.cache.ttl.refresh",
                Tags.of("cache", cache, "operation", operation, "trigger", trigger), outcome);
    }

    void recordLogicalRead(String cache, String operation, String source, String outcome) {
        Counter.builder("rcas.cache.logical.read")
                .tags("cache", cache, "operation", operation, "source", source, "outcome", outcome)
                .register(registry)
                .increment();
    }

    void recordRedisFallback(String cache, String operation) {
        Counter.builder("rcas.cache.redis.fallback")
                .tags("cache", cache, "operation", operation, "reason", "lookup_error")
                .register(registry)
                .increment();
    }

    private void record(Timer.Sample sample, String name, Tags tags, String outcome) {
        Timer timer = Timer.builder(name)
                .tags(tags.and("outcome", outcome))
                .publishPercentileHistogram()
                .register(registry);
        sample.stop(timer);
    }
}
