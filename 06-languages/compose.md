# Jetpack Compose conventions: official baseline + typical house rules

## 1. Source and hierarchy

Compose doesn't have a single style guide: the normative reference is the team's own document,
the Compose API Guidelines (https://github.com/androidx/androidx/blob/androidx-main/compose/docs/compose-api-guidelines.md),
written for library authors but applicable to any public composable. It's complemented by the
developer.android.com pages on state (https://developer.android.com/develop/ui/compose/state),
effects (https://developer.android.com/develop/ui/compose/side-effects), and stability
(https://developer.android.com/develop/ui/compose/performance/stability), official Google prose but
not a PR checklist. Beneath all of it, `kotlin.md` (this directory) still applies: Compose is a
Kotlin DSL, not a separate language.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Unit composable name | "name any function that returns `Unit` and bears the `@Composable` annotation using `PascalCase`, and the name MUST be that of a noun, not a verb or verb phrase" | `UserProfile()`, not `DrawUserProfile()` |
| Value-returning composable | follows the normal Kotlin Coding Conventions, not the noun rule | `rememberScrollState()` |
| Modifier: position | "This parameter MUST be named `modifier` and MUST appear as the first optional parameter in the element function's parameter list. Element functions MUST NOT accept multiple `Modifier` parameters" | a single `modifier`, first among the optional ones |
| Modifier: default value | "the default value of the `modifier` parameter MUST be `Modifier`" | `modifier: Modifier = Modifier` |
| Content slot | "Layout functions SHOULD place their primary or most common `@Composable` function parameter in the last parameter position to permit the use of Kotlin's trailing lambda syntax" | `content: @Composable () -> Unit` at the end |
| Hoisted state | "factor a collection of state and callbacks into an interface, allowing a caller to provide a cohesive policy object as a unit" | group related state and callbacks, not loose parameters |
| State vs event | "Compose operates on state as input, not events"; the state observer "must therefore be idempotent" | a composable must not assume it sees every event |
| Hoisting (dev docs) | "State hoisting in Compose is a pattern of moving state to a composable's caller to make a composable stateless" | the composable below doesn't own its state |
| Single source of truth (dev docs) | "By moving state instead of duplicating it, we're ensuring there's only one source of truth" | |
| Side-effect-free | "composables should ideally be side-effect free" | IO/mutation outside the composable's body |
| Stable type | "A type is stable if it is immutable, or if it is possible for Compose to know whether its value has changed between recompositions" | `@Immutable`/`@Stable` enable skipping |
| Skippable | "If the compiler marks a composable as skippable, Compose can skip it during recomposition if all its arguments are equal with their previous values" | fewer unstable parameters, more skips |

## 3. What the official guide does NOT say

- Nothing about where money or irreversible effects live: it talks about "state vs events", not
  "business effect vs UI effect".
- Nothing about MVI vs MVVM: hoisted state is a parameter pattern, not a layered architecture.
- Nothing about module boundaries (design-system vs feature): that boundary is organizational.
- Nothing about money formatting, localized strings, or accessibility inside the composable.

## 4. Typical house rules (labeled as such)

- **Building blocks in a design module**: stateless composables with state hoisting live in
  `:designsystem` (or equivalent); the app composes them and feeds them state.
- **`collectAsStateWithLifecycle`, not `collectAsState`**: the flow is only collected while the view
  is in the foreground.
- **One immutable `UiState` per screen; the reducer is the spec**: the pure function producing the
  new state lives in its own file, testable in pure JVM; its case table IS the contract (see
  `kotlin.md`, MVI rule).
- **Effects as a one-shot channel, never as state**: navigation, a snackbar, an event that's
  consumed once; never recomposed twice due to rotation.
- **An irreversible effect (charge, send) never goes through the UI effects channel**: that verb
  goes to the store/ViewModel, which calls the domain; the UI only fires the intent.
- **Anti-green rule**: an intermediate state (processing, retrying) is never painted with the color
  or icon of success; success is only painted on the domain's real confirmation.
- **One `@Preview` per state variant**, including error and empty: if a state has no preview, it
  isn't visually tested.
- **Accessibility as a rule, not an extra**: `contentDescription` with a localized key, `testTag`,
  and focus order declared alongside the composable, not added later.
- **No money or date formatting inside the composable**: the already-formatted string arrives in
  the `UiState`; the composable only paints.
- **Text by key, never literals**: the same mechanism as the rest of the app (`Strings.Keys` /
  `DSLocalizer`), not a loose string in a `Text()`.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| Modifier: name, position, only one | Compose lint (`androidx.compose.ui.lint`, `ModifierParameter`) | PR review |
| Stability / skippability | Compose compiler report (`composables.txt`, `classes.txt`) | `metricsDestination` in CI with a threshold |
| Hoisting / coupling to store | detekt-compose (https://github.com/mrmans0n/compose-rules) | Konsist over forbidden imports |
| Module boundaries (blocks vs feature) | grep of forbidden imports with a negative control | Konsist (P2) |
| Visual regression per variant | Paparazzi or Roborazzi (screenshot test per `@Preview`) | human visual review |
| Irreversible effect outside the store | test that fails if the ViewModel exposes the charge verb to the UI | architecture review in PR |
| Literal / keyless text | grep for `Text("` with a string literal | project lint |

## Concurrency and the UI thread

`LaunchedEffect` only relaunches its coroutine when an explicit key changes: "If LaunchedEffect is recomposed with different keys, the existing coroutine will be cancelled and the new suspend function will be launched in a new coroutine" (side-effects). `rememberCoroutineScope` gives a scope "bound to the point of the Composition where it's called", never `GlobalScope`. `rememberUpdatedState` avoids restarting a long-running effect when only a captured lambda changes. `collectAsStateWithLifecycle` "collects values from a Flow in a lifecycle-aware manner" (state), not `collectAsState`.

House rules: the composable never fires the charge effect, that lives in the store; `LaunchedEffect` keys are always explicit, never a `Unit` disguising the trigger; one-shot events go through a lifecycle-collected `Channel`; recomposition is pure, with no side effect in the composable's body.

## Sources

- https://github.com/androidx/androidx/blob/androidx-main/compose/docs/compose-api-guidelines.md
- https://developer.android.com/develop/ui/compose/state
- https://developer.android.com/develop/ui/compose/side-effects
- https://developer.android.com/develop/ui/compose/performance/stability
- https://developer.android.com/develop/ui/compose/performance/stability/diagnose
- https://github.com/mrmans0n/compose-rules

## Verdict

Compose formalizes hoisting and separates state from event, but leaves "which effect is
irreversible" out of its scope: the app decides that with its own channel and the anti-green rule.
The critical flow's auditability depends on the reducer being pure and the store, not the UI,
talking to the domain; the compiler certifies stability, not business correctness.
