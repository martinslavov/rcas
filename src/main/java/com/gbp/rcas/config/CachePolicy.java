package com.gbp.rcas.config;

import java.time.Clock;
import java.time.Duration;
import java.util.Objects;

public record CachePolicy(Duration redisExpiration, Duration maxLifetime, Clock clock) {

    public CachePolicy {
        Objects.requireNonNull(redisExpiration);
        Objects.requireNonNull(maxLifetime);
        Objects.requireNonNull(clock);
        if (redisExpiration.isZero() || redisExpiration.isNegative()
                || maxLifetime.isZero() || maxLifetime.isNegative()) {
            throw new IllegalArgumentException("Cache expiration and maximum lifetime must be positive");
        }
    }
}
