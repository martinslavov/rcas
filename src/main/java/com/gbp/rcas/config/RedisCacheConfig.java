package com.gbp.rcas.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.data.redis.connection.ReactiveRedisConnectionFactory;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import org.springframework.data.redis.serializer.GenericToStringSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

@Configuration
public class RedisCacheConfig {

    @Bean
    public ReactiveRedisTemplate<String, String> redisCacheTemplate(
            ReactiveRedisConnectionFactory redisConnectionFactory) {
        var template = new ReactiveRedisTemplate<>(
                redisConnectionFactory,
                RedisSerializationContext.<String, String>newSerializationContext(new StringRedisSerializer())
                                         .hashKey(new GenericToStringSerializer<>(Long.class))
                                         .hashValue(new StringRedisSerializer())
                                         .build()
        );
        return template;
    }

    @Bean
    public ReactiveHashOperations<String, Long, String> hashOperations(
            @Qualifier("redisCacheTemplate") ReactiveRedisTemplate<String, String> redisCacheTemplate) {
        return redisCacheTemplate.opsForHash();
    }

}
