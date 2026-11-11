package com.gbp.rcas.service.impl;


import com.gbp.rcas.config.KPI;
import com.gbp.rcas.enums.KPITypes;
import com.gbp.rcas.model.User;
import com.gbp.rcas.repository.UserRepository;
import com.gbp.rcas.service.CacheService;
import com.gbp.rcas.service.UserService;

import org.springframework.stereotype.Service;

import reactor.core.publisher.Mono;

import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;

@Service(value = "userService")
public class UserServiceImpl implements UserService {

    private final UserRepository userRepository;
    private final KPI kpi;
    private final CacheService cacheService;

    public UserServiceImpl(UserRepository userRepository, KPI kpi, CacheService cacheService) {
        this.userRepository = userRepository;
        this.kpi = kpi;
        this.cacheService = cacheService;
    }

    @Override
    public Mono<User> findById(Long id) {
       return kpi.measure(KPITypes.USER, "findById",
               () -> cacheService.getCache(id, CACHE_NAME_USER, () -> userRepository.findById(id), User.class));
    }

}
