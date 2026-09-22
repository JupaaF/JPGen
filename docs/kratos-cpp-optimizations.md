# Optimización del C++ de Kratos: resultados con 4000 partículas

**Estado: rollback realizado el 22 de septiembre de 2026.** El código de Kratos y las bibliotecas DEM del directorio de compilación están restaurados a la versión original. La instalación habitual conserva sus bibliotecas originales. Este documento y sus datos describen un experimento archivado; las optimizaciones no están aplicadas.

Las dos optimizaciones se implementaron experimentalmente y se evaluaron mediante **25 simulaciones completas**, con 4000 partículas, fracción sólida nominal 0,60 y búsqueda de vecinos en **cada paso**. Combinadas reducen el tiempo mediano un **20,03 % con un hilo** y un **30,31 % con cuatro hilos**. Todos los arrays finales coinciden exactamente con la referencia original.

La mejora mayor de las dos opciones individuales fue la reconstrucción de vecinos indexados. La combinación obtuvo los mejores tiempos de este caso y redujo también el consumo de CPU, con un pequeño incremento de memoria residente. Se decidió revertir el cambio conjunto para retomar, si procede, modificaciones pequeñas e independientes. El binario experimental queda archivado en `benchmarks/kratos_cpp/archive/experimental_installation`, fuera de su antigua ruta de uso.

## Tiempos medidos

Cada fila tiene tres repeticiones por número de hilos. La referencia de cada columna es el algoritmo original del **mismo binario recompilado**, con las dos opciones desactivadas. Las aceleraciones comparan el mismo número de hilos; no incluyen cambios de paso temporal o frecuencia de búsqueda.

| Variante | 1 hilo: mediana (s) | Reducción de tiempo | 4 hilos: mediana (s) | Reducción de tiempo |
| --- | ---: | ---: | ---: | ---: |
| Referencia, opciones desactivadas | 44.56 | 0.00 % | 21.01 | 0.00 % |
| 1. Reutilización de memoria | 40.30 | 9.57 % | 18.50 | 11.95 % |
| 2. Vecinos indexados | 37.44 | 15.98 % | 17.50 | 16.70 % |
| 1 + 2 | 35.64 | 20.03 % | 14.65 | 30.31 % |

**Aceleración combinada: 1,25× con un hilo y 1,43× con cuatro.** Reducción de tiempo y aceleración son métricas distintas.

| Variante | Hilos | Rango de tiempo (s) | CPU mediana (s) | RSS máximo: mediana (MiB) | Paso nativo: mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Referencia, opciones desactivadas | 1 | 41.25–48.47 | 44.51 | 114.21 | 42.48 |
| 1. Reutilización de memoria | 1 | 40.20–43.45 | 40.25 | 115.12 | 38.36 |
| 2. Vecinos indexados | 1 | 37.44–42.71 | 37.39 | 115.02 | 35.58 |
| 1 + 2 | 1 | 35.54–35.69 | 35.58 | 115.34 | 33.76 |
| Referencia, opciones desactivadas | 4 | 20.53–21.26 | 79.36 | 115.66 | 18.89 |
| 1. Reutilización de memoria | 4 | 16.95–18.76 | 72.24 | 115.79 | 16.64 |
| 2. Vecinos indexados | 4 | 16.85–17.71 | 65.63 | 115.94 | 16.03 |
| 1 + 2 | 4 | 14.60–16.10 | 57.07 | 116.39 | 13.27 |

Con ambas opciones, el consumo de CPU acumulado entre hilos baja de 44,51 a 35,58 s con un hilo y de 79,36 a 57,07 s con cuatro. CPU no equivale a energía eléctrica. El RSS es el máximo de cada proceso, medido por `/usr/bin/time`; se informa su mediana.

El tiempo total incluye importación, inicialización, los 1000 pasos y escritura del estado final. Excluye generar el packing, compilar y copiar entradas. El paso nativo corresponde al cronómetro de `ExplicitStrategy.SolveSolutionStep`, sin separar sus funciones C++ internas.

## Cambios evaluados y revertidos

1. **Memoria de búsqueda reutilizable** (`KRATOS_DEM_REUSE_SEARCH_STORAGE=1`). En `omp_dem_search.h`, conserva los bins periódicos y la capacidad de los buffers por hilo. Vacía y rellena las celdas en cada búsqueda, con el orden de inserción original. Cambios de cantidad de partículas o límites del dominio reconstruyen la estructura. En dominios abiertos conserva el cálculo original del dominio y sólo reutiliza los buffers. Los punteros propietarios de los buffers temporales se liberan después de copiar los resultados.

2. **Vecinos indexados** (`KRATOS_DEM_INDEXED_NEIGHBOURS=1`). En `explicit_solver_strategy.{h,cpp}`, reemplaza los mapas `std::map` temporales por hilo y el vector temporal por partícula por listas persistentes indexadas. Mantiene un índice por puntero que se reconstruye si cambia la población o su orden; no presupone IDs consecutivos. Conserva los filtros, reciprocidad, orden de recorrido por hilo y actualización del historial de contactos. La comprobación lineal de duplicados permanece.

Para alojar la caché fue necesario corregir la interfaz Python en `add_custom_strategies_to_python.cpp`: ahora construye la clase derivada `OMP_DEMSearch`, cuyos miembros contienen la caché, y su constructor reenvía los límites de dominio a la clase base. El nombre público y los argumentos permanecen iguales. La primera versión compilada fallaba al acceder al almacenamiento inexistente de la derivada; el diagnóstico con GDB se conserva en `benchmarks/kratos_cpp/crash-gdb.log`. Esa versión fallida no participa en las tablas.

En el experimento, los interruptores se leían al construir el buscador y el solver y sólo el valor exacto `1` los activaba. Estos interruptores ya no existen en el código restaurado. El parche completo se conserva únicamente como referencia histórica en [kratos-dem-search-optimizations.patch](../patches/kratos-dem-search-optimizations.patch), porque `Kratos/` está ignorado por el repositorio principal.

## Caso y validación

- Kratos `66dbb226f80dc78d5ff3985351effb03798ad2b8`, Release, GCC 13.3 y OpenMP; CPU Intel Core i7-4790.
- Mismo packing y física del [estudio inicial](kratos-performance.md): 4000 esferas de radio 0,005 m, celda periódica cúbica fija, semilla 20260917, fracción sólida nominal 0,60; Hertz viscoso Coulomb.
- 1000 pasos de 1 µs, tiempo final 0,001 s. `NeighbourSearchFrequency=1`, margen de búsqueda cero.
- Todos los archivos de entrada se copiaron sin cambios y se verificaron por SHA-256 en las 25 ejecuciones.
- Una ejecución de control con la biblioteca original y 24 del binario recompilado: cuatro configuraciones × dos números de hilos × tres repeticiones. El control original tardó 50,24 s y produjo arrays idénticos; su única medida no se usa para calcular aceleraciones.
- Después de verificar la referencia recompilada, ejecución secuencial en orden mezclado con semilla 20260922; sin simultanear simulaciones.
- Se verificó la ubicación real de las bibliotecas cargadas mediante `/proc/self/maps`, además de registrar sus hashes.
- Las 25 simulaciones completaron 1000 pasos, conservaron 4000 partículas y fracción 0,60, y produjeron arrays finitos.
- IDs, radios, posiciones, velocidades y velocidades angulares coinciden exactamente mediante `np.array_equal`, ordenados por ID. Diferencias máximas de posición, velocidad, velocidad angular, energía cinética y momento lineal: **cero** en todos los casos.
- Energía cinética final: 0,007024541766673227 J. El caso incluye dos partículas cuyo estado final refleja un cruce periódico.

La máquina no estaba aislada: la carga de un minuto registrada al iniciar los casos varió entre 1,52 y 4,35. Se publican medianas y rangos; tres repeticiones no constituyen una garantía universal de aceleración. Los tiempos de esta campaña no deben compararse directamente con los de otra sesión de carga distinta.

La equivalencia se ha validado para esta celda fija y población constante. No se ha establecido todavía para MPI, inlets/eliminación de partículas, dominios abiertos o protocolos que deforman la celda. Tampoco se ha medido el comportamiento a tiempos físicos mayores o con otros tamaños de población.

## Rollback y conservación del estudio

Se revirtió únicamente el parche de este experimento. `git -C Kratos status --short` quedó vacío, incluido el archivo nuevo de interruptores. Las bibliotecas DEM de `Kratos/build/Release/applications/DEMApplication` se restauraron desde la copia original y se verificaron por SHA-256. Las de `Kratos/bin/Release` ya coincidían con la referencia y se conservaron.

Los cuatro archivos objeto afectados se retiraron del directorio de compilación y se archivaron, para que una futura compilación los reconstruya desde las fuentes restauradas. No fue necesario recompilar para el rollback. El entorno experimental y su script de compilación se movieron a `benchmarks/kratos_cpp/archive/`; su antigua ruta `installations/experimental` ya no está disponible.

El [registro del rollback](kratos-cpp-rollback.json) contiene el commit, los hashes restaurados y los archivos objeto invalidados. Las mediciones, logs, entradas y estados finales se conservan sin modificaciones. Las rutas y hashes incluidos en los datos son los de la campaña histórica, anteriores al archivado.

Para volver a consultar el resumen de las mediciones guardadas:

```bash
.venv/bin/python tools/summarize_kratos_cpp.py \
  benchmarks/kratos_cpp/measurements_v2
```

Los scripts de perfilado se conservan como material del estudio. No se debe interpretar su presencia ni la del parche como una activación de las optimizaciones. El binario archivado sirve como evidencia del experimento, no como instalación de uso habitual.

## Posible continuación gradual

Para retomar el trabajo se propone empezar por **vecinos indexados de forma aislada**, que fue la mejora individual más alta. La reutilización de buffers y la reutilización de bins pueden separarse en cambios posteriores; esta última requiere revisar primero la construcción de la clase derivada en la interfaz Python.

Cada cambio debería medirse por separado con la misma referencia, antes de combinarlo con otro. Este plan no se ha aplicado tras el rollback. El parche conjunto conserva la implementación exacta medida, pero no se recomienda reaplicarlo completo como siguiente paso.

## Artefactos

- [Datos completos, hashes y tiempos por fase](kratos-cpp-results.json).
- [Registro del rollback](kratos-cpp-rollback.json).
- [Parche C++ e interfaz Python](../patches/kratos-dem-search-optimizations.patch).
- [Ejecutor de la campaña](../tools/profile_kratos_cpp.py), [medición del proceso](../tools/kratos_cpp_worker.py) y [resumen](../tools/summarize_kratos_cpp.py).
- Entradas, logs, estados finales y métricas: `benchmarks/kratos_cpp/measurements_v2/`.
- Log de compilación: `benchmarks/kratos_cpp/build.log`; estado: `build.exit`.
- Diagnóstico de la primera versión y compilación anterior: `benchmarks/kratos_cpp/crash-gdb.log` y `benchmarks/kratos_cpp/build_history/attempt_1/`.

La validación se realizó con simulaciones; no se añadieron tests.
