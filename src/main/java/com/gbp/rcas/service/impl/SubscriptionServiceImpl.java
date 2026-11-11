package com.gbp.rcas.service.impl;

import com.gbp.rcas.config.KPI;
import com.gbp.rcas.enums.KPITypes;
import com.gbp.rcas.model.Subscription;
import com.gbp.rcas.repository.SubscriptionRepository;
import com.gbp.rcas.service.CacheService;
import com.gbp.rcas.service.SubscriptionService;

import org.springframework.stereotype.Service;

import java.util.List;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;


@Service(value = "subscriptionService")
public class SubscriptionServiceImpl implements SubscriptionService {

    private final SubscriptionRepository subscriptionRepository;
    private final KPI kpi;
    private final CacheService cacheService;

    public SubscriptionServiceImpl(SubscriptionRepository subscriptionRepository, KPI kpi, CacheService cacheService) {
        this.subscriptionRepository = subscriptionRepository;
        this.kpi = kpi;
        this.cacheService = cacheService;
    }

    @Override
    public Mono<Subscription> findById(Long id) {
        return kpi.measure(KPITypes.SUBSCRIPTION, "findById",
                () -> cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, () -> subscriptionRepository.findById(id), Subscription.class));
    }

    @Override
    public Flux<Subscription> findSubscriptionsByIds(List<Long> subscriptionIds) {

        return Flux.fromIterable(subscriptionIds)
                .flatMap(id -> kpi.measure(KPITypes.SUBSCRIPTION, "findSubscriptionsByIds",
                        () -> cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, () -> subscriptionRepository.findById(id), Subscription.class)));
    }

    @Override
    public Flux<Subscription> findSubscriptionsByUserId(Long userId) {

        return Flux.just(userId)
                .flatMap(id -> kpi.measure(KPITypes.SUBSCRIPTION, "findSubscriptionsByUserId",
                        () -> cacheService.getCache(userId * -1, CACHE_NAME_SUBSCRIPTION, Subscription.class,
                                () -> subscriptionRepository.findSubscriptionsByUserId(id))));
    }

}
