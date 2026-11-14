package com.gbp.rcas.config;

import com.github.benmanes.caffeine.cache.Caffeine;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.TimeUnit;
import java.time.Clock;
import java.time.Duration;

import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;

@Configuration
@EnableCaching
public class CaffeineCacheConfig {

    @Value("${cache.expiration.hours:24}")
    private int cacheExpiration;

    @Bean
    public CacheManager cacheManager() {
        Caffeine<Object, Object> caffeineCacheBuilder =
                Caffeine.newBuilder()
                        .recordStats()
                        .expireAfterAccess(
                                cacheExpiration, TimeUnit.HOURS);

        CaffeineCacheManager cacheManager =
                new CaffeineCacheManager(
                        CACHE_NAME_USER, CACHE_NAME_SUBSCRIPTION);
        cacheManager.setCaffeine(caffeineCacheBuilder);
        return cacheManager;
    }

    @Bean
    public Clock cacheClock() {
        return Clock.systemUTC();
    }

    @Bean
    public CachePolicy cachePolicy(
            @Value("${cache.expiration.hours:24}") long cacheExpirationHours,
            @Value("${cache.max-lifetime.hours:24}") long maxLifetimeHours,
            Clock cacheClock) {
        return new CachePolicy(Duration.ofHours(cacheExpirationHours), Duration.ofHours(maxLifetimeHours), cacheClock);
    }
}
