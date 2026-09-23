# Protocolo DEM: `density_continuation`

Estado: implementado en JPGen y en el Kratos local con
[el parche DEM de reinicio](../patches/kratos-dem-density-restart.patch). La
prevalidación exige el marcador de compatibilidad del binario antes de iniciar
una ejecución. El rollback restaura un checkpoint completo en un nuevo análisis
del mismo proceso y conserva los contadores de trabajo. Los checkpoints guardan
el estado portable del protocolo para inspección; todavía no existe un comando
CLI para reanudar una ejecución tras salir del proceso. Un caso pequeño
reproducible se encuentra en [el ejemplo](../examples/dem_density_continuation.yaml).

## Objetivo

Añadir una etapa seleccionable mediante `control.type: density_continuation`,
al mismo nivel de configuración que `stress_servo`, `strain_rate` o
`free_evolution`. Su objetivo es aumentar progresivamente la fracción sólida y
guardar muestras equilibradas para una lista de densidades objetivo, evitando
el salto brusco de fricción a cero.

La etapa reduce la fricción mediante incrementos adaptativos, mantiene un
confinamiento de referencia y permite que el volumen responda mecánicamente.
No prescribe un volumen objetivo ni convierte directamente el error de densidad
en velocidad de pared. Reutiliza el servo de presión para mantener el
confinamiento; el parámetro de preparación es la fricción.

La continuidad de la densidad no está garantizada: una pequeña reducción de
fricción puede desencadenar un reordenamiento colectivo. El protocolo busca
resolver objetivos dentro de tolerancia y diagnosticar aquellos que no logra
alcanzar con la trayectoria y el presupuesto elegidos.

## Magnitudes y alcance inicial

- Densidad objetivo: `solid_fraction`, definida como suma de volúmenes de esferas
  dividida por el volumen actual de la celda. Conserva la convención nominal de
  JPGen, que no descuenta solapamientos.
- Partículas, radios y densidad del material constantes; celda periódica variable.
- Presión media de referencia positiva y constante durante toda la etapa.
- Objetivos estrictamente crecientes. No es un protocolo de descompactación.
- Fricción estática y dinámica multiplicadas por un factor común `f` en `[0, 1]`:
  `mu_static = f * mu_static_entry`, `mu_dynamic = f * mu_dynamic_entry`.
  Las referencias son los valores activos al entrar en la etapa; `friction_decay`
  permanece constante. Esto conserva la relación entre ambos coeficientes.
- La primera versión guarda muestras a la fricción alcanzada. Recuperar la
  fricción original no forma parte de su aceptación ni ocurre implícitamente.

## Configuración

Fragmento dentro de `dem.protocol.stages`; los valores son ilustrativos y deben
ajustarse a las unidades, tamaño y dinámica de la muestra:

```yaml
- name: prepare_density_series
  control:
    type: density_continuation
    targets: [0.620, 0.625, 0.630]
    density_atol: 0.0002

    confinement:
      target_pressure: 5000.0       # Pa, presión media
      pressure_rtol: 0.01
      max_velocity: 0.01           # m/s, convención del servo existente

    friction:
      min_factor: 0.0
      initial_decrement: 0.05      # decrementos del factor, no de mu
      min_decrement: 0.0001
      max_decrement: 0.10
      safety_factor: 0.5
      growth_factor: 1.5
      retry_factor: 0.5

    relaxation:
      max_duration: 0.1           # s por intento, incluida la relajación inicial
      condition:
        all:
          - {observable: kinetic_energy, op: below, value: 1.0e-8}
          - {observable: unbalanced_force, op: below, value: 1.0e-3}
        hold_for: 0.005
      density_stability:
        window: 0.005             # s
        max_range: 0.00005        # max(phi) - min(phi) en la ventana

    limits:
      max_attempts: 200
      max_retries_per_increment: 12

    snapshots:
      mode: equilibrated
      include_restart: true

  until:
    observable: density_targets_completed
    op: above
    value: 3
  max_duration: 10.0
```

`density_targets_completed` es un observable nuevo, local a la etapa. El
validador exige que `until` sea la condición de finalización de todos los
objetivos; no permite que un cruce transitorio termine esta etapa. Los límites
internos producen fallos diagnosticados, no éxito parcial silencioso.

Para empezar, se exige `snapshots.mode: equilibrated` e
`include_restart: true`. Otros modos serían ampliaciones explícitas.

## Criterio de aceptación

Una muestra se acepta cuando, durante el intervalo de permanencia requerido:

1. `abs(phi - target) <= density_atol`.
2. La presión satisface la tolerancia relativa respecto a la referencia.
3. Se cumple `relaxation.condition`.
4. La ventana de estabilidad de densidad está completa y su rango no supera
   `density_stability.max_range`.

La permanencia se aplica a la conjunción, no solo a la energía. Las medidas se
comprueban en cada paso completo, independientemente de `sample_every`.
La energía cinética baja por sí sola no demuestra equilibrio; se utiliza además
el observable de desequilibrio disponible. Su definición y sus limitaciones,
incluido si cubre momentos, deben constar en la salida del backend.

La tolerancia es absoluta en fracción sólida. No se interpola una geometría
entre dos estados para fabricar una muestra con la densidad exacta.

## Máquina de estados

### 1. Inicializar y equilibrar

Capturar las fricciones activas como referencias y fijar `f = 1`. Mantener el
confinamiento hasta cumplir relajación, presión y estabilidad de densidad.
Evaluar entonces el primer objetivo: si ya está dentro de tolerancia, guardarlo;
si queda por debajo de la densidad equilibrada más allá de tolerancia, fallar
con `target_below_initial_density`.

### 2. Crear checkpoint de continuación

Guardar el estado equilibrado de partida antes de cada intento de reducción.
Es el estado desde el que se restaurará si el intento no es aceptable.

### 3. Reducir fricción

Aplicar `f_new = max(min_factor, f - decrement)`. Actualizar los parámetros de
los contactos existentes y de los futuros. La ley `DEM_D_Hertz_viscous_Coulomb`
lee los coeficientes activos al calcular fuerzas y limita la respuesta tangencial
con esos valores. El historial de contactos permanece en las partículas y no se
borra globalmente.

### 4. Relajar a fricción constante

Mantener `f_new` y el confinamiento. No seguir reduciendo fricción mientras la
muestra se está relajando. Registrar los cruces de objetivos como eventos
transitorios; un cruce no acepta una muestra.

### 5. Clasificar el resultado

- Equilibrado y por debajo del objetivo: aceptar como punto de continuación,
  crear el siguiente checkpoint y calcular otro decremento.
- Equilibrado dentro de tolerancia: publicar la muestra, incrementar
  `density_targets_completed` y continuar hacia el siguiente objetivo desde
  ese mismo estado.
- Equilibrado por encima de tolerancia: restaurar el checkpoint anterior,
  multiplicar el decremento por `retry_factor` y repetir.
- Sin equilibrio dentro del tiempo por intento: restaurar y reducir el
  decremento; al agotar los límites, fallar con `relaxation_failed`.

El sobrepaso transitorio por sí solo no activa rollback: la clasificación usa
el resultado relajado. Deben existir límites geométricos y numéricos del backend
que interrumpan estados inválidos durante cualquier intento.

### 6. Terminar

Tras guardar el último objetivo, mantener el estado aceptado y su fricción
activa. La siguiente etapa recibe ambos y conserva la historia de contactos.
No restaurar automáticamente los parámetros iniciales.

## Adaptación del decremento

Para dos puntos de continuación equilibrados y aceptados:

`s = (phi_k - phi_previous) / (f_previous - f_k)`.

Si la pendiente es positiva y numéricamente significativa:

`next_decrement = safety_factor * (target - phi_k) / s`.

Limitar el resultado a `[min_decrement, max_decrement]`, al factor disponible
hasta `min_factor` y a un crecimiento máximo de `growth_factor` respecto al
último decremento exitoso. La pendiente usa exclusivamente puntos aceptados,
no estados transitorios ni intentos descartados.

Sin pendiente fiable, usar el decremento inicial en el primer intento y
mantener el último decremento exitoso en los siguientes. Una respuesta plana
no justifica un salto inmediato a fricción cero. Una pendiente negativa se
registra como respuesta no monótona y no se usa en la fórmula predictiva.

En rollback, reducir el decremento del intento fallido. Si el siguiente
reintento exigiría un decremento inferior al mínimo configurado, terminar con
`resolution_limit` y guardar el intervalo observado de densidades equilibradas. Eso no demuestra que el
objetivo sea físicamente imposible con otra trayectoria.

Si `f` alcanza `min_factor`, completar la relajación y evaluar antes de declarar
`friction_limit`. Un último decremento menor que `min_decrement` solo se permite
para llegar exactamente al límite de factor; no habilita reintentos menores.

## Checkpoints y semántica temporal

Un checkpoint reiniciable debe preservar, como mínimo:

- IDs, posiciones, radios, velocidades, rotaciones y estado dinámico requerido.
- Celda periódica y datos necesarios para reconstruir contactos y vecinos.
- Historia tangencial y demás variables internas de cada contacto.
- Parámetros materiales activos y referencias de fricción de la etapa.
- Tiempo, integrador, estado del servo y generadores aleatorios si los hubiera.
- Estado de continuación, objetivo activo e historiales de condiciones.

Los HDF5 de geometría o resultados actuales no bastan para este contrato. El
backend Kratos exige el marcador `JPGEN_DENSITY_RESTART_VERSION = 1` en el
binario y rechaza la etapa antes de iniciar la simulación si falta. La carga
usa los model parts serializados; reconstruye la malla de medición de contactos
y busca vecinos en cada paso. No sustituye el checkpoint por una
reinicialización desde posiciones.

Rollback restaura el tiempo físico y los historiales al checkpoint. Los
contadores de trabajo, intentos y reintentos no retroceden. Para esta etapa,
`max_duration` limita el tiempo integrado acumulado de todos los intentos,
incluidos los descartados; esta excepción respecto al tiempo de la trayectoria
aceptada debe mostrarse explícitamente en los resultados. `stage_time` conserva
el significado de tiempo físico de la rama activa. También se registra
`attempted_duration` para contabilizar trabajo y evitar reintentos ilimitados.

Los registros de intentos son append-only y llevan identificador de intento y
eventos `start`, `accepted`, `accepted_target` o `discarded`. El campo de paso
de `observables.jsonl` cuenta trabajo integrado, mientras que el tiempo refleja
la rama física activa; tras rollback pueden aparecer tiempos repetidos.

## Resultados

Publicar atómicamente una muestra por objetivo aceptado bajo
`dem/density_targets/target_0001/`, etc. Cada directorio contiene:

- Estado de partículas y celda para análisis, en el formato común correspondiente.
- Checkpoint nativo reiniciable, con versión y compatibilidad del backend.
- Metadatos: objetivo y densidad real, presión y tensor de tensiones, energía,
  desequilibrio, factor y coeficientes de fricción, tiempo físico, trabajo
  acumulado, intentos, tolerancias, semilla y procedencia.

Si una muestra necesita recuperar la fricción de entrada, hacerlo en una etapa
posterior explícita y volver a evaluar densidad, presión y equilibrio. No
etiquetar la captura previa como muestra equilibrada a la fricción recuperada.
Una futura variante podría aceptar solo después de esa recuperación y utilizar
ramas separadas de continuación y evaluación.

Los fallos conservan los objetivos ya publicados, el último checkpoint equilibrado
y los diagnósticos del intento fallido. No continuar silenciosamente con el
siguiente objetivo. Los metadatos distinguen una serie incompleta de una ejecución
que ha cumplido todos los objetivos.

## Integración en JPGen

`dem/protocol.py` valida y recorre etapas y bloques repetidos. Cada entrada en
una etapa de densidad crea una instancia independiente de
`dem/density_continuation.py` y toma como referencia la fricción activa de ese
momento. El control cambia los parámetros de contacto entre pasos completos;
al comienzo del siguiente paso el servo calcula y aplica la velocidad de las
caras, y Kratos integra las fuerzas con la nueva fricción. Así se conserva la
historia tangencial de los contactos existentes.

`DemContinuationPort` ofrece lectura y actualización de fricción, checkpoint,
restauración, publicación y registro de intentos. Kratos serializa los model
parts y una instantánea del estado portable; una restauración crea un análisis
nuevo dentro del mismo worker y vuelve a enlazar el `ProtocolRunner` activo.
Las capacidades del backend y la prevalidación del binario impiden ejecutar la
etapa con una implementación incompleta. El asistente puede construir la etapa
y el caso standalone copia la máquina de estados portable.

## Validaciones y límites

Exigir valores finitos; objetivos positivos, ordenados y separados por más de
dos tolerancias; presión positiva; tolerancias y duraciones positivas;
`0 <= min_factor < 1`; decrementos positivos y ordenados;
`0 < safety_factor < 1`; `0 < retry_factor < 1`; `growth_factor >= 1`;
y límites enteros positivos. La ventana de estabilidad debe caber dentro del
tiempo de relajación y contener al menos dos observaciones completas.

Si ambas fricciones de entrada son cero, el protocolo carece de un parámetro
que reducir y debe rechazar la etapa. No imponer un límite universal de 0.64 a
la densidad: granulometría, presión y solapamientos afectan al rango alcanzable.

La etapa no garantiza monotonía, continuidad ni cualquier densidad deseada.
Los resultados deben distinguir compactación por reorganización de un aumento
de fracción nominal asociado a solapamientos, registrando estos cuando el
backend disponga de la medida.

## Base física y referencias

- Agnolin y Roux (2007), *Internal states of model isotropic granular packings.
  I. Assembling process, geometry and contact networks*:
  https://arxiv.org/abs/0705.3194
- Silbert (2010), *Jamming of frictional spheres and random loose packing*:
  https://doi.org/10.1039/C001973A
- Documentación de LAMMPS, ley tangencial con historia y reajuste al límite de
  Coulomb: https://docs.lammps.org/stable/pair_granular.html

Estas referencias respaldan la dependencia con la fricción, la preparación y
la memoria de contacto. La continuación adaptativa con objetivos, rollback y publicación de muestras
es una implementación de JPGen; no se presenta como un algoritmo validado por
esos trabajos.
