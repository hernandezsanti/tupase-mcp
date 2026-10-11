# tupase-mcp

[English](README.md) | **Español**

Busca, reserva y cancela clases de [Tupase](https://www.tupaseapp.com) hablando con Claude, Cursor o cualquier cliente [MCP](https://modelcontextprotocol.io).

> **Cliente no oficial.** Este proyecto no tiene ninguna relación con Tupase ni cuenta con su aprobación. Usa la API privada de la app con **tu propia cuenta** y bajo tu responsabilidad: Tupase podría cambiarla o restringir el acceso en cualquier momento.

Corre en tu computadora y le habla directamente a Tupase: no hay ningún servidor intermedio ni nadie más que vea tus datos.

## Qué puedes pedirle

![Demo: buscar clases de pilates en Pocitos y reservar](docs/demo.gif)

*Búsqueda real en Tupase. La reserva queda en vista previa hasta que confirmas, así que en esta demo no se reservó nada.*

Otras cosas que funcionan:

- "¿Cuáles son mis reservas de esta semana? Muéstrame el QR de la primera."
- "Guarda Zona Fit como favorito y búscame solo en mis favoritos."
- "¿Cuál es mi rutina? Dime qué fechas puedo reservar de mis clases habituales."
- "¿Qué barrios tienen actividad esta semana?"
- "Cancela mi reserva de mañana."

## Instalación

Necesitas [uv](https://docs.astral.sh/uv/).

**1. Inicia sesión una sola vez.** Te pide el correo y la contraseña de tu cuenta de Tupase. La contraseña no se guarda: solo queda un token de renovación en el llavero de tu sistema.

```bash
uvx tupase-mcp login
```

**2. Agrega el servidor a tu cliente.**

Claude Code:

```bash
claude mcp add tupase -- uvx tupase-mcp
```

Claude Desktop (`claude_desktop_config.json`) y Cursor (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "tupase": { "command": "uvx", "args": ["tupase-mcp"] }
  }
}
```

Reinicia el cliente y pídele algo, por ejemplo "¿quién soy en Tupase?" para comprobar que la sesión funciona.

Para cerrar sesión: `uvx tupase-mcp logout`.

**Linux sin escritorio (servidores, WSL, Docker):** no hay un llavero del sistema disponible. Instala un backend de Secret Service (por ejemplo `gnome-keyring`) o el paquete `keyrings.alt` antes de iniciar sesión; de lo contrario, `login` indicará que no se pudo usar el llavero.

## Tools

| Tool | Qué hace |
|---|---|
| `buscar_actividades` | Busca por fecha y hora, disciplina, barrio, lugar, cercanía o solo favoritos. Máximo 7 días y 50 resultados por consulta |
| `listar_disciplinas` | Disciplinas disponibles en un rango de fechas |
| `listar_barrios` | Barrios con actividad en un rango de fechas |
| `ver_lugar` | Un lugar con todas sus actividades de los próximos 7 días |
| `mis_reservas` | Tus reservas, con el estado real (cruza con tus notificaciones) |
| `reservar` | Reserva una actividad |
| `cancelar_reserva` | Cancela una reserva por su código |
| `ver_qr_reserva` | Devuelve el código y el QR de una reserva como imagen |
| `mi_rutina` | Detecta tus clases habituales (mismo lugar, día y hora, al menos 2 veces) y lista sus próximas fechas reservables |
| `agregar_favorito`, `quitar_favorito`, `mis_favoritos` | Favoritos de lugares, guardados en tu computadora |
| `quien_soy` | Tu perfil y el estado de la cuenta |
| `editar_perfil` | Actualiza los datos de tu perfil |
| `mis_notificaciones` | Tus notificaciones |
| `mis_medios_de_pago` | Tu medio de pago registrado (solo lectura; Tupase puede responder con un error según la cuenta) |

## Seguridad

`reservar`, `cancelar_reserva` y `editar_perfil` cambian datos de tu cuenta, así que tienen un paso extra: sin `confirmar=true` solo devuelven una vista previa, y Claude debe mostrártela y esperar tu confirmación antes de repetir la llamada.

- La marca "destructiva" de una tool es solo una pista: cada cliente MCP decide si te pide confirmación, y si elegiste "permitir siempre" para esas tools, se ejecutan sin preguntar. **No elijas "permitir siempre" para esas tres tools.**
- Los resultados de Tupase incluyen texto de terceros (nombres de lugares, notificaciones) que podría contener instrucciones escondidas para el modelo. El paso `confirmar` reduce ese riesgo, pero no lo elimina: revisa lo que te muestra Claude antes de confirmar.

## Notas

- **Horas pico:** Tupase devuelve como máximo 499 resultados por consulta. Para entregar todo, el servidor parte la búsqueda por tramos y por disciplina; una hora completa en horario pico puede tardar unos 20 segundos. Filtrar por disciplina, barrio o lugar la hace instantánea.
- **Estado de las reservas:** algunas quedan como "Pendiente de confirmación" hasta que el lugar las confirma; `mis_reservas` las marca como confirmadas cuando Tupase te avisa que tienes el cupo.
- **Horarios:** todas las fechas se interpretan y se muestran en hora de Montevideo.
- **Si algo falla:** el servidor escribe sus mensajes de diagnóstico en el log del cliente MCP (stderr), nunca tus credenciales.

## Privacidad

- El token de renovación se guarda en el llavero del sistema (Keychain, Credential Manager o Secret Service). Tu contraseña nunca se guarda.
- Los favoritos se guardan en un archivo local en el directorio de datos de tu usuario.
- Nada se envía a terceros: solo hay tráfico entre tu computadora, Auth0 (el inicio de sesión de Tupase) y la API de Tupase.

## Desarrollo

```bash
uv sync
uv run pytest
uv run ruff check --fix . && uv run ruff format .
```

Los tests no usan la red ni tu llavero. Para probar las tools a mano: `npx @modelcontextprotocol/inspector uv run tupase-mcp`. Los endpoints que usa el cliente están descritos en [`docs/api.md`](docs/api.md).

## Licencia

MIT
