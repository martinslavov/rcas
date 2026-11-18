package com.gbp.rcas.repository;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.MountableFile;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

class UserPartitionTest {
    private static final PostgreSQLContainer<?> DATABASE = new PostgreSQLContainer<>("postgres:15.2")
            .withDatabaseName("testdb").withUsername("test").withPassword("test")
            .withCopyFileToContainer(MountableFile.forHostPath("db.migration/performance_vacuum_database.sql"),
                    "/tmp/performance_vacuum_database.sql");

    @BeforeAll
    static void start() {
        DATABASE.start();
    }

    @AfterAll
    static void stop() {
        DATABASE.stop();
    }

    @BeforeEach
    void reset() throws Exception {
        execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public");
        execute(Files.readString(Path.of("db.migration/init.sql")));
        execute(Files.readString(Path.of("db.migration/V2__InsertUser.sql")));
    }

    @Test
    void seedUsersAreRoutedToThreeDailyPartitions() throws Exception {
        assertThat(number("SELECT count(DISTINCT tableoid) FROM user_t")).isEqualTo(3);
        assertThat(number("SELECT count(*) FROM user_t WHERE tableoid::regclass::text = "
                + "'user_t_' || to_char(created_on, 'YYYYMMDD')")).isEqualTo(3);
        assertThat(number("SELECT count(*) FROM user_t WHERE id = 1 AND username = 'martin'")).isEqualTo(1);
        execute(Files.readString(Path.of("db.migration/V2__InsertUser.sql")));
        assertThat(number("SELECT count(*) FROM user_t")).isEqualTo(3);
    }

    @Test
    void globalIdUsernameAndEmailRemainUniqueAcrossDays() throws Exception {
        assertUniqueViolation("INSERT INTO user_t VALUES (1, 'other', 'password', 'other@example.test', CURRENT_DATE)");
        assertUniqueViolation("INSERT INTO user_t VALUES (100, 'martin', 'password', 'other@example.test', CURRENT_DATE)");
        assertUniqueViolation("INSERT INTO user_t VALUES (100, 'other', 'password', 'slavoff.martin@gmail.com', CURRENT_DATE)");
        assertThat(number("SELECT count(*) FROM user_identity")).isEqualTo(3);
    }

    @Test
    void registryTracksUpdatesMovesDeletesAndTruncateAndCannotBeBypassed() throws Exception {
        execute("UPDATE user_t SET created_on = CURRENT_DATE, username = 'renamed' WHERE id = 1");
        assertThat(number("SELECT count(*) FROM user_identity WHERE id = 1 AND username = 'renamed' "
                + "AND created_on = CURRENT_DATE")).isEqualTo(1);
        assertThrows(SQLException.class, () -> execute("DELETE FROM user_identity WHERE id = 1"));
        assertThrows(SQLException.class, () -> execute("UPDATE user_identity SET username = 'invalid' WHERE id = 1"));
        execute("DELETE FROM user_t WHERE id = 1");
        assertThat(number("SELECT count(*) FROM user_identity WHERE id = 1")).isZero();
        execute("TRUNCATE user_t RESTART IDENTITY CASCADE");
        assertThat(number("SELECT count(*) FROM user_identity")).isZero();
    }

    @Test
    void unknownDatesUseDefaultAndCannotBeSilentlyRepartitioned() throws Exception {
        execute("INSERT INTO user_t VALUES (100, 'old', 'password', 'old@example.test', DATE '2000-01-01')");
        assertThat(number("SELECT count(*) FROM user_t_default WHERE id = 100")).isEqualTo(1);
        assertThrows(SQLException.class, () -> execute("SELECT ensure_user_day_partition(DATE '2000-01-01')"));
        assertThat(number("SELECT count(*) FROM user_t_default WHERE id = 100")).isEqualTo(1);
    }

    @Test
    void autovacuumTuningAppliesToAllUserAndSubscriptionLeaves() throws Exception {
        execute(Files.readString(Path.of("db.migration/V4__AutovacuumTuning.sql")));
        assertThat(number("SELECT count(*) FROM pg_class WHERE relname IN "
                + "('user_t_default', 'subscription_p0', 'subscription_p1', 'subscription_p2', 'subscription_p3') "
                + "AND 'autovacuum_enabled=true' = ANY(reloptions)")).isEqualTo(5);
        execute("SELECT ensure_user_day_partition(CURRENT_DATE + 1)");
        assertThat(number("SELECT count(*) FROM pg_class WHERE relname = 'user_t_' || to_char(CURRENT_DATE + 1, 'YYYYMMDD') "
                + "AND 'autovacuum_vacuum_cost_limit=800' = ANY(reloptions)")).isEqualTo(1);
    }

    @Test
    void performanceWorkloadIsRepeatableAndLeavesNineThousandUsersPerDay() throws Exception {
        var result = DATABASE.execInContainer("psql", "-U", DATABASE.getUsername(), "-d", DATABASE.getDatabaseName(),
                "-v", "ON_ERROR_STOP=1", "-f", "/tmp/performance_vacuum_database.sql");
        assertThat(result.getExitCode()).as(result.getStderr()).isZero();
        assertThat(number("SELECT count(*) FROM user_t WHERE username LIKE 'performance-user-%'")).isEqualTo(27000);
        result = DATABASE.execInContainer("psql", "-U", DATABASE.getUsername(), "-d", DATABASE.getDatabaseName(),
                "-v", "ON_ERROR_STOP=1", "-f", "/tmp/performance_vacuum_database.sql");
        assertThat(result.getExitCode()).as(result.getStderr()).isZero();
        assertThat(number("SELECT count(*) FROM user_t WHERE username LIKE 'performance-user-%'")).isEqualTo(27000);
        assertThat(number("SELECT count(*) FROM (SELECT tableoid FROM user_t WHERE username LIKE 'performance-user-%' "
                + "GROUP BY tableoid HAVING count(*) = 9000) partitions")).isEqualTo(3);
    }

    @Test
    void startupPopulatorIsRepeatableAndKeepsBothRegistriesConsistent() throws Exception {
        runPopulator();
        runPopulator();
        assertThat(number("SELECT count(*) FROM user_t WHERE id BETWEEN 1000 AND 1002")).isEqualTo(3);
        assertThat(number("SELECT count(DISTINCT tableoid) FROM user_t WHERE id BETWEEN 1000 AND 1002")).isEqualTo(3);
        assertThat(number("SELECT count(*) FROM user_identity")).isEqualTo(6);
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isEqualTo(4);
    }

    private void runPopulator() throws Exception {
        var builder = new ProcessBuilder("bash", "scripts/startup-service-records-populator.sh");
        builder.environment().put("COMPOSE", "bash src/test/resources/docker-compose-testcontainer.sh");
        builder.environment().put("TEST_POSTGRES_CONTAINER", DATABASE.getContainerId());
        builder.redirectErrorStream(true);
        Process process = builder.start();
        assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).as(new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8)).isZero();
    }

    private void assertUniqueViolation(String sql) {
        assertThat(assertThrows(SQLException.class, () -> execute(sql)).getSQLState()).isEqualTo("23505");
    }

    private Connection connection() throws SQLException {
        return DriverManager.getConnection(DATABASE.getJdbcUrl(), DATABASE.getUsername(), DATABASE.getPassword());
    }

    private void execute(String sql) throws SQLException {
        try (Connection connection = connection(); Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private long number(String sql) throws SQLException {
        try (Connection connection = connection(); Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(sql)) {
            result.next();
            return result.getLong(1);
        }
    }
}
