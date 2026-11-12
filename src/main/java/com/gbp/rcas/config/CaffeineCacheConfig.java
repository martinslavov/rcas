package com.gbp.rcas.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.Ticker;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.TimeUnit;

import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;

@Configuration
@EnableCaching
public class CaffeineCacheConfig {

    @Value("${cache.caffeine.expiration.minutes:5}")
    private long cacheExpirationMinutes;

    @Bean
    public CacheManager cacheManager() {
        return cacheManager(Ticker.systemTicker());
    }

    CacheManager cacheManager(Ticker ticker) {
        Caffeine<Object, Object> caffeineCacheBuilder =
                Caffeine.newBuilder()
                        .ticker(ticker)
                        .expireAfterAccess(cacheExpirationMinutes, TimeUnit.MINUTES);

        CaffeineCacheManager cacheManager =
                new CaffeineCacheManager(
                        CACHE_NAME_USER, CACHE_NAME_SUBSCRIPTION);
        cacheManager.setCaffeine(caffeineCacheBuilder);
        return cacheManager;
    }
}
