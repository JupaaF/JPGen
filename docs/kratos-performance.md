# Perfilado de Kratos con 4000 partículas

Estudio local del 21 de septiembre de 2026. Los experimentos usan la compilación
existente de `Kratos/bin/Release`, no una distribución instalada desde PyPI.

El paso nativo consume aproximadamente el **95 % del tiempo** de la referencia.
La mejora directamente disponible en JPGen es usar **2 o 4 hilos**: aceleraciones
de **1,67× y 1,77×**, respectivamente, con arrays finales exactamente iguales.
Dos hilos ofrecen aquí un mejor equilibrio entre latencia y CPU consumida;
no se ha medido el rendimiento de varias simulaciones simultáneas.

La mayor aceleración experimental es **4,29×** combinando cuatro hilos con
búsqueda cada 10 pasos y margen de 50 µm: **98,83 → 23,03 s**. Introduce una
diferencia de energía cinética del **0,005609 %** y de posición máxima de
**39,76 nm** tras 1 ms. Su adopción general requiere controlar el desplazamiento
entre búsquedas y validar la tolerancia física de cada escenario. El control
que añade sólo el margen, manteniendo búsqueda cada paso, da arrays finales
exactamente iguales: las diferencias observadas están asociadas a espaciar
las búsquedas.

Se completaron **28 simulaciones**: una referencia del pipeline, dos ejecuciones
con `cProfile`, 18 de la matriz principal, seis de combinaciones y un control
de margen aislado. Las tablas de tiempos usan las 25 últimas, con cronómetros
de fase y sin `cProfile`.

## Resultados medidos

| Variante | Repeticiones | Mediana (s) | Rango (s) | Aceleración | CPU del solver (s) | Error relativo energía (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 hilo, búsqueda cada paso | 3 | 98.83 | 75.24–101.55 | 1.00× | 95.44 | 0.000000 |
| 2 hilos, búsqueda cada paso | 3 | 59.12 | 58.78–62.89 | 1.67× | 101.92 | 0.000000 |
| 4 hilos, búsqueda cada paso | 3 | 55.84 | 45.07–65.74 | 1.77× | 148.24 | 0.000000 |
| 1 hilo, cada 10 pasos + margen | 3 | 50.14 | 48.25–50.19 | 1.97× | 48.38 | 0.005609 |
| 1 hilo, cada 20 pasos + margen | 3 | 46.07 | 45.17–49.68 | 2.15× | 44.19 | 0.013880 |
| 1 hilo, cada 10 pasos sin margen | 3 | 43.45 | 42.75–49.10 | 2.27× | 42.41 | 0.005824 |
| 2 hilos, cada 10 pasos + margen | 3 | 28.20 | 28.03–29.17 | 3.50× | 51.56 | 0.005609 |
| 4 hilos, cada 10 pasos + margen | 3 | 23.03 | 19.67–24.54 | 4.29× | 66.44 | 0.005609 |
| 1 hilo, cada paso + margen (control) | 1 | 101.73 | 101.73–101.73 | 0.97× | 98.35 | 0.000000 |

CPU es el tiempo de proceso acumulado entre hilos que informa Kratos para el solver; no es el tiempo de pared ni una medición de energía eléctrica. Las aceleraciones son cocientes de medianas respecto a la referencia. La campaña de combinaciones se ejecutó después de la principal; la carga externa limita la precisión de esa comparación. El control de margen aislado tiene una sola repetición y se usa para comparar física, no para estimar velocidad.

Datos por ejecución y perfiles de fase: [kratos-performance-results.json](kratos-performance-results.json). Los estados completos y logs están en `benchmarks/kratos_4000/{measurements,combined,control}/`.

### Comparación física

| Variante | Máximo desplazamiento respecto a referencia (m) | Máxima diferencia de velocidad (m/s) | Máxima diferencia angular (rad/s) | Error L2 velocidad (%) | Error L2 angular (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 hilo, búsqueda cada paso | 0 | 0 | 0 | 0 | 0 |
| 2 hilos, búsqueda cada paso | 0 | 0 | 0 | 0 | 0 |
| 4 hilos, búsqueda cada paso | 0 | 0 | 0 | 0 | 0 |
| 1 hilo, cada 10 pasos + margen | 3.97585e-08 | 0.000139439 | 0.047943 | 0.0152809 | 0.0222905 |
| 1 hilo, cada 20 pasos + margen | 8.18049e-08 | 0.000164931 | 0.0498077 | 0.0343027 | 0.0477421 |
| 1 hilo, cada 10 pasos sin margen | 3.97585e-08 | 0.000139439 | 0.047943 | 0.0155746 | 0.0227923 |
| 2 hilos, cada 10 pasos + margen | 3.97585e-08 | 0.000139439 | 0.047943 | 0.0152809 | 0.0222905 |
| 4 hilos, cada 10 pasos + margen | 3.97585e-08 | 0.000139439 | 0.047943 | 0.0152809 | 0.0222905 |
| 1 hilo, cada paso + margen (control) | 0 | 0 | 0 | 0 | 0 |

Todas las ejecuciones terminaron los 1000 pasos, conservaron IDs, radios y celda, y produjeron arrays finitos con 4000 partículas y fracción sólida 0,60. Los errores se comparan con la simulación inicial de un hilo y búsqueda cada paso, usando distancia periódica para posiciones. No se ha fijado una tolerancia universal de aceptación física.

### Distribución del tiempo de la referencia

Medianas de los cronómetros en sus tres repeticiones (algunas fases están anidadas):

| Fase | Mediana (s) |
| --- | ---: |
| `ExplicitStrategy.Initialize` | 0.0662 |
| `ExplicitStrategy.InitializeSolutionStep` | 2.0122 |
| `ExplicitStrategy.SolveSolutionStep` | 94.1409 |
| `ExplicitStrategy.FinalizeSolutionStep` | 1.0737 |
| `ExplicitStrategy.Finalize` | 0.0000 |
| `DEMAnalysisStage.Initialize` | 0.2316 |
| `DEMAnalysisStage.InitializeSolutionStep` | 2.6265 |
| `DEMAnalysisStage.FinalizeSolutionStep` | 1.1324 |
| `DEMAnalysisStage.OutputSolutionStep` | 0.0186 |
| `DEMAnalysisStage.Finalize` | 0.0062 |
| `DEMAnalysisStage.RunSolutionLoop` | 98.0468 |

El cronómetro de `SolveSolutionStep` incluye la llamada al C++ desde Python. La comparación de frecuencias evidencia el coste evitable asociado a buscar y mantener vecinos cada paso; no mide por separado el tiempo de cada función C++.

## Caso y metodología

- Kratos `10.2."1"-fix-stress-calculation-66dbb226f8-Release-x86_64`, commit
  `66dbb226f80dc78d5ff3985351effb03798ad2b8`, GCC 13.3, Python 3.12.3,
  compilación Release (`-O3 -DNDEBUG`) con OpenMP.
- Intel Core i7-4790, cuatro núcleos físicos y ocho hilos lógicos.
- 4000 esferas de radio 0,005 m, fracción sólida nominal **0,60**, celda
  periódica cúbica de lado 0,1516942506995828 m.
- Packing generado por `progressive_growth`, semilla 20260917; solapamiento
  máximo inicial 0,0200045187, permitido 0,02 más tolerancia 0,00001.
  La fracción sólida suma volúmenes individuales, sin descontar solapamientos.
- Velocidad inicial isotrópica de módulo 0,1 m/s; gravedad nula; densidad
  2500 kg/m³, Young 10⁷ Pa, Poisson 0,25; Hertz viscoso Coulomb,
  fricción estática/dinámica 0,5/0,4 y restitución 0,8.
- 1000 pasos de 10⁻⁶ s hasta 0,001 s; Euler simpléctico, rotación directa.
  Se mantiene la física, el paso temporal y el packing en todas las variantes.
- Cada repetición arranca en un proceso independiente y un directorio nuevo,
  copiando exactamente el mismo caso inicial. No se hereda el estado final
  de otra variante. Las simulaciones se ejecutan secuencialmente.
- Tiempo de pared del proceso completo: incluye importación, lectura,
  inicialización, integración y escritura del estado final. Excluye generación
  del packing y orquestación/persistencia HDF5 de JPGen.
- Tres repeticiones por variante (excepto el control aislado, una), orden
  mezclado dentro de cada campaña con semilla 20260921;
  se informan mediana y rango. Los cronómetros de fase usan `perf_counter`;
  hay medidas anidadas, por lo que no deben sumarse indiscriminadamente.
- Se comparan IDs, radios, tiempo, celda, finitud de arrays, posiciones con
  distancia periódica, velocidades, velocidades angulares, energía cinética
  traslacional más rotacional y momento lineal.

`cProfile` se ejecutó por separado. En esta instalación sus estadísticas
no recogen todo el tiempo real del solver (por ejemplo, 3,60 s registrados
frente a 48,15 s de pared). Por ello no se usan sus porcentajes para atribuir
coste al código nativo. Los archivos `.pstats` se conservan como evidencia;
la atribución publicada se basa en cronómetros explícitos alrededor de las
fases Python y de las llamadas al solver C++.

## Interpretación de la búsqueda de vecinos

`case_writer.py` fija actualmente `NeighbourSearchFrequency=1`. En
`ExplicitSolverStrategy::SolveSolutionStep`, cada paso realiza operaciones de
búsqueda DEM/FEM, fuerzas e integración. `SearchDEMOperations` vuelve a buscar,
reconstruye listas y punteros y actualiza el historial de vecinos. El buscador
`OMP_DEMSearch` construye de nuevo su estructura de bins en cada búsqueda.

Espaciar la búsqueda reduce ese trabajo, pero requiere incluir candidatos aún
sin contacto. Los experimentos con margen fijan `DeltaOption="Absolute"` y
`SearchTolerance=5e-5` m. Esta tolerancia amplía los radios de búsqueda; no
cambia el radio físico de las partículas. Una variante sin margen sirve como
control para detectar el error de espaciar búsquedas sin suficientes candidatos.

Las diferencias medidas al final de 1 ms no prueban equivalencia de todas las
trayectorias ni validez para tiempos mayores. Antes de adoptar una frecuencia
fija en producción debe garantizarse que el movimiento relativo acumulado
entre búsquedas no agota el margen. Una implementación general debe disparar
una nueva búsqueda por desplazamiento acumulado y considerar también la
deformación de la celda. Este estudio mantiene la celda fija y no representa
protocolos de servo ni mediciones de tensión por paso.

## Reproducción

La configuración exacta y los resultados grandes se guardan en
`benchmarks/kratos_4000/`, que está ignorado por Git. Los scripts del estudio
están en `tools/` y no son una suite de tests.

```bash
.venv/bin/python -m jpgen examples/kratos_profile_4000.yaml
# Sustituir RUN por el directorio creado por la ejecución anterior.
.venv/bin/python tools/profile_kratos.py runs/RUN/dem \
  benchmarks/kratos_4000/new_measurements --phases --repeats 3 \
  --variants baseline threads2 threads4 search10 search20 search10_no_skin
.venv/bin/python tools/summarize_kratos_profile.py \
  benchmarks/kratos_4000/new_measurements runs/RUN/dem/native_results
# Ejecutar después de la matriz principal, sin simultanear procesos:
.venv/bin/python tools/profile_kratos.py runs/RUN/dem \
  benchmarks/kratos_4000/new_combined --phases --repeats 3 \
  --variants search10_threads2 search10_threads4
.venv/bin/python tools/profile_kratos.py runs/RUN/dem \
  benchmarks/kratos_4000/new_control --phases --repeats 1 --variants skin_only
```

Para obtener un perfil `cProfile` independiente usar `--profile` y otro
nombre de directorio. Los destinos no se sobrescriben. Cada caso conserva
parámetros, logs, estado final, informe de ejecución y tiempos. El archivo
`provenance.json` registra plataforma, commit y hashes del packing y bibliotecas.

## Oportunidades en el C++ que requieren otro experimento

La inspección del código identifica candidatos concretos, pero este estudio no
mide su mejora individual ni modifica o recompila Kratos:

1. Reutilizar capacidad de bins y buffers de resultados en
   `custom_utilities/omp_dem_search.h`, especialmente `GetBins` y
   `SearchElementsInRadiusExclusiveImplementation`. Actualmente se construye
   una estructura nueva en cada búsqueda. Reutilizar memoria exige actualizar
   correctamente la ocupación espacial y la periodicidad.
2. Reducir las asignaciones y búsquedas de `std::map` por hilo en
   `ExplicitSolverStrategy::SearchNeighbours`, conservando la reciprocidad de
   vecinos y el historial de contactos. No se puede eliminar ese mantenimiento
   sólo porque el caso tenga un material.
3. Investigar las clonaciones de ley constitutiva por contacto en
   `SphericParticle::EvaluateBallToBallForcesForPositiveIndentiations` y
   `pCloneDiscontinuumConstitutiveLawWithNeighbour`. Cualquier reutilización debe
   respetar el estado mutable de la ley y la seguridad entre hilos; no se ha
   demostrado que una caché sea válida para todas las leyes.

Para priorizar estos cambios internos haría falta muestreo nativo o cronómetros
C++ dentro de búsqueda, fuerzas e integración. Los cronómetros de este estudio
miden la llamada nativa completa; no separan esos tres componentes.

## Condiciones de la máquina

La máquina no estaba aislada: durante el estudio `/proc/loadavg` llegó a indicar
aproximadamente 10 para ocho CPU lógicas. No se detuvieron procesos ajenos ni se
fijaron frecuencias de CPU o afinidad. Las medianas y rangos describen esta
sesión compartida; no son garantías de velocidad ni intervalos de confianza.
Las variantes se ejecutaron de una en una y en orden mezclado para reducir,
sin eliminar, el efecto de la carga cambiante. La comparación de arrays finales
es independiente de esa variación de tiempos.

## Aplicación práctica

La opción de hilos ya está soportada por JPGen, dentro de `dem`:

```yaml
backend_options:
  installation: Kratos/bin/Release
  threads: 4
  timeout_seconds: 600.0
```

`NeighbourSearchFrequency` y `SearchTolerance` se modifican únicamente en las
copias experimentales de `ProjectParametersDEM.json`; actualmente no son
opciones públicas del backend JPGen. Los scripts conservan todos los casos
preparados para poder inspeccionarlos y volver a ejecutarlos. No se cambia el
valor global de búsqueda ni se altera el paso temporal del usuario.
