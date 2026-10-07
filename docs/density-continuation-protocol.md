# Protocolo DEM: `density_continuation`

Disponible en Kratos y LIGGGHTS. Esta etapa aumenta la fracción sólida mediante
ciclos de fricción cero bajo confinamiento isotrópico, usando un único solver
activo. No hay restart, rollback, decrementos adaptativos ni listas de objetivos.
Las opciones del protocolo anterior se rechazan.

## Configuración

```yaml
name: density
control:
  type: density_continuation
  target: 0.620
  density_atol: 0.0002
  confinement:
    target_pressure: 5000.0
    pressure_rtol: 0.01
    max_velocity: 0.01
    loading_factor: 0.8
    update_every_steps: 1
  relaxation:
    condition:
      all:
        - {observable: unbalanced_force, op: below, value: 1.0e-3}
      hold_for: 0.005
    density_stability:
      window: 0.005
      max_range: 0.00005
until: {observable: density_targets_completed, op: above, value: 1}
max_duration: 10.0
```

`target` es la fracción sólida nominal: suma de los volúmenes de las esferas
entre el volumen de la celda, sin descontar solapamientos. La densidad del
material y los radios permanecen constantes. `density_atol` permite aceptar
un valor ligeramente inferior: `solid_fraction + density_atol >= target`.
Cualquier sobrepaso es correcto, siempre que el estado esté estabilizado con
la fricción normal. No se impone un límite universal de densidad.

## Ciclo

1. Registrar como fricción normal el par estático/dinámico activo al entrar.
2. Estabilizar la muestra con esa fricción, manteniendo el servo.
3. Si alcanza el objetivo dentro de la tolerancia, publicar el estado aceptado
   y continuar con la siguiente etapa sin hacer ningún reset.
4. Si queda por debajo, guardar un checkpoint científico del packing estable
   **antes** de cambiar ambos coeficientes de fricción a cero.
5. Ejecutar exactamente 100 pasos del solver con fricción cero, manteniendo el servo.
6. Restaurar exactamente los dos coeficientes normales y volver a estabilizar.
7. Comprobar el objetivo. Si aún queda por debajo, volver al paso 4.

La fase de 100 pasos sigue el método improved servo control de
[DEMGen](https://github.com/ChengshunShang1996/DEMGen/blob/7bffd9e5683ce10a2ca073f635b0c5c745c687ea/src/utilities/improved_radius_expansion_with_servo_control_method_run.py#L231-L238).
JPGen exige una nueva estabilización con fricción normal, acepta sobrepasos
y conserva un checkpoint científico antes de cada reset.

No hay límite de cantidad de ciclos. `max_duration` limita toda la etapa,
incluida la estabilización inicial, los 100 pasos a fricción cero y la
estabilización posterior de todos los ciclos. Si el
objetivo no se ha aceptado al agotarlo, la ejecución falla con `max_duration`,
conserva los checkpoints científicos y no empieza la siguiente etapa. El
cumplimiento en el último paso permitido tiene prioridad sobre el fallo.
En un fallo por duración se restaura la fricción normal. No hay un timeout
separado por fase.

Las fases con fricción normal exigen simultáneamente presión dentro de `pressure_rtol`,
desequilibrio de fuerzas dentro de su umbral, y variación
de densidad inferior a `max_range` durante la ventana `window`. La condición
conjunta debe mantenerse durante `hold_for`. Los historiales de estabilización
se vacían al restaurar la fricción normal. Los 100 pasos a fricción cero
no requieren estabilización ni evalúan la aceptación del objetivo. Una densidad
transitoria nunca acepta el objetivo. La energía cinética se registra para
análisis y no forma parte de los umbrales de estabilización. La duración de esta fase es fija y no
es configurable; si `max_duration` se agota antes, la etapa falla.

## Resultados

Los checkpoints son pares NPZ/JSON bajo `stages/dem/results/states/`, indexados
como `kind: density_checkpoint`, `phase: before_reset` en `states.jsonl`.
Conservan IDs, posiciones, radios, velocidades, velocidades angulares y celda.
El índice registra ciclo, observables y ambos coeficientes normales.
Son estados para análisis; no incluyen serializaciones ni capacidades de restart.

El objetivo aceptado se indexa como `density_target` con `accepted: true` y un
archivo `.target.json` de esquema `JPGen.dem.target` versión `1.1`, que registra
objetivo, tolerancia, densidad real, fricciones normales y condiciones físicas.
Los observables muestreados incluyen `density_phase` (`initial`, `zero`, `normal`)
y `cycles` fuera del diccionario numérico de observables. Todos los pasos y
tiempos avanzan de forma monótona. El checkpoint y otros eventos del mismo
paso comparten el estado científico, sin duplicar arrays.

LIGGGHTS requiere la extensión JPGen ABI 5. Ejecutar
`python tools/build_liggghts.py --jobs 4` para actualizar la biblioteca. El cambio
de fricción actualiza las propiedades y sus cachés de contacto sin reconstruir
el solver ni borrar el historial tangencial. Kratos actualiza sus subpropiedades
de contacto en el solver activo. Ambos usan el mismo controlador portable.
