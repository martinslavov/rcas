---
name: software-engineering-principles
description: Apply practical software engineering principles when designing, implementing, reviewing, or refactoring Java and Spring Boot code. Use to evaluate responsibilities, abstractions, dependencies, boundaries, and complexity without applying patterns mechanically.
---

# Software Engineering Principles

Use this skill to make code easier to understand, change, test, and operate. Apply principles to the actual requirements and repository, not as a checklist of patterns to add. The best design is the simplest one that meets current needs while leaving reasonable room for likely change.

## Engineering rules

1. Never apply SOLID mechanically; use it to identify and correct concrete design friction.
2. Do not introduce an abstraction unless there is a concrete reason, such as a real variation point, a boundary to isolate, or a test seam that materially improves the design.
3. Prefer a simple, direct implementation over a sophisticated design that does not solve a present problem.
4. Avoid premature optimization. Measure a demonstrated bottleneck before trading clarity for performance.
5. Avoid speculative generalization: do not build for hypothetical requirements.
6. Prefer composition to inheritance unless substitutability and shared behavior make inheritance clearly advantageous.
7. Keep classes and methods focused on a coherent purpose, not on arbitrary size limits.
8. Minimize coupling and keep responsibilities and architectural boundaries clear.
9. Preserve the existing architecture, conventions, and public behavior unless there is a justified reason to change them.
10. More abstractions, interfaces, classes, and design patterns do not automatically mean better engineering.

## Decision workflow

For design, implementation, and refactoring:

1. Inspect the relevant code, tests, module boundaries, and repository conventions before proposing a change.
2. State the actual requirement or observed defect. Separate evidence from assumptions.
3. Identify only the principles relevant to that problem.
4. Consider realistic alternatives, including leaving the design as-is.
5. Compare their complexity, behavior, maintainability, extensibility, testability, and compatibility.
6. Choose the simplest option that addresses the requirement.
7. Explain significant design decisions and meaningful trade-offs.
8. Review the result for unnecessary indirection, speculative flexibility, and accidental behavior changes; run relevant tests.

In reviews, classify observations as:

- **Defect:** a demonstrated correctness, reliability, security, compatibility, or maintainability problem.
- **Risk or opportunity:** a plausible concern or future improvement, with its conditions stated.
- **Preference:** a stylistic alternative without a concrete negative impact. Do not present preferences as architectural defects.

## SOLID

SOLID is a set of heuristics for managing change and dependencies, not a requirement to create one interface or class per concept. Use the smallest change that removes real coupling, fragility, or responsibility overload.

### Single Responsibility Principle (SRP)

**Purpose.** A unit should have one coherent responsibility and change for one closely related reason. “Responsibility” is about the kind of policy or actor that drives change, not simply one method per class.

**Why it matters.** Unrelated changes in one class can break each other, complicate tests, and make the class difficult to understand.

**Common violations.** A service that validates a request, calculates domain policy, performs persistence, sends email, and formats an HTTP response; a “Utils” class accumulating unrelated operations.

Bad:

```java
class OrderService {
    void place(Order order) {
        if (order.items().isEmpty()) {
            throw new IllegalArgumentException("Order must contain items");
        }
        orderRepository.save(order);
        emailClient.send(order.customerEmail(), "Order received");
    }

    private final OrderRepository orderRepository;
    private final EmailClient emailClient;

    OrderService(OrderRepository orderRepository, EmailClient emailClient) {
        this.orderRepository = orderRepository;
        this.emailClient = emailClient;
    }
}
```

Improved, when notification delivery is a separate policy or operational concern:

```java
class PlaceOrder {
    private final OrderRepository orderRepository;
    private final OrderNotifier orderNotifier;

    PlaceOrder(OrderRepository orderRepository, OrderNotifier orderNotifier) {
        this.orderRepository = orderRepository;
        this.orderNotifier = orderNotifier;
    }

    void execute(Order order) {
        if (order.items().isEmpty()) {
            throw new IllegalArgumentException("Order must contain items");
        }
        orderRepository.save(order);
        orderNotifier.orderPlaced(order);
    }
}

interface OrderNotifier {
    void orderPlaced(Order order);
}
```

**Apply it.** Split a class when distinct policies change independently, or when a responsibility makes testing and reasoning materially harder. Keep closely related operations together; a small application service coordinating one use case can have a coherent responsibility.

**Avoid overuse.** Do not split every method into a class, or extract a trivial delegate solely to reduce line count. If separate responsibilities never vary independently and the split obscures the flow, keep them together.

### Open/Closed Principle (OCP)

**Purpose.** Keep stable code closed to repeated edits when a known kind of behavior varies; permit that variation through a suitable extension point.

**Why it matters.** A clear variation point can avoid risky conditionals spread across the codebase.

**Common violations.** Repeatedly editing a central switch in many locations for each supported payment method; creating a plugin framework for a fixed two-case rule.

Bad:

```java
class ShippingCost {
    int forOrder(String method, int weightGrams) {
        if (method.equals("standard")) {
            return 500 + weightGrams / 100;
        }
        if (method.equals("express")) {
            return 1200 + weightGrams / 100;
        }
        throw new IllegalArgumentException("Unknown shipping method: " + method);
    }
}
```

Improved, when shipping methods are independently added or configured:

```java
interface ShippingPolicy {
    int costInCents(int weightGrams);
}

final class StandardShipping implements ShippingPolicy {
    @Override
    public int costInCents(int weightGrams) {
        return 500 + weightGrams / 100;
    }
}

final class ExpressShipping implements ShippingPolicy {
    @Override
    public int costInCents(int weightGrams) {
        return 1200 + weightGrams / 100;
    }
}

final class ShippingCost {
    int forOrder(ShippingPolicy policy, int weightGrams) {
        return policy.costInCents(weightGrams);
    }
}
```

**Apply it.** First identify a real, repeated axis of change. Add an extension point when new variants are likely and can be represented by a stable contract. Keep exhaustive switches when the set is small, closed, and easier to understand.

**Avoid overuse.** Do not add factories, registries, reflection, or strategy hierarchies for speculative variants. An abstraction with one implementation and no meaningful boundary may only relocate a conditional.

### Liskov Substitution Principle (LSP)

**Purpose.** A subtype must be usable wherever its base type is expected without breaking that type's documented behavior or invariants.

**Why it matters.** Clients rely on base-type guarantees. A subtype that rejects valid inputs, weakens results, or surprises callers makes polymorphism unsafe.

**Common violations.** A subtype that throws `UnsupportedOperationException` for a base operation; a subtype that strengthens preconditions or changes observable semantics.

Bad:

```java
class MutableRectangle {
    private int width;
    private int height;

    void setWidth(int width) { this.width = width; }
    void setHeight(int height) { this.height = height; }
    int area() { return width * height; }
}

class Square extends MutableRectangle {
    @Override
    void setWidth(int width) {
        super.setWidth(width);
        super.setHeight(width);
    }

    @Override
    void setHeight(int height) {
        super.setWidth(height);
        super.setHeight(height);
    }
}
```

Improved, when callers need an area value rather than mutable dimensions:

```java
interface Shape {
    int area();
}

final class Rectangle implements Shape {
    private final int width;
    private final int height;

    Rectangle(int width, int height) {
        if (width < 0 || height < 0) {
            throw new IllegalArgumentException("Dimensions must be non-negative");
        }
        this.width = width;
        this.height = height;
    }

    @Override
    public int area() {
        return width * height;
    }
}

final class Square implements Shape {
    private final int side;

    Square(int side) {
        if (side < 0) {
            throw new IllegalArgumentException("Side must be non-negative");
        }
        this.side = side;
    }

    @Override
    public int area() {
        return side * side;
    }
}
```

**Apply it.** Document behavior in contracts; test subtypes against the same behavioral expectations as the parent. Prefer a smaller interface or composition if a subtype cannot honor all inherited operations.

**Avoid overuse.** Do not force inheritance just to share fields or implementation. If no client needs interchangeability, unrelated concrete types may be clearer.

### Interface Segregation Principle (ISP)

**Purpose.** Clients should depend only on operations they use. Interfaces should express cohesive client needs.

**Why it matters.** Large interfaces force implementations to carry irrelevant methods and make unrelated changes ripple through consumers.

**Common violations.** “Do everything” service interfaces; implementations with empty methods or `UnsupportedOperationException`; consumers injected with a broad interface for one operation.

Bad:

```java
interface Device {
    void print(String document);
    void scan(String document);
    void fax(String document);
}

final class BasicPrinter implements Device {
    public void print(String document) { System.out.println(document); }
    public void scan(String document) { throw new UnsupportedOperationException(); }
    public void fax(String document) { throw new UnsupportedOperationException(); }
}
```

Improved:

```java
interface Printer {
    void print(String document);
}

interface Scanner {
    String scan();
}

final class BasicPrinter implements Printer {
    @Override
    public void print(String document) {
        System.out.println(document);
    }
}
```

**Apply it.** Design interfaces around actual consumers and capabilities. Split a contract when different clients need different subsets or implementations cannot honor all methods.

**Avoid overuse.** Do not create a separate interface for every method or consumer when that increases indirection without reducing coupling. A cohesive, small interface may be enough.

### Dependency Inversion Principle (DIP)

**Purpose.** High-level policy should not depend directly on low-level details; both should depend on an abstraction that expresses the policy boundary.

**Why it matters.** Domain and application rules can remain stable when persistence, messaging, or external services change.

**Common violations.** Domain logic constructs a JDBC client or calls a vendor SDK directly; application policy depends on framework-specific persistence details.

Bad:

```java
class RegisterCustomer {
    void execute(String email) throws java.sql.SQLException {
        var connection = java.sql.DriverManager.getConnection("jdbc:example:customers");
        // SQL and registration policy are coupled here.
    }
}
```

Improved:

```java
interface CustomerRepository {
    void save(Customer customer);
}

final class RegisterCustomer {
    private final CustomerRepository customers;

    RegisterCustomer(CustomerRepository customers) {
        this.customers = customers;
    }

    void execute(String email) {
        customers.save(new Customer(email));
    }
}

record Customer(String email) {}
```

**Apply it.** Put an interface at a meaningful policy boundary when it isolates a changing or external detail. Let an infrastructure adapter implement that port; wire it at the application boundary.

**Avoid overuse.** DIP does not mean every concrete class needs an interface. Do not abstract stable, local implementation details with no credible substitution, test, or boundary benefit.

## Other engineering principles

For each principle, use its purpose as a decision aid. The trade-off section matters: principles can conflict, and applying one without context can make the design worse.

### DRY — Don't Repeat Yourself

**Purpose.** Keep one authoritative representation of a business rule or knowledge so corrections remain consistent.

**Apply it.** Consolidate duplication when repeated code expresses the same rule and is expected to change together. Name the shared concept, then test its behavior.

**Common violations.** Copy-pasted validation, pricing calculations, or authorization rules that drift over time.

**Trade-offs.** Similar-looking code may encode different domain policies or change for different reasons. Prematurely sharing it creates coupling. Prefer intentional duplication over a misleading common abstraction; refactor after commonality is understood.

### KISS — Keep It Simple

**Purpose.** Reduce the mental effort needed to understand and safely change code.

**Apply it.** Prefer direct control flow, clear names, and standard Java constructs. Choose the least complex design that meets requirements and has acceptable testability.

**Common violations.** Clever streams or generic frameworks obscuring a short operation; layers of delegates that add no behavior.

**Trade-offs.** “Simple” is not always “fewest lines.” A small explicit abstraction can simplify a caller or isolate a volatile boundary. Evaluate total comprehension, not line count.

### YAGNI — You Aren't Gonna Need It

**Purpose.** Avoid paying the ongoing cost of features and flexibility that no current requirement needs.

**Apply it.** Implement stated behavior and credible near-term variation. Add extension points when actual change pressure appears.

**Common violations.** Configurable pipelines, speculative plugin APIs, or generic frameworks for a single known use case.

**Trade-offs.** Avoid using YAGNI to ignore known requirements, security constraints, or established extension contracts. Some capabilities, such as observability or compatibility, may be explicit non-functional requirements.

### Separation of Concerns

**Purpose.** Keep distinct policies and technical responsibilities from interfering with one another.

**Apply it.** Separate HTTP mapping, application orchestration, domain rules, and persistence when those concerns have distinct behavior or change drivers.

**Common violations.** Controllers containing domain policy and SQL; repositories deciding user-facing response formats.

**Trade-offs.** Excessive layering scatters a simple flow across many files. Separate by meaningful change boundary, not by framework stereotype alone.

### Encapsulation

**Purpose.** Protect invariants by controlling how state is observed and changed.

**Apply it.** Keep mutable fields private, expose intention-revealing operations, validate state at construction or mutation boundaries, and return safe views or copies of mutable collections.

**Common violations.** Public mutable fields; setters that let callers create invalid states; leaking internal lists.

**Trade-offs.** Do not hide useful, stable data behind needless getters and wrappers. Records are suitable for transparent immutable data carriers when their invariants are simple.

### Composition over Inheritance

**Purpose.** Reuse behavior while keeping components replaceable and avoiding fragile coupling to a base-class implementation.

**Apply it.** Inject or own collaborators that perform a capability; use inheritance only when the subtype truly satisfies the base contract and the shared behavior is stable.

**Common violations.** Extending a class only to reuse a helper; deep hierarchies with overridden hooks and hidden initialization order.

**Trade-offs.** Composition introduces explicit delegation and may require several collaborators. Inheritance is reasonable for a stable, meaningful “is-a” relationship with valid substitutability.

### High Cohesion / Low Coupling

**Purpose.** Keep related behavior together and reduce the knowledge components require about each other's internals.

**Apply it.** Group code around a cohesive capability or domain concept. Depend on narrow contracts and pass required values rather than exposing object graphs.

**Common violations.** “God” services with unrelated operations; components reaching through several collaborators to fetch data and decide policy.

**Trade-offs.** Minimizing all dependencies is not the goal. A clear dependency can make collaboration explicit and testable; avoid splitting cohesive behavior merely to reduce a dependency count.

### Law of Demeter — Principle of Least Knowledge

**Purpose.** A unit should communicate with direct collaborators and avoid relying on deep internal object structure.

**Apply it.** Ask an object to perform an operation or provide a domain-level result instead of chaining through its internals.

**Common violations.** Chains such as `order.getCustomer().getAddress().getCountry()` used throughout the codebase; callers coordinating internal state transitions.

**Trade-offs.** Not every chain is harmful: fluent APIs, immutable value types, and simple DTO access may be clear. Avoid creating forwarding methods that merely duplicate every accessor.

### Dependency Injection (DI)

**Purpose.** Supply a component's collaborators from outside so its dependencies are visible and replaceable.

**Apply it.** Prefer constructor injection for required dependencies. In Spring, use constructor injection and let configuration or component scanning wire concrete beans.

```java
@org.springframework.stereotype.Service
final class InvoiceService {
    private final InvoiceRepository invoices;

    InvoiceService(InvoiceRepository invoices) {
        this.invoices = invoices;
    }
}
```

**Common violations.** Hidden service-locator calls, field injection that obscures required dependencies, or constructing infrastructure clients inside business logic.

**Trade-offs.** DI containers add runtime wiring and framework coupling at composition boundaries. For a small pure-Java program, explicit construction may be simpler.

### Inversion of Control (IoC)

**Purpose.** Let a framework or composition root control object creation and lifecycle rather than having application code control all infrastructure details.

**Apply it.** Keep framework configuration at the application boundary; keep core policy callable without starting a container where practical.

**Common violations.** Business logic depending on global container lookups; confusing “uses Spring” with “has inverted control.”

**Trade-offs.** Container-managed lifecycle and proxies can be useful, but they make runtime behavior less explicit. Use IoC for real lifecycle and wiring needs, not as a reason to route every object through a container.

### Immutability where appropriate

**Purpose.** Prevent accidental state changes, simplify sharing, and make invariants easier to reason about.

**Apply it.** Prefer `final` fields and immutable value types. Use records for simple data carriers; defensively copy mutable inputs when necessary.

```java
import java.util.List;

record SearchResult(List<String> items) {
    SearchResult {
        items = List.copyOf(items);
    }
}
```

**Common violations.** Mutable shared state without a clear owner; exposing internal collections; using setters for values that should not change after construction.

**Trade-offs.** Immutability can require copying and is not appropriate for every lifecycle-managed entity or performance-sensitive mutable buffer. Measure before optimizing; preserve clear ownership.

### Explicit over Implicit Design

**Purpose.** Make important behavior, dependencies, and assumptions easy to see.

**Apply it.** Use meaningful names, explicit constructor parameters, clear configuration, and deliberate error handling. Prefer a clear branch to surprising reflection or hidden global state.

**Common violations.** Behavior determined by undocumented defaults, magic strings, ambient context, or implicit fallback values.

**Trade-offs.** Excessive ceremony can bury the important path. Use concise language and framework conventions when they are familiar and visible.

### Fail Fast

**Purpose.** Detect invalid inputs or violated invariants close to their source rather than allowing corrupted state or obscure downstream failures.

**Apply it.** Validate at public boundaries and constructors; throw a meaningful exception for invalid state; preserve the cause when translating an exception.

```java
record Percentage(int value) {
    Percentage {
        if (value < 0 || value > 100) {
            throw new IllegalArgumentException("Percentage must be between 0 and 100");
        }
    }
}
```

**Common violations.** Swallowing exceptions, accepting invalid state and failing later, or returning `null` as an undocumented error signal.

**Trade-offs.** Validate where the contract is owned; avoid repeating identical defensive checks at every internal call. For expected absence or business rejection, use the repository's established result or exception convention rather than treating it as a programming error.

### Principle of Least Surprise

**Purpose.** Make behavior match the reasonable expectations set by names, contracts, and local conventions.

**Apply it.** Keep method effects predictable, preserve established API semantics, and follow the project's patterns unless they are demonstrably harmful.

**Common violations.** A getter that performs network I/O; a method named `save` that also sends email; exceptions or defaults that contradict the documented contract.

**Trade-offs.** Familiar conventions vary between projects. Prefer local consistency over imposing personal preferences, while documenting justified deviations.

### Tell, Don't Ask

**Purpose.** Let an object perform behavior using its own state instead of exposing state so callers can make decisions and mutate it externally.

**Apply it.** Move a rule to the object that owns the invariant when that makes behavior more cohesive.

Less cohesive:

```java
if (account.balance().compareTo(amount) >= 0) {
    account.setBalance(account.balance().subtract(amount));
}
```

More cohesive:

```java
account.withdraw(amount);
```

**Common violations.** Repeated getter-condition-setter sequences that duplicate policy or allow invalid transitions.

**Trade-offs.** A data-transfer object should expose data; not every record needs behavior. Do not create domain methods that merely wrap assignments or force business rules into objects that do not own them.

## Practical Java and Spring Boot guidance

### Classes, methods, and objects

- Name types and methods after their role or domain action. A method should communicate its inputs, effects, and failure modes.
- Keep methods focused on one coherent operation. Extract a helper when it names meaningful logic or removes duplication, not simply to shorten a method.
- Keep state private and make invariants hard to violate. Prefer constructor validation over a sequence of setters that temporarily creates invalid objects.
- Use `record` for immutable data carriers when its value semantics fit. Do not use records for entities whose identity and lifecycle require mutable state.
- Avoid boolean flags that select unrelated behaviors; use separate methods or a domain type when the alternatives have distinct meaning.

### Interfaces and abstractions

- Introduce an interface for a meaningful boundary, multiple real implementations, a stable capability, or an isolation seam with material value.
- Do not create an interface just because a class is a service or because a mock could be written. Concrete classes are often easy to test through their public behavior.
- Keep interfaces small and behavioral. Avoid leaking framework types into core policy contracts when that would make the boundary harder to reuse.
- Use enums or sealed types for a small, closed set of alternatives; use a polymorphic contract for an open set with independent implementations.

### Dependencies and Spring services

- Use constructor injection for required dependencies; keep fields `final` where possible.
- Keep Spring annotations and configuration primarily at the application/infrastructure boundary. Do not add a framework dependency to domain code without a concrete need.
- Make application services coordinate use cases and transaction boundaries. Put reusable domain invariants in domain types or domain services that own those rules.
- Use repository abstractions to express persistence needs when a boundary is useful. Avoid generic repositories that expose persistence mechanics to every caller.
- Keep controllers responsible for transport concerns: map requests, call application behavior, and map results. Do not let controllers become the home of domain policy.
- Configure transactions at an appropriate application boundary. Do not assume that extracting a method or class preserves Spring proxy behavior; verify transaction and proxy semantics when refactoring annotated code.

### Exceptions and failure handling

- Use exceptions for exceptional failures and the project's established result conventions for expected outcomes.
- Do not catch an exception merely to log and rethrow it unchanged; avoid duplicate logs at multiple layers.
- Catch only when the current layer can recover, add useful context, or translate to a contract it owns. Preserve the cause when wrapping.
- Never silently ignore failures or return success-shaped fallbacks. Avoid broad `catch (Exception)` unless a boundary truly must isolate arbitrary failures and has explicit reporting.
- Validate external input at the boundary, then rely on established invariants internally rather than scattering redundant checks.

### Refactoring existing code

1. Identify observable behavior and existing callers before changing structure.
2. Add or update focused tests around the behavior being preserved, especially at public or integration boundaries.
3. Make one coherent structural change at a time: extract a responsibility, name a domain concept, or isolate an actual external boundary.
4. Preserve method contracts, transaction behavior, serialization, exception semantics, and compatibility unless the requirement says otherwise.
5. Remove obsolete indirection after the change; do not leave old and new paths that can diverge.
6. Run targeted tests and relevant build or static checks. Report remaining uncertainty rather than claiming unverified behavior.

## Architecture and principles

Architectural styles are tools for managing complexity and change. Do not impose them on a small application or introduce layers without a real boundary.

### Clean Code

Clean Code is the daily practice of making behavior legible: meaningful names, focused functions, controlled side effects, clear error handling, and tests at useful boundaries. It complements SOLID but is not a license to fragment code into tiny methods and classes. Prefer clarity for the next maintainer over cleverness or rigid size rules.

### Clean Architecture

Clean Architecture organizes dependencies so policy is not forced to depend on external details. It is useful when domain/application rules need to survive changes in delivery mechanisms or infrastructure. Keep the dependency rule explicit and avoid creating use-case, gateway, presenter, and factory types where a direct call is sufficient.

### Hexagonal Architecture (Ports and Adapters)

Ports and adapters are valuable when the application must isolate external systems, support multiple delivery or persistence mechanisms, or test policy independently of infrastructure. Define ports around application needs and implement adapters for technologies. A single adapter and a stable external dependency do not automatically justify an elaborate framework.

### Domain-Driven Design (DDD)

DDD is useful when business rules are complex, domain language matters, and multiple concepts have distinct invariants. Use bounded contexts, entities, value objects, and domain services to model real domain boundaries. Do not add aggregates, repositories, or ubiquitous-language ceremonies to simple CRUD without a domain problem they solve.

### Layered Architecture

Layers such as web, application, domain, and infrastructure can clarify responsibilities and dependency direction in conventional Spring Boot systems. Keep each layer purposeful, and prevent business policy from leaking into controllers or persistence code. For small features, avoid pass-through layers that only rename and forward values.

### Modular design and domain/infrastructure separation

Modular boundaries are appropriate when parts of a system have independent concepts, change rates, ownership, or deployment needs. Keep module APIs narrow and avoid circular dependencies. Separate domain policy from infrastructure when the separation protects business rules or enables useful alternatives; do not create an artificial domain layer around code with no domain logic.

## Code review checklist

Use only the items relevant to the change; an unchecked item is not automatically a defect.

- [ ] Does each changed class have a coherent responsibility and each method a clear purpose?
- [ ] Are abstractions justified by a real variation, boundary, or testability need?
- [ ] Do dependencies point toward stable policy where that boundary matters?
- [ ] Are coupling and cohesion appropriate, with no unnecessary knowledge of collaborators' internals?
- [ ] Are state and invariants encapsulated, and are mutable values safely owned?
- [ ] Is repeated code truly the same knowledge, or does it represent distinct rules?
- [ ] Is the solution simpler than the problem requires, without speculative flexibility or premature optimization?
- [ ] Does inheritance preserve the parent contract, and would composition be clearer?
- [ ] Can behavior be tested without excessive mocking or framework setup?
- [ ] Will the change remain understandable and maintainable using local conventions?
- [ ] Does it preserve public behavior, exception semantics, transactions, serialization, and backward compatibility?
- [ ] Are errors explicit and handled at the layer that can meaningfully respond?
