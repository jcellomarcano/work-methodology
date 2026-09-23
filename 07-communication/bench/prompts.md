# Fixed prompt bench for measuring the identity block

Five prompts, one per response type. Each is passed as-is, in two arms: `sin` (prompt only) and `con`
(the full `identidad.es.md` in front, plus the line `INTERLOCUTOR: público. Responde en español.`). Each
output is saved as `out/<model>-<arm>-<kind>.md` and linted with `--type <kind> --lang es --audience public`.
Primary metric per arm: proportion of outputs with `verdict: PASS`. Secondary: FAIL by rule and human-layer
lines. The prompts carry the data the response needs, so neither arm has to invent or look anything up.

Note: the prompt text below (P1-P5) is the frozen Spanish input the benchmark was actually run against; it
stays in Spanish so it matches the recorded outputs in `out/` and `out-v1/` exactly. See the folder's
translation report for why.

## P1 · pregunta (question)

¿Puedo reintentar un pago fallido en mi app de cobro sin riesgo de cobrar dos veces? Contexto: el SDK genera la
clave de idempotencia dentro del bucle de reintento (`PaymentRetry.kt:52` @ 9f3e2a1 llama a
`newIdempotencyKey()` en cada iteración). No existe ningún test que cubra el reintento.

## P2 · estado (state)

Dame el estado de la migración a Room. Datos: 14 de 18 entidades migradas; tests verdes en los commits
a1b2c3d..e4f5a6b; faltan `Receipt` y `Shift`; el banco de pruebas lo tiene otra sesión hasta mañana; no se
ha probado el arranque en frío sin red.

## P3 · decision (decision)

¿Guardamos el estado del pago en SharedPreferences, en Room o en un fichero write-ahead propio? Restricciones:
el proceso puede morir entre la llamada al proveedor y la confirmación; hay que poder reconstruir qué pasó;
el equipo ya usa Room; la jerarquía del proyecto es Dinero > Estado del pago > Recuperabilidad > UX.

## P4 · fallo (failure)

Los cajeros dicen que "la pantalla se queda congelada al cobrar". Datos: log `12:03:41 ANR in MainActivity`;
`PaymentViewModel.kt:118` @ 7c1d0e9 llama a `provider.confirm()` de forma síncrona en el hilo principal; la
red iba bien (ping 40 ms); no hay OOM en el log; no se ha reproducido todavía en el banco de pruebas.

## P5 · investigacion (research)

Explícame qué es el "split-attention effect" y qué implica para escribir documentación técnica. Mi lector no
conoce el tema. Usa solo estas fuentes, citándolas literales: (1) Sweller, van Merriënboer y Paas (2019),
https://link.springer.com/article/10.1007/s10648-019-09465-5 : "Learners must mentally integrate two sources
of information in order to understand the solution, a process that yields a high cognitive load and hampers
learning." (2) misma fuente, efecto de redundancia: "only presenting the diagram was superior to presenting
both sources of information together." (3) misma fuente, carga extrínseca: la determina "how the information
is presented and what the learner is required to do by the instructional procedure." No has leído la página:
eres tú quien decide la etiqueta epistémica de cada afirmación.
