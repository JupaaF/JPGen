# Estudio de placement: núcleos C++ y packings de fracción sólida 0,62

Se implementaron dos núcleos C++17: evaluación de contactos por bloques e
inserción mediante celdas. La referencia para medir la ganancia es la versión
Python **ya optimizada**, no la implementación anterior a las optimizaciones
1–5. El commit de partida del estudio es
`1c35f9215d35c491aadbcebd8ff903b9eb1c2457`.

## Qué mostró el perfilado

Se perfilaron ejecuciones completas de inserción de 5.000 partículas, relajación
de 1.500 y crecimiento de 1.500 hasta una fracción sólida nominal de 0,62.

| Área en Python | Evidencia de cProfile | Decisión |
| --- | --- | --- |
| Evaluar contactos en crecimiento denso | 95,6 % del tiempo acumulado en la evaluación; 13,7 % del total en `np.add.at` | Fusionar geometría, solapamiento y acumulación en C++ |
| Evaluar contactos en relajación | 94,5 % del tiempo acumulado | Usar el mismo núcleo C++ |
| Inserción | 66,6 % de tiempo propio en `_place_particles`, además de consultas a diccionarios y muchas operaciones pequeñas | Mover las celdas y la aceptación de candidatos a C++ |
| Construir candidatos en crecimiento denso | 3,1 % acumulado | Conservar `cKDTree` y la lista de vecinos reutilizable |
| Control de etapas y convergencia | Coste reducido frente a evaluar contactos | Conservarlo en Python |

Los porcentajes acumulados incluyen funciones hijas y no se suman entre sí. El
tiempo propio de una función Python tampoco equivale exclusivamente al tiempo
del intérprete: puede incluir operaciones nativas que el perfilador no separa.

Los perfiles posteriores muestran que el núcleo de contactos representa cerca
del 40 % del tiempo atribuido en el caso denso; la búsqueda y mantenimiento de
vecinos adquieren más peso relativo. En este entorno, cProfile deja sin atribuir
parte del tiempo de la inserción nativa. El script registra también tiempo de
pared y su relación con el tiempo atribuido para hacer visible esa limitación.
Las aceleraciones de la siguiente tabla se obtuvieron **sin cProfile**.

## Resultado medido

Medianas de tres ejecuciones por caso y backend, realizadas secuencialmente.
El cálculo exhaustivo de geometría, la comparación y la exportación quedan
fuera del intervalo cronometrado.

| Caso | Python optimizado | C++ | Aceleración |
| --- | ---: | ---: | ---: |
| Inserción, 5.000 partículas | 1,099 s | 0,196 s | 5,61× |
| Relajación, 1.500 partículas | 1,377 s | 0,394 s | 3,50× |
| Crecimiento con siete etapas rechazadas | 0,729 s | 0,252 s | 2,89× |
| Crecimiento a 0,62, 512 partículas | 4,090 s | 1,024 s | 3,99× |
| Crecimiento a 0,62, 1.500 partículas | 23,281 s | 5,108 s | 4,56× |

Entorno: Linux x86-64, Python 3.12.3, NumPy 2.5.3, SciPy 1.18.1, pybind11 3.1.0
y GCC 13.3.0. Los tiempos varían con la máquina y la carga; tres repeticiones
no constituyen una estimación estadística amplia. En problemas pequeños o con
muchas coincidencias de centros el beneficio puede ser menor.

## Conservación de resultados

Los 24 casos ground truth previos y los dos nuevos casos densos mantienen
**posiciones idénticas elemento a elemento, estadísticas idénticas y diferencias
geométricas cero**. Esto incluye el fallo deliberado por perturbaciones agotadas
y el crecimiento con rollback. Cuatro casos adicionales conservan esos resultados
forzando el límite de caché a un par, para recorrer la búsqueda por bloques.

La geometría se comprobó mediante todos los pares, independientemente de los
núcleos nativos y del índice espacial. La auditoría de producción coincide con
esas métricas, acepta los 25 resultados convergentes y rechaza el fallo esperado.
Las huellas de las fuentes y versiones se conservan con cada captura.

Para mantener la reproducibilidad:

- Python conserva el RNG de NumPy, el orden de inserción y el número de draws.
- La acumulación de correcciones respeta los bloques originales: primero todos
  los extremos `i`, después todos los extremos `j`.
- NumPy conserva la reducción de energía usada para detectar estancamiento.
- Si hay centros coincidentes que necesitan una dirección aleatoria, esa
  evaluación se repite en Python sin haber consumido RNG en C++.
- Se compila sin `fast-math` ni contracción de operaciones en FMA. La igualdad
  exacta comprobada en este entorno no garantiza igualdad entre compiladores,
  plataformas o versiones diferentes.

## Packings densos generados

La fracción sólida nominal es `sum(4*pi*r**3/3) / volumen_caja`. Con solapamiento
permitido no representa exactamente el volumen de la unión de las esferas.
Ambos casos usan una caja periódica de longitudes `[1, 1.1, 0.9]`, radios variados,
solapamiento máximo configurado de `0.005` y tolerancia de `1e-5`.

| Partículas | Semilla | Fracción sólida | Iteraciones | Exceso máximo sobre el límite |
| --- | ---: | ---: | ---: | ---: |
| 512 | 20260917 | 0,6200000000000001 | 3.176 | 8,203e-6 |
| 1.500 | 20260918 | 0,6200000000000003 | 6.352 | 7,996e-6 |

Los dos convergen en diez etapas aceptadas. Sus archivos están en:

- `benchmarks/placement/cpp_study/packings/growth_dense_062_512/`
- `benchmarks/placement/cpp_study/packings/growth_dense_062_1500/`

Cada directorio contiene `packing.h5`, `particles.vtp` y `metadata.json`. La
lectura posterior del HDF5 recupera exactamente posiciones y radios. El VTK
contiene centros y radios para visualizar las esferas mediante glyphs.

Estos casos usan los streams explícitos del benchmark: radios con
`default_rng(seed + 1000)` y placement con `default_rng(seed)`. Su configuración
HDF5 identifica el caso de benchmark; no es un YAML de replay del generador de
producción, que usa otro esquema de streams.

## Compilación y selección

`python -m pip install -e .` compila la extensión opcional con un compilador
C++17 disponible. `pybind11` es una dependencia de construcción, no de ejecución.
La integración sigue la documentación de
[compilación con setuptools](https://pybind11.readthedocs.io/en/stable/compiling.html#modules-with-setuptools)
y [arrays NumPy](https://pybind11.readthedocs.io/en/stable/advanced/pycpp/numpy.html).

- `JPGEN_PLACEMENT_BACKEND=auto`: usa C++ cuando está instalado; si no, Python.
- `JPGEN_PLACEMENT_BACKEND=python`: fuerza Python para comparar o diagnosticar.
- `JPGEN_PLACEMENT_BACKEND=native`: exige la extensión y falla si no está.
- `JPGEN_BUILD_NATIVE=0`: desactiva la extensión al construir el paquete.

La selección de ejecución se hace al importar el módulo. Después de modificar
`_kernels.cpp` hay que reinstalar para recompilar. No se modifica el esquema de
configuración de placement. Los arrays que no cumplen el formato del núcleo de
evaluación continúan por Python.

Se construyeron y abrieron desde directorios aislados un wheel nativo y otro
Python puro a partir del sdist. El sdist incluye el C++; el wheel nativo carga la
extensión y el wheel puro selecciona Python sin depender de un binario local.

## Archivos del estudio y reproducción

Las capturas y herramientas están en `benchmarks/placement/`. Ese directorio ya
estaba excluido por el `.gitignore` del proyecto: son artefactos locales del
estudio. Esta documentación y los cambios de implementación sí están fuera de
esa exclusión.

Dentro de `cpp_study/`, `python_reference`, `python_edges` y
`python_dense_medians` contienen las referencias medidas; `native_reference`,
`native_edges` y `native_dense` sus comparaciones. `python_dense` conserva la
primera captura densa anterior al cambio de backend. También se guardan perfiles,
`native_streaming`, `audit.json`, `packaging.json` y `environment.json`.

Con los artefactos locales conservados, usar directorios de salida nuevos:

```bash
JPGEN_PLACEMENT_BACKEND=python .venv/bin/python benchmarks/placement/profile_placement.py \
  --case insertion_5000 --case relaxation_1500 --case growth_dense_062_1500 \
  --output /tmp/jpgen-profile-python

JPGEN_PLACEMENT_BACKEND=native .venv/bin/python benchmarks/placement/benchmark.py \
  --reference benchmarks/placement/cpp_study/python_dense_medians \
  --output /tmp/jpgen-dense-native --repeats 3

.venv/bin/python benchmarks/placement/export_packings.py \
  --capture /tmp/jpgen-dense-native --output /tmp/jpgen-dense-packings
```

Las comparaciones generan informes numéricos; no son una suite de tests ni
codifican el resultado de la comparación en el código de salida.
