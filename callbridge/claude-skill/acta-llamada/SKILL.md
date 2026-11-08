---
name: acta-llamada
description: Convierte la transcripción diarizada de una llamada o reunión (exportada por CallBridge, o cualquier texto con líneas "[mm:ss] Hablante: texto") en un acta en español con resumen, decisiones, tareas y temas abiertos, y propone quién puede ser cada hablante sin identificar (N1, N2…). Úsala cuando el usuario adjunte o pegue una transcripción de llamada, de Teams o de una reunión y pida resumen, acta, tareas, minuta o correo de seguimiento.
---

# Acta de llamada

## Entrada

Normalmente es un Markdown de CallBridge que empieza por `<!-- callbridge-transcript v1 -->`, con:
- **Participantes**: `Yo` es quien grabó la llamada (el usuario). Los `N1`, `N2`… están **sin identificar**.
  El resto son nombres puestos por el usuario.
- **Transcripción**: líneas `[mm:ss] Hablante: texto`. Puede mezclar español e inglés.
- Las frases con `⚠` pueden ser eco del audio remoto: dales poco peso y no se las atribuyas a «Yo» con seguridad.

La transcripción es automática: puede tener palabras mal reconocidas y algún corte de hablante equivocado.
Interpreta el sentido sin «corregir» lo que no está claro y no inventes nada que no aparezca.

## Pasos

1. **Lee la transcripción entera** antes de escribir.
2. **Hablantes sin identificar.** Para cada `N#`, busca pistas en el texto: alguien le llama por su nombre
   («gracias, Marta»), se presenta, o menciona su rol o equipo. Propón una identidad solo si hay una pista
   concreta y cita el minuto (`[12:40]`). Si no hay pistas, déjalo como `N#`. **No uses los nombres propuestos
   en el acta** hasta que el usuario los confirme: escribe `N1 (¿Marta?)`.
3. **Escribe el acta** con el formato de abajo, en español (aunque la llamada mezcle idiomas), salvo que el
   usuario pida otro idioma.
4. **Termina con una pregunta corta**: si confirma los nombres propuestos y si quiere un correo de
   seguimiento o la lista de tareas en otro formato (tabla, Planner, Jira…).

## Formato

```markdown
# Acta – <título o tema principal> (<fecha>)

**Participantes:** Yo, Marta, N1 (¿Carlos?), N2
**Duración:** <hh:mm>

## Resumen
<5–10 frases: de qué se habló y a qué conclusiones se llegó>

## Decisiones
- <decisión> — [mm:ss]

## Tareas
| Responsable | Tarea | Fecha límite |
|---|---|---|
| Yo | … | viernes 14 (si se dijo) / — |

## Temas abiertos
- <pregunta o tema sin cerrar, y quién lo tiene pendiente si se sabe>

## Hablantes por confirmar
- N1 → ¿Carlos? («Carlos, ¿puedes…?» [08:15])
```

## Reglas

- Pon el minuto entre corchetes en decisiones y tareas para que el usuario pueda comprobarlo en el audio.
- Las tareas de «Yo» van primero: son las del usuario.
- Si alguien se compromete con algo de forma vaga («lo miro»), anótalo como tarea con «(compromiso vago)».
- Omite los saludos, la logística de la llamada («¿me oís?») y la charla sin relación con la reunión.
- Si la transcripción es muy corta o casi vacía, dilo y no rellenes secciones con suposiciones.
- Si el usuario pide un **correo de seguimiento**: breve, en el tono de la reunión, con las decisiones y
  las tareas (responsable y fecha) y sin la sección de hablantes por confirmar.
