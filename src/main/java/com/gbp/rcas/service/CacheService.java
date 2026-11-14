package com.gbp.rcas.service;

import java.util.function.Supplier;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

public interface CacheService {
    <T> Mono<T> getCache(Long id, String cacheName, Supplier<Mono<T>> retriever, Class<T> cls);

    <T> Flux<T> getCache(Long id, String cacheName, Class<T> cls, Supplier<Flux<T>> retriever);

}
