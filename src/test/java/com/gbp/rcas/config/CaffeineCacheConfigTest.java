package com.gbp.rcas.config;

import com.github.benmanes.caffeine.cache.Ticker;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;

import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;
import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class CaffeineCacheConfigTest {

    private static final long CACHE_ID = 1L;

    @Test
    void expiresUserAndSubscriptionCachesAfterFiveMinutesOfInactivityByDefault() {
        new ApplicationContextRunner()
                .withUserConfiguration(CaffeineCacheConfig.class)
                .run(context -> {
                    AtomicLong tickerNanos = new AtomicLong();
                    CacheManager cacheManager = context.getBean(CaffeineCacheConfig.class)
                            .cacheManager(ticker(tickerNanos));

                    assertExpiresAfterAccess(cacheManager.getCache(CACHE_NAME_USER), tickerNanos);
                    assertExpiresAfterAccess(cacheManager.getCache(CACHE_NAME_SUBSCRIPTION), tickerNanos);
                });
    }

    @Test
    void configuresCaffeineExpirationInMinutes() {
        new ApplicationContextRunner()
                .withUserConfiguration(CaffeineCacheConfig.class)
                .withPropertyValues("cache.caffeine.expiration.minutes=2")
                .run(context -> {
                    AtomicLong tickerNanos = new AtomicLong();
                    CacheManager cacheManager = context.getBean(CaffeineCacheConfig.class)
                            .cacheManager(ticker(tickerNanos));
                    Cache userCache = cacheManager.getCache(CACHE_NAME_USER);
                    userCache.put(CACHE_ID, "user");

                    advance(tickerNanos, Duration.ofMinutes(2).plusNanos(1));

                    assertNull(userCache.get(CACHE_ID, String.class));
                });
    }

    private void assertExpiresAfterAccess(Cache cache, AtomicLong tickerNanos) {
        cache.put(CACHE_ID, "cached");

        advance(tickerNanos, Duration.ofMinutes(4));
        assertEquals("cached", cache.get(CACHE_ID, String.class));

        advance(tickerNanos, Duration.ofMinutes(4));
        assertEquals("cached", cache.get(CACHE_ID, String.class));

        advance(tickerNanos, Duration.ofMinutes(5).plusNanos(1));
        assertNull(cache.get(CACHE_ID, String.class));
    }

    private Ticker ticker(AtomicLong tickerNanos) {
        return tickerNanos::get;
    }

    private void advance(AtomicLong tickerNanos, Duration duration) {
        tickerNanos.addAndGet(duration.toNanos());
    }
}
