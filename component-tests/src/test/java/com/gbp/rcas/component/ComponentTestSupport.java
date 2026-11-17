package com.gbp.rcas.component;

import org.junit.jupiter.api.BeforeAll;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Component tests call the running service (started with docker compose), so they need no Spring context.
 * The base URL can be overridden with the RCAS_BASE_URL environment variable.
 */
abstract class ComponentTestSupport {

    private static final int READY_TIMEOUT_SECONDS = 90;

    private static final String BASE_URL =
            System.getenv().getOrDefault("RCAS_BASE_URL", "http://localhost:8080/app");

    private static final HttpClient CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    @BeforeAll
    static void waitUntilServiceIsReady() {
        long deadlineNanos = System.nanoTime() + Duration.ofSeconds(READY_TIMEOUT_SECONDS).toNanos();
        IllegalStateException lastFailure = null;

        while (System.nanoTime() < deadlineNanos) {
            try {
                Response health = get("/actuator/health");
                if (health.status() == 200) {
                    JsonNode body = health.json();
                    if ("UP".equals(body.path("status").asText())
                            && "UP".equals(body.path("components").path("r2dbc").path("status").asText())
                            && "UP".equals(body.path("components").path("redis").path("status").asText())) {
                        return;
                    }
                }
                lastFailure = new IllegalStateException("Health endpoint is not fully UP yet");
            } catch (IllegalStateException ex) {
                lastFailure = ex;
            }

            try {
                Thread.sleep(1000);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Interrupted while waiting for service readiness", ex);
            }
        }

        throw new IllegalStateException("Timed out waiting for service readiness", lastFailure);
    }

    record Response(int status, String body) {
        JsonNode json() {
            return MAPPER.readTree(body);
        }
    }

    static Response get(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(BASE_URL + path))
                .timeout(Duration.ofSeconds(10))
                .header("Accept", "application/json")
                .GET()
                .build();
        try {
            HttpResponse<String> response = CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
            return new Response(response.statusCode(), response.body());
        } catch (IOException e) {
            throw new IllegalStateException("Request failed: " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted: " + request.uri(), e);
        }
    }
}
