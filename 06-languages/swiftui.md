# SwiftUI conventions: official baseline + typical house rules

## 1. Source and hierarchy

There's no single style guide for SwiftUI: the normative reference is Apple's documentation by type
(State https://developer.apple.com/documentation/swiftui/state, Binding
https://developer.apple.com/documentation/swiftui/binding, Observable
https://developer.apple.com/documentation/observation/observable(), and the article "Managing user
interface state" https://developer.apple.com/documentation/swiftui/managing-user-interface-state)
plus the Human Interface Guidelines (https://developer.apple.com/design/human-interface-guidelines)
for accessibility and interaction. WWDC sessions ("Data Essentials in SwiftUI", 2020,
https://developer.apple.com/videos/play/wwdc2020/10040/; "Discover Observation in SwiftUI", 2023,
https://developer.apple.com/videos/play/wwdc2023/10149/) are guidance, not spec: cited as Inferred.
When in doubt: the type/protocol doc first, the HIG for accessibility, the project's own
`CONVENTIONS.md` for the rest.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| `@State`: purpose | "Use state as the single source of truth for a given value type that you store in a view hierarchy" | the data lives exactly once, in the view that declares it |
| `@State`: scope | "Declare state as private in the highest view in the view hierarchy that needs access to the value" | private; shared downward, not duplicated |
| `@Binding`: purpose | "A property wrapper type that can read and write a value owned by a source of truth" | the child view doesn't own the data, it only edits it |
| `@Binding`: mechanism | "A binding connects a property to a source of truth stored elsewhere, instead of storing data directly" | no storage of its own |
| Single source of truth (article) | "Store data as state in the least common ancestor of the views that need the data to establish a single source of truth that's shared across views" | the least common ancestor, not the highest level available |
| `@State` isn't persistence | "Don't use state properties for persistent storage because the life cycle of state variables mirrors the view life cycle" | `@State` is transient UI, not the data model |
| `@Observable` | "This macro adds observation support to a custom type and conforms the type to the Observable protocol" | replaces `ObservableObject`/`@Published` |
| `#Preview` | "You use one of the preview macros, like `#Preview`, to tell Xcode what to display" | the preview is code, it compiles |

## 3. What the official guide does NOT say

- Nothing about architecture: not TCA, not MVVM, not where business logic lives; the docs only say
  who owns the value.
- Nothing about where an irreversible effect (charge, send) should live: `.task`/`.onChange` are
  mechanism, not policy.
- Nothing about `#Preview` determinism: the macro's docs don't warn against `Date()` or random
  values inside a preview.
- Nothing about money or text formatting inside the view: that's the app's own convention.

## 4. Typical house rules (labeled as such)

- **Views as stateless building blocks, state in an `@Observable` store**: the view declares
  `@State`/`@Binding` only for purely visual things (is a sheet open?, which tab?); the rest lives
  in the store injected via `@Environment` or a parameter.
- **`.task`/`.onChange` only for view-scoped effects** (load on appear, react to a visual change);
  the irreversible effect (charge, send) is never fired from a view modifier, it goes to the store,
  which calls the domain.
- **Anti-green rule**: an intermediate state (processing, retrying) is never painted with the color
  or icon of success; only the domain's real confirmation paints success.
- **One `#Preview` per variant with fixed data**: one preview per state (empty, error, success,
  loading), with deterministic data; never `Date()`, a random `UUID()`, or a network call inside the
  preview.
- **Accessibility as a rule, not an extra**: `accessibilityLabel` with a localized key and a stable
  `accessibilityIdentifier` for UI tests, declared alongside the modifier that needs them.
- **Strings from a catalog, never literals**: `String Catalogs` (or the project's own localization
  mechanism), not a loose literal in a `Text()`.
- **Decimal or integers in the smallest unit for money, formatted outside the view**: the store
  hands over the already-formatted string; the view only paints.
- **Domain models with value semantics** (struct/enum); the store is the only class with identity
  and observable mutable state.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| Irreversible effect in the view | grep for network/payment calls inside `View.body` or modifiers | architecture review in PR |
| Non-deterministic preview | grep for `Date()`/`UUID()`/network inside `#Preview` | preview compiled in CI |
| Accessibility | Xcode's Accessibility Inspector | `XCUIApplication().performAccessibilityAudit()` in a UI test |
| Visual regression per variant | snapshot test per preview | swift-snapshot-testing |
| `!` / `try!` in the view | SwiftLint (`force_unwrapping`, `force_try`) | human review |
| Literal / keyless text | grep for `Text("` with a literal | project lint |
| Unsafe concurrency in the store | compiler flag (`-strict-concurrency=complete`) | Thread Sanitizer |

## Concurrency and the UI thread

`.task(id:)` "adds a task to perform before this view appears or when a specified value changes" (task(id:priority:_:)); the task is cancelled and relaunched when `id` changes, and cancelled when the view disappears, like any Swift Concurrency task tied to the life cycle of whoever launched it. The view runs isolated to the main actor (`@MainActor`, developer.apple.com/documentation/swift/mainactor), just like the `@Observable` store that feeds it.

House rules: the view never does the money work, that lives in the store (an actor or a `@MainActor` class); `.task` only for view-scoped loads, cancelled on disappear; no `Task.detached` fired from a view; strict concurrency (`-strict-concurrency=complete`) enabled in the project.

## Sources

- https://developer.apple.com/documentation/swiftui/state
- https://developer.apple.com/documentation/swiftui/binding
- https://developer.apple.com/documentation/swiftui/managing-user-interface-state
- https://developer.apple.com/documentation/observation/observable()
- https://developer.apple.com/design/human-interface-guidelines
- https://developer.apple.com/videos/play/wwdc2020/10040/
- https://developer.apple.com/videos/play/wwdc2023/10149/
- https://developer.apple.com/documentation/swiftui/view/task(id:priority:_:)
- https://developer.apple.com/documentation/swift/mainactor

## Verdict

SwiftUI formalizes very well who owns the data ("source of truth"), but says nothing about which
effect is irreversible nor about architecture: that boundary is drawn by hand with an `@Observable`
store the view never bypasses. The critical flow's auditability depends on the store, not the view's
`body`, talking to the domain.
